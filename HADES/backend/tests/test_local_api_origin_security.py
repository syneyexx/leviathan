from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import main
from database import Database


class _FakeLmStudio:
    async def models(self):
        return {"object": "list", "data": []}


class LocalApiOriginSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp_dir.name)
        main.database = Database(str(self.root / "api-security.db"))
        main.runner = main.TaskRunner()
        self.client_patch = patch.object(main, "lm_client", return_value=_FakeLmStudio())
        self.client_patch.start()
        # Avoid full lifecycle (plugin reconcile / native) hanging in CI sandboxes.
        self.life_start = patch.object(main, "lifecycle_startup", new_callable=AsyncMock)
        self.life_stop = patch.object(main, "lifecycle_shutdown", new_callable=AsyncMock)
        self.life_start.start()
        self.life_stop.start()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.life_start.stop()
        self.life_stop.stop()
        self.client_patch.stop()
        self.temp_dir.cleanup()

    def test_hostile_origin_cannot_trigger_simple_mutating_post(self) -> None:
        response = self.client.post(
            "/api/settings/backup",
            headers={"Origin": "https://attacker.invalid"},
        )
        self.assertIn(response.status_code, {400, 403})

    def test_untrusted_host_cannot_reach_local_mutating_api(self) -> None:
        response = self.client.post(
            "/api/settings/backup",
            headers={"Host": "attacker.invalid"},
        )
        self.assertIn(response.status_code, {400, 403})


if __name__ == "__main__":
    unittest.main()
