from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from workspace_backup import WorkspaceBackupService


class WorkspaceBackupSecretRedactionSafetyTests(unittest.TestCase):
    def test_secret_redaction_error_must_fail_closed(self) -> None:
        """Redaction transaction failures must not yield secret-excluded archive bytes."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "hades.db"
            with sqlite3.connect(db_path) as db:
                db.executescript(
                    """
                    CREATE TABLE app_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    INSERT INTO app_settings(key, value, updated_at)
                    VALUES('lm_studio_api_key', 'fixture-redact-me', '2026-01-01T00:00:00Z');
                    CREATE TRIGGER block_settings_update
                    BEFORE UPDATE ON app_settings
                    BEGIN
                        SELECT RAISE(ABORT, 'fixture update blocked');
                    END;
                    """
                )

            service = WorkspaceBackupService(root, db_path=db_path)
            with self.assertRaises(sqlite3.Error):
                service._sqlite_backup_bytes(db_path, redact_secrets=True)


if __name__ == "__main__":
    unittest.main()
