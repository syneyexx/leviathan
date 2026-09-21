from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.backup import BackupError, BackupService


class BackupServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "live.db"
        self.artifacts = root / "artifacts"
        self.backups = root / "backups"
        self.artifacts.mkdir()
        (self.artifacts / "note.txt").write_text("hello", encoding="utf-8")
        # Minimal sqlite file
        import sqlite3

        with sqlite3.connect(self.db) as conn:
            conn.execute(
                "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"
            )
            conn.execute(
                "INSERT INTO schema_migrations(version, name, applied_at) VALUES (1, 'baseline', 'now')"
            )
        self.service = BackupService(
            database_path=self.db,
            artifacts_root=self.artifacts,
            backup_root=self.backups,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_create_list_and_restore_requires_confirm(self) -> None:
        manifest = self.service.create(note="phase39")
        self.assertTrue(manifest.backup_id.startswith("backup-"))
        self.assertEqual(manifest.artifacts_copied, 1)
        listed = self.service.list()
        self.assertEqual(len(listed), 1)
        with self.assertRaises(BackupError):
            self.service.restore(manifest.backup_id, confirm=False)
        # Mutate live DB then restore
        self.db.write_bytes(b"corrupted")
        restored = self.service.restore(manifest.backup_id, confirm=True)
        self.assertEqual(restored.backup_id, manifest.backup_id)
        self.assertGreater(self.db.stat().st_size, 10)


if __name__ == "__main__":
    unittest.main()
