from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


class ReleaseSmokeSubprocessPolicyTests(unittest.TestCase):
    def test_release_smoke_respects_subprocess_block_before_unittest(self) -> None:
        client = TestClient(main.app)
        settings = {"subprocess_policy": "block"}
        with patch.object(main.database, "get_settings", return_value=settings), patch(
            "release_confidence.inventory_gates",
            return_value={"overall": "ok", "what_broke": []},
        ), patch(
            "release_confidence.run_focused_unittest",
            return_value={"ok": True, "exit_code": 0, "what_broke": []},
        ) as run:
            response = client.post(
                "/api/release/confidence/smoke",
                json={"run_smoke": True},
            )

        self.assertIn(response.status_code, {403, 409, 428})
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
