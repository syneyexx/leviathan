from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from control.service import ControlService
from database import Database


class ControlExportSecretRedactionTests(unittest.TestCase):
    def setUp(self) -> None:
        from settings_secrets import provider_secret_store

        provider_secret_store.enable_memory_backend_for_tests()

    def tearDown(self) -> None:
        from settings_secrets import provider_secret_store

        provider_secret_store._memory_test_override = None

    def test_export_without_secrets_masks_all_core_api_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(str(Path(temp_dir) / "hades.db"))
            db.initialize()
            service = ControlService(db)
            service.patch_global(
                {
                    "lm_studio_api_key": "LM_SECRET_VALUE",
                    "tts_api_key": "TTS_SECRET_VALUE",
                    "stt_api_key": "STT_SECRET_VALUE",
                }
            )

            exported = service.export_config(include_secrets=False)
            values = exported["values"]
            self.assertEqual(values["lm_studio_api_key"], "***")
            self.assertEqual(values["tts_api_key"], "***")
            self.assertEqual(values["stt_api_key"], "***")
            rendered = repr(exported)
            self.assertNotIn("LM_SECRET_VALUE", rendered)
            self.assertNotIn("TTS_SECRET_VALUE", rendered)
            self.assertNotIn("STT_SECRET_VALUE", rendered)


if __name__ == "__main__":
    unittest.main()
