"""HADES-10 defaults: new installs stream + context compiler; explicit false preserved."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from database import DEFAULT_SETTINGS, Database


class Hades10DefaultsTests(unittest.TestCase):
    def test_fresh_install_defaults_streaming_and_context_compiler(self) -> None:
        self.assertIs(DEFAULT_SETTINGS["streaming"], True)
        self.assertIs(DEFAULT_SETTINGS["enable_context_compiler_chat"], True)
        self.assertIs(DEFAULT_SETTINGS["stream_provisional_text"], True)
        self.assertIs(DEFAULT_SETTINGS["memory_auto_promote"], False)
        self.assertEqual(DEFAULT_SETTINGS["language"], "nl")
        self.assertEqual(DEFAULT_SETTINGS["network_policy"], "block")
        self.assertIs(DEFAULT_SETTINGS["allow_cloud_model_fallback"], False)
        self.assertIs(DEFAULT_SETTINGS["voice_enabled"], True)
        self.assertIs(DEFAULT_SETTINGS["spoken_answers_enabled"], False)

    def test_explicit_false_is_not_overwritten_by_reseed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "hades.db"
            database = Database(str(db_path))
            database.initialize()
            database.update_settings(
                {"streaming": False, "enable_context_compiler_chat": False},
                bump_revision=True,
            )
            settings = database.get_settings()
            self.assertIs(settings["streaming"], False)
            self.assertIs(settings["enable_context_compiler_chat"], False)

            reopened = Database(str(db_path))
            reopened.initialize()
            again = reopened.get_settings()
            self.assertIs(again["streaming"], False)
            self.assertIs(again["enable_context_compiler_chat"], False)
            self.assertGreaterEqual(int(again.get("config_revision") or 0), 1)

    def test_missing_key_falls_back_to_new_default_via_get_settings_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "fresh.db"
            database = Database(str(db_path))
            database.initialize()
            self.assertIs(database.get_settings()["streaming"], True)

            with database.connection() as conn:
                conn.execute("DELETE FROM app_settings WHERE key = ?", ("streaming",))

            partial = database.get_settings()
            self.assertIs(partial["streaming"], True)

            restored = Database(str(db_path))
            restored.initialize()
            self.assertIs(restored.get_settings()["streaming"], True)


if __name__ == "__main__":
    unittest.main()
