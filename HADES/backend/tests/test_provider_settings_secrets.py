from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from control.service import ControlService
from database import Database
from settings_secrets import (
    KEYRING_SENTINEL,
    SECRET_MASK,
    migrate_provider_settings_secrets,
    provider_secret_store,
    resolve_settings_secrets,
)


class ProviderSettingsSecretMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        provider_secret_store.enable_memory_backend_for_tests()

    def tearDown(self) -> None:
        provider_secret_store._memory_test_override = None

    def test_migration_moves_plaintext_out_of_sqlite_and_keeps_runtime_usable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "hades.db"
            database = Database(str(db_path))
            database.initialize()
            secret = "LM-PLAINTEXT-MIGRATION-SECRET"
            database.update_settings({"lm_studio_api_key": secret, "language": "nl"})

            result = migrate_provider_settings_secrets(database)
            self.assertTrue(result["ok"])
            self.assertIn("lm_studio_api_key", result["migrated_keys"])

            with database.connection() as conn:
                row = conn.execute(
                    "SELECT value FROM app_settings WHERE key=?",
                    ("lm_studio_api_key",),
                ).fetchone()
                stored = json.loads(row["value"])
                self.assertEqual(stored, KEYRING_SENTINEL)
                self.assertNotIn(secret, conn.execute("SELECT value FROM app_settings").fetchall())

            resolved = resolve_settings_secrets(database.get_settings())
            self.assertEqual(resolved["lm_studio_api_key"], secret)

    def test_migration_does_not_drop_secrets_when_keyring_unavailable(self) -> None:
        provider_secret_store._memory_test_override = None
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "hades.db"
            database = Database(str(db_path))
            database.initialize()
            secret = "KEEP-IN-SQLITE-IF-NO-KEYRING"
            database.update_settings({"tts_api_key": secret})

            with mock.patch.object(provider_secret_store, "available", return_value={"ok": False, "error": "no keyring"}):
                result = migrate_provider_settings_secrets(database)

            self.assertFalse(result["ok"])
            with database.connection() as conn:
                raw = json.loads(
                    conn.execute("SELECT value FROM app_settings WHERE key=?", ("tts_api_key",)).fetchone()["value"]
                )
            self.assertEqual(raw, secret)

    def test_control_api_masks_values_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(str(Path(temp_dir) / "hades.db"))
            db.initialize()
            service = ControlService(db)
            service.patch_global(
                {
                    "lm_studio_api_key": "LM_API_SECRET_FIXTURE",
                    "tts_api_key": "TTS_API_SECRET_FIXTURE",
                    "stt_api_key": "STT_API_SECRET_FIXTURE",
                },
                actor="secret-redaction-test",
            )

            public_values = service.global_values()
            self.assertEqual(public_values["lm_studio_api_key"], SECRET_MASK)
            history = service.history(limit=10)
            rendered = repr(public_values) + repr(history)
            self.assertNotIn("LM_API_SECRET_FIXTURE", rendered)
            self.assertNotIn("TTS_API_SECRET_FIXTURE", rendered)

            runtime = service.runtime_values()
            self.assertEqual(runtime["lm_studio_api_key"], "LM_API_SECRET_FIXTURE")


if __name__ == "__main__":
    unittest.main()
