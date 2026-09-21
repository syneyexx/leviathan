"""Regression: Settings network_policy must persist via PATCH (UI Beveiliging flow)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from control.service import ControlService
from database import Database
from fastapi.testclient import TestClient


class FakeLmStudio:
    async def models(self):
        return {"object": "list", "data": [{"id": "local-test-model", "object": "model", "owned_by": "local"}]}

    async def chat(self, payload):
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}


class NetworkPolicyPersistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        main.database = Database(str(Path(self.temp_dir.name) / "network-policy.db"))
        main.database.initialize()
        main.control_service = ControlService(main.database, None)
        main.runner = main.TaskRunner()
        self.client_patch = patch.object(main, "lm_client", return_value=FakeLmStudio())
        self.client_patch.start()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.client_patch.stop()
        self.temp_dir.cleanup()

    def test_patch_network_policy_allow_persists_with_revision(self) -> None:
        get1 = self.client.get("/api/settings")
        self.assertEqual(get1.status_code, 200)
        body = get1.json()
        values = body["values"]
        self.assertEqual(values.get("network_policy"), "block")
        rev = int(body.get("config_revision") or values.get("config_revision") or 0)

        patched = self.client.patch(
            "/api/settings",
            json={"values": {"network_policy": "allow"}, "expected_revision": rev},
        )
        self.assertEqual(patched.status_code, 200, patched.text)
        saved = patched.json()["values"]
        self.assertEqual(saved.get("network_policy"), "allow")
        self.assertGreater(int(patched.json().get("config_revision") or 0), rev)

        get2 = self.client.get("/api/settings")
        self.assertEqual(get2.status_code, 200)
        self.assertEqual(get2.json()["values"].get("network_policy"), "allow")

    def test_patch_invalid_network_policy_returns_400(self) -> None:
        get1 = self.client.get("/api/settings")
        rev = int(get1.json().get("config_revision") or 0)
        bad = self.client.patch(
            "/api/settings",
            json={"values": {"network_policy": "wide-open"}, "expected_revision": rev},
        )
        self.assertEqual(bad.status_code, 400, bad.text)
        # Unchanged on disk
        get2 = self.client.get("/api/settings")
        self.assertEqual(get2.json()["values"].get("network_policy"), "block")


if __name__ == "__main__":
    unittest.main()
