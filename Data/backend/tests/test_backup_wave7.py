"""WAVE 7 + WAVE 21 — journaled three-DB restore, coordinator maintenance proof, startup gate."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from Data.modules.backup import (
    MAINT_NORMAL,
    MAINT_QUIESCED,
    MAINT_RECOVERY_REQUIRED,
    RESTORE_NEW_SET_ACTIVE,
    RESTORE_OLD_SET_ACTIVE,
    RESTORE_RECOVERY_REQUIRED,
    BackupError,
    BackupService,
    MaintenanceCoordinator,
    RestoreStartupBlocked,
    assert_startup_allows_canonical_db_use,
    assert_writes_allowed,
    journal_blocks_normal_startup,
    register_process_coordinator,
)


def _seed_db(path: Path, *, marker: str, with_datasets: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        path.unlink()
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
        self.coordinator = MaintenanceCoordinator(
            backup_root=self.backups,
            quiesce_timeout_seconds=2.0,
        )
        register_process_coordinator(self.coordinator)
        self.service = BackupService(
            database_path=self.control,
            artifacts_root=self.artifacts,
            backup_root=self.backups,
            corpus_root=self.corpus,
            database_paths=self.paths,
            maintenance=self.coordinator,
        )

    def tearDown(self) -> None:
        register_process_coordinator(None)
        self.tmp.cleanup()

    def _proof(self):
        return self.coordinator.enter_for_restore(reason="test")

    def test_backup001_corpus_inventory_reads_knowledge_not_control(self) -> None:
        # CONTROL has no dataset tables — if inventory wrongly used CONTROL, empty.
        manifest = self.service.create(note="w7-inventory")
        pub = manifest.public_dict()
        self.assertEqual(pub["truth"]["corpusInventorySourceDomain"], "KNOWLEDGE")
        self.assertEqual(manifest.metadata.get("corpusInventorySourceDomain"), "KNOWLEDGE")
        self.assertGreaterEqual(len(pub["corpusInventory"]), 1)
        paths = {e.get("absolutePath") for e in pub["corpusInventory"]}
        self.assertIn(str(self.dataset_file), paths)

    def test_backup003_refuses_without_maintenance_proof(self) -> None:
        manifest = self.service.create()
        with self.assertRaises(BackupError) as ctx:
            self.service.restore(manifest.backup_id, confirm=True)
        self.assertIn("maintenance_proof", str(ctx.exception))

    def test_backup003_refuses_caller_boolean_as_proof(self) -> None:
        """WAVE 21 — maintenance_boundary=True is not quiescence proof."""
        manifest = self.service.create()
        with self.assertRaises(BackupError) as ctx:
            self.service.restore(
                manifest.backup_id, confirm=True, maintenance_boundary=True
            )
        self.assertIn("not proof", str(ctx.exception).lower())
        # Live markers unchanged — fail closed before file replace.
        self.assertEqual(_marker(self.control), "control-v1")

    def test_backup002_happy_path_new_set_active(self) -> None:
        manifest = self.service.create()
        # Mutate live markers
        _seed_db(self.control, marker="control-dirty")
        _seed_db(self.knowledge, marker="knowledge-dirty", with_datasets=True)
        _seed_db(self.market, marker="market-dirty")
        proof = self._proof()
        self.assertEqual(proof.state, MAINT_QUIESCED)
        restored = self.service.restore(
            manifest.backup_id, confirm=True, maintenance_proof=proof
        )
        self.assertEqual(restored.metadata.get("restoreTerminalState"), RESTORE_NEW_SET_ACTIVE)
        self.assertTrue(restored.metadata.get("maintenanceProofVerified"))
        self.assertEqual(_marker(self.control), "control-v1")
        self.assertEqual(_marker(self.knowledge), "knowledge-v1")
        self.assertEqual(_marker(self.market), "market-v1")
        status = self.service.restore_status()
        self.assertEqual(status["state"], RESTORE_NEW_SET_ACTIVE)
        self.assertFalse(status["active"])
        self.assertEqual(self.coordinator.state, MAINT_NORMAL)

    def test_crash_before_cutover_leaves_old_set_active(self) -> None:
        manifest = self.service.create()
        with self.assertRaises(BackupError) as ctx:
            self.service.restore(
                manifest.backup_id,
                confirm=True,
                maintenance_proof=self._proof(),
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
                maintenance_proof=self._proof(),
                inject_crash_after="after_CONTROL",
            )
        status = self.service.restore_status()
        self.assertEqual(status["state"], RESTORE_RECOVERY_REQUIRED)
        self.assertTrue(status["active"])
        self.assertEqual(self.coordinator.state, MAINT_RECOVERY_REQUIRED)
        # CONTROL replaced; others still dirty — mixed revisions must not look healthy.
        self.assertEqual(_marker(self.control), "control-v1")
        self.assertEqual(_marker(self.knowledge), "knowledge-dirty")
        self.assertEqual(_marker(self.market), "market-dirty")

        # Startup gate must block normal canonical DB use.
        with self.assertRaises(RestoreStartupBlocked):
            assert_startup_allows_canonical_db_use(self.backups)
        blocked, reason = journal_blocks_normal_startup(status.get("journal"))
        self.assertTrue(blocked)
        self.assertIn("RECOVERY_REQUIRED", reason)

        # Writes rejected while recovery fence held.
        with self.assertRaises(Exception) as wctx:
            assert_writes_allowed(op="test_write")
        self.assertIn("maintenance", str(wctx.exception).lower())

        # Resume finishes the set (coordinator re-enters from RECOVERY_REQUIRED).
        resumed = self.service.restore(
            manifest.backup_id, confirm=True, maintenance_proof=self._proof()
        )
        self.assertEqual(resumed.metadata.get("restoreTerminalState"), RESTORE_NEW_SET_ACTIVE)
        self.assertTrue(resumed.metadata.get("restoreResumed"))
        self.assertEqual(_marker(self.control), "control-v1")
        self.assertEqual(_marker(self.knowledge), "knowledge-v1")
        self.assertEqual(_marker(self.market), "market-v1")
        self.assertEqual(self.service.restore_status()["state"], RESTORE_NEW_SET_ACTIVE)
        # After successful resume, startup gate clears.
        assert_startup_allows_canonical_db_use(self.backups)

    def test_wave21_writes_rejected_during_maintenance(self) -> None:
        proof = self._proof()
        self.assertFalse(self.coordinator.writes_allowed())
        with self.assertRaises(Exception) as ctx:
            assert_writes_allowed(op="enqueue")
        self.assertIn("writes rejected", str(ctx.exception).lower())
        # Prove token is real and state is QUIESCED.
        verified = self.coordinator.verify_proof(proof)
        self.assertEqual(verified.proof_id, proof.proof_id)
        self.coordinator.mark_old_set_active()
        self.coordinator.exit_to_normal()
        assert_writes_allowed(op="enqueue")

    def test_wave21_quiesce_timeout_fail_closed_no_db_replace(self) -> None:
        class BusyRuntime:
            def enter_maintenance_fence(self) -> None:
                return None

            def clear_maintenance_fence(self) -> None:
                return None

            def maintenance_busy(self) -> bool:
                return True

            def list(self, **_kwargs):  # noqa: ANN003
                return ["busy"]

        busy = BusyRuntime()
        coord = MaintenanceCoordinator(
            backup_root=self.backups / "busy",
            job_runtime=busy,
            quiesce_timeout_seconds=0.15,
            drain_poll_seconds=0.02,
        )
        manifest = self.service.create()
        control_before = self.control.read_bytes()
        with self.assertRaises(Exception) as ctx:
            coord.enter_for_restore(timeout_seconds=0.15)
        self.assertIn("timed out", str(ctx.exception).lower())
        # Must not have replaced live DB files.
        self.assertEqual(self.control.read_bytes(), control_before)
        with self.assertRaises(BackupError):
            self.service.restore(
                manifest.backup_id, confirm=True, maintenance_proof=None
            )


if __name__ == "__main__":
    unittest.main()
