from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from workspace_backup import WorkspaceBackupService


class WorkspaceBackupSecretHistoryTests(unittest.TestCase):
    def test_redacted_database_copy_masks_current_override_and_history_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "hades.db"
            conn = sqlite3.connect(str(db_path))
            try:
                conn.executescript(
                    """
                    CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE setting_overrides (
                        id TEXT PRIMARY KEY,
                        key TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        scope_id TEXT,
                        value TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE setting_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        key TEXT NOT NULL,
                        old_value TEXT,
                        new_value TEXT,
                        scope TEXT NOT NULL,
                        scope_id TEXT,
                        actor TEXT,
                        timestamp TEXT NOT NULL
                    );
                    """
                )
                conn.execute(
                    "INSERT INTO app_settings(key,value) VALUES(?,?)",
                    ("lm_studio_api_key", "CURRENT_SECRET_VALUE"),
                )
                conn.execute(
                    "INSERT INTO setting_overrides(id,key,scope,scope_id,value,updated_at) VALUES(?,?,?,?,?,?)",
                    ("ovr_1", "lm_studio_api_key", "project", "proj_1", '"OVERRIDE_SECRET_VALUE"', "2026-09-13T00:00:00+00:00"),
                )
                conn.execute(
                    "INSERT INTO setting_history(key,old_value,new_value,scope,scope_id,actor,timestamp) VALUES(?,?,?,?,?,?,?)",
                    (
                        "lm_studio_api_key",
                        '"OLD_SECRET_VALUE"',
                        '"NEW_SECRET_VALUE"',
                        "project",
                        "proj_1",
                        "user",
                        "2026-09-13T00:00:00+00:00",
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            service = WorkspaceBackupService(root, db_path=db_path)
            redacted_bytes = service._sqlite_backup_bytes(db_path, redact_secrets=True)
            copied = root / "redacted.db"
            copied.write_bytes(redacted_bytes)

            check = sqlite3.connect(str(copied))
            try:
                current = check.execute(
                    "SELECT value FROM app_settings WHERE key=?",
                    ("lm_studio_api_key",),
                ).fetchone()[0]
                override = check.execute(
                    "SELECT value FROM setting_overrides WHERE key=?",
                    ("lm_studio_api_key",),
                ).fetchone()[0]
                history = check.execute(
                    "SELECT old_value,new_value FROM setting_history WHERE key=?",
                    ("lm_studio_api_key",),
                ).fetchone()
            finally:
                check.close()

            self.assertEqual(current, "***")
            self.assertNotIn("OVERRIDE_SECRET_VALUE", override)
            self.assertNotIn("OLD_SECRET_VALUE", history[0] or "")
            self.assertNotIn("NEW_SECRET_VALUE", history[1] or "")


if __name__ == "__main__":
    unittest.main()
