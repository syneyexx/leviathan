"""W178 — backup/restore truth fields + missing corpus detection."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from Data.modules.backup import (
    BACKUP_KIND_METADATA_ONLY,
    BackupService,
)


class BackupTruthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="lev-w178-")
        root = Path(self.tmp.name)
        self.db = root / "live.db"
        self.artifacts = root / "artifacts"
        self.backups = root / "backups"
        self.corpus = root / "corpus"
        self.artifacts.mkdir()
        self.corpus.mkdir()
        (self.artifacts / "note.txt").write_text("hello", encoding="utf-8")

        # Corpus file referenced by dataset metadata
        self.dataset_file = self.corpus / "datasets" / "materialized" / "demo.jsonl"
        self.dataset_file.parent.mkdir(parents=True, exist_ok=True)
        self.dataset_file.write_text(
            '{"id":"1","text":"a","metadata":{}}\n', encoding="utf-8"
        )

        with sqlite3.connect(self.db) as conn:
            conn.execute(
                "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"
            )
            conn.execute(
                "INSERT INTO schema_migrations(version, name, applied_at) VALUES (1, 'baseline', 'now')"
            )
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

        self.service = BackupService(
            database_path=self.db,
            artifacts_root=self.artifacts,
            backup_root=self.backups,
            corpus_root=self.corpus,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_metadata_only_truth_fields(self) -> None:
        manifest = self.service.create(note="w178-db-only")
        pub = manifest.public_dict()
        self.assertEqual(pub["backupKind"], BACKUP_KIND_METADATA_ONLY)
        self.assertFalse(pub["corpusFilesIncluded"])
        self.assertFalse(pub["isCompleteDataSnapshot"])
        self.assertTrue(pub["truth"]["metadataOnlyIsNotCompleteSnapshot"])
        self.assertGreaterEqual(len(pub["corpusInventory"]), 1)
        self.assertFalse(pub["corpusInventory"][0].get("includedInBackup"))
        # Inventory should capture the sha of the live corpus file
        self.assertTrue(pub["corpusInventory"][0].get("sha256"))

    def test_missing_file_detection_after_db_only_restore(self) -> None:
        manifest = self.service.create(note="w178-missing")
        self.assertEqual(manifest.backup_kind, BACKUP_KIND_METADATA_ONLY)

        # Simulate operator deleting corpus after backup (DB-only restore cannot bring it back)
        self.dataset_file.unlink()
        self.assertFalse(self.dataset_file.exists())

        restored = self.service.restore(manifest.backup_id, confirm=True)
        pub = restored.public_dict()
        self.assertEqual(pub["backupKind"], BACKUP_KIND_METADATA_ONLY)
        self.assertFalse(pub["isCompleteDataSnapshot"])
        self.assertGreaterEqual(len(pub["missingCorpusFiles"]), 1)
        self.assertTrue(pub["truth"]["missingCorpusFileCount"] >= 1)
        reasons = {m.get("reason") for m in pub["missingCorpusFiles"]}
        self.assertTrue(
            reasons
            & {
                "missing_after_metadata_only_restore",
                "missing_at_backup_time",
            }
        )


if __name__ == "__main__":
    unittest.main()
