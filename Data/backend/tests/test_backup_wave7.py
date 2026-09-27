"""WAVE 7 — BACKUP-001..005 journaled three-DB restore + corpus inventory domain."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from Data.modules.backup import (
    RESTORE_NEW_SET_ACTIVE,
    RESTORE_OLD_SET_ACTIVE,
    RESTORE_RECOVERY_REQUIRED,
    BackupError,
    BackupService,
)


def _seed_db(path: Path, *, marker: str, with_datasets: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"
        )
        conn.execute(
            "INSERT INTO schema_migrations(version, name, applied_at) VALUES (1, ?, 'now')",
            (marker,),
        )
        conn.execute("CREATE TABLE marker(v TEXT)")
        conn.execute("INSERT INTO marker(v) VALUES (?)", (marker,))
        if with_datasets:
            conn.execute(
                """
                CREATE TABLE datasets (
                    dataset_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT 'local',
                    status TEXT NOT NULL DEFAULT 'ready',
                    description TEXT NOT NULL DEFAULT '',
                    raw_path TEXT,
                    created_at TEXT NOT NULL DEFAULT 'now',
                    updated_at TEXT NOT NULL DEFAULT 'now'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE dataset_versions (
                    version_id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL,
                    version_label TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ready',
                    kind TEXT NOT NULL DEFAULT 'materialized',
                    storage_path TEXT,
                    created_at TEXT NOT NULL DEFAULT 'now',
                    updated_at TEXT NOT NULL DEFAULT 'now'
                )
                """
            )
        conn.commit()


def _marker(path: Path) -> str:
    with sqlite3.connect(str(path)) as conn:
        row = conn.execute("SELECT v FROM marker").fetchone()
        return str(row[0]) if row else ""


class BackupWave7Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="lev-w7-")
        root = Path(self.tmp.name)
        self.control = root / "leviathan_control.db"
        self.knowledge = root / "leviathan_knowledge.db"
        self.market = root / "leviathan_market.db"
        self.artifacts = root / "artifacts"
        self.backups = root / "backups"
        self.corpus = root / "corpus"
        self.artifacts.mkdir()
        self.corpus.mkdir()
        (self.artifacts / "a.txt").write_text("a", encoding="utf-8")
        self.dataset_file = self.corpus / "ds" / "rows.jsonl"
        self.dataset_file.parent.mkdir(parents=True)
        self.dataset_file.write_text('{"id":1}\n', encoding="utf-8")

        _seed_db(self.control, marker="control-v1")
        _seed_db(self.knowledge, marker="knowledge-v1", with_datasets=True)
        with sqlite3.connect(str(self.knowledge)) as conn:
            conn.execute(
                "INSERT INTO datasets(dataset_id, name, raw_path) VALUES (?, ?, ?)",
                ("ds1", "demo", str(self.dataset_file)),
            )
            conn.execute(
                "INSERT INTO dataset_versions(version_id, dataset_id, version_label, storage_path) "
                "VALUES (?, ?, ?, ?)",
                ("v1", "ds1", "v1", str(self.dataset_file)),
            )
            conn.commit()
        _seed_db(self.market, marker="market-v1")

        self.paths = SimpleNamespace(
            control=self.control,
            knowledge=self.knowledge,
            market=self.market,
        )
        self.service = BackupService(
            database_path=self.control,
            artifacts_root=self.artifacts,
            backup_root=self.backups,
            corpus_root=self.corpus,
            database_paths=self.paths,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_backup001_corpus_inventory_reads_knowledge_not_control(self) -> None:
        # CONTROL has no dataset tables — if inventory wrongly used CONTROL, empty.
        manifest = self.service.create(note="w7-inventory")
        pub = manifest.public_dict()
        self.assertEqual(pub["truth"]["corpusInventorySourceDomain"], "KNOWLEDGE")
        self.assertEqual(manifest.metadata.get("corpusInventorySourceDomain"), "KNOWLEDGE")
        self.assertGreaterEqual(len(pub["corpusInventory"]), 1)
        paths = {e.get("absolutePath") for e in pub["corpusInventory"]}
        self.assertIn(str(self.dataset_file), paths)

    def test_backup003_refuses_without_maintenance_boundary(self) -> None:
        manifest = self.service.create()
        with self.assertRaises(BackupError) as ctx:
            self.service.restore(manifest.backup_id, confirm=True, maintenance_boundary=False)
        self.assertIn("maintenance_boundary", str(ctx.exception))

    def test_backup002_happy_path_new_set_active(self) -> None:
        manifest = self.service.create()
        # Mutate live markers
        _seed_db(self.control, marker="control-dirty")
        _seed_db(self.knowledge, marker="knowledge-dirty", with_datasets=True)
        _seed_db(self.market, marker="market-dirty")
        restored = self.service.restore(
            manifest.backup_id, confirm=True, maintenance_boundary=True
        )
        self.assertEqual(restored.metadata.get("restoreTerminalState"), RESTORE_NEW_SET_ACTIVE)
        self.assertEqual(_marker(self.control), "control-v1")
        self.assertEqual(_marker(self.knowledge), "knowledge-v1")
        self.assertEqual(_marker(self.market), "market-v1")
        status = self.service.restore_status()
        self.assertEqual(status["state"], RESTORE_NEW_SET_ACTIVE)
        self.assertFalse(status["active"])

    def test_crash_before_cutover_leaves_old_set_active(self) -> None:
        manifest = self.service.create()
        with self.assertRaises(BackupError) as ctx:
            self.service.restore(
                manifest.backup_id,
                confirm=True,
                maintenance_boundary=True,
                inject_crash_after="before_cutover",
            )
        self.assertIn("injected_crash:before_cutover", str(ctx.exception))
        status = self.service.restore_status()
        self.assertEqual(status["state"], RESTORE_OLD_SET_ACTIVE)
        self.assertEqual(_marker(self.control), "control-v1")
        self.assertEqual(_marker(self.knowledge), "knowledge-v1")
        self.assertEqual(_marker(self.market), "market-v1")

    def test_crash_after_control_requires_recovery_and_resume(self) -> None:
        manifest = self.service.create()
        # Dirty live DBs so we can observe mixed revisions after partial cutover.
        _seed_db(self.control, marker="control-dirty")
        _seed_db(self.knowledge, marker="knowledge-dirty", with_datasets=True)
        _seed_db(self.market, marker="market-dirty")

        with self.assertRaises(BackupError):
            self.service.restore(
                manifest.backup_id,
                confirm=True,
                maintenance_boundary=True,
                inject_crash_after="after_CONTROL",
            )
        status = self.service.restore_status()
        self.assertEqual(status["state"], RESTORE_RECOVERY_REQUIRED)
        self.assertTrue(status["active"])
        # CONTROL replaced; others still dirty — mixed revisions must not look healthy.
        self.assertEqual(_marker(self.control), "control-v1")
        self.assertEqual(_marker(self.knowledge), "knowledge-dirty")
        self.assertEqual(_marker(self.market), "market-dirty")

        # Resume finishes the set.
        resumed = self.service.restore(
            manifest.backup_id, confirm=True, maintenance_boundary=True
        )
        self.assertEqual(resumed.metadata.get("restoreTerminalState"), RESTORE_NEW_SET_ACTIVE)
        self.assertTrue(resumed.metadata.get("restoreResumed"))
        self.assertEqual(_marker(self.control), "control-v1")
        self.assertEqual(_marker(self.knowledge), "knowledge-v1")
        self.assertEqual(_marker(self.market), "market-v1")
        self.assertEqual(self.service.restore_status()["state"], RESTORE_NEW_SET_ACTIVE)


if __name__ == "__main__":
    unittest.main()
