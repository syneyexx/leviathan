from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from control.routes import router as control_router
from control.service import ControlService
from database import Database


class ControlApiSecretRedactionTests(unittest.TestCase):
    def setUp(self) -> None:
        from settings_secrets import provider_secret_store

        provider_secret_store.enable_memory_backend_for_tests()

    def tearDown(self) -> None:
        from settings_secrets import provider_secret_store

        provider_secret_store._memory_test_override = None

    def test_public_control_values_and_history_do_not_return_secret_values(self) -> None:
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

            app = FastAPI()
            app.include_router(control_router)
            with patch("control.routes.get_control_service", return_value=service):
                client = TestClient(app)
                values_response = client.get("/api/control/values")
                history_response = client.get("/api/control/history")

            self.assertEqual(values_response.status_code, 200)
            self.assertEqual(history_response.status_code, 200)
            values = values_response.json()["values"]
            self.assertEqual(values["lm_studio_api_key"], "***")
            self.assertEqual(values["tts_api_key"], "***")
            self.assertEqual(values["stt_api_key"], "***")

            rendered = values_response.text + history_response.text
            self.assertNotIn("LM_API_SECRET_FIXTURE", rendered)
            self.assertNotIn("TTS_API_SECRET_FIXTURE", rendered)
            self.assertNotIn("STT_API_SECRET_FIXTURE", rendered)


if __name__ == "__main__":
    unittest.main()
