from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import main


class PreviewSubprocessPolicyTests(unittest.TestCase):
    def test_preview_start_respects_subprocess_block_before_manager_start(self) -> None:
        client = TestClient(main.app)
        manager = MagicMock()
        manager.start_preview.return_value = {"started": True, "healthy": False, "pid": 12345}
        settings = {"subprocess_policy": "block", "file_write_policy": "allow"}

        with patch.object(main.database, "get_settings", return_value=settings), patch(
            "preview_runtime.get_preview_manager",
            return_value=manager,
        ):
            response = client.post(
                "/api/preview/start",
                json={"path": ".", "run_id": "policy-test", "kind": "npm"},
            )

        self.assertIn(response.status_code, {403, 409, 428})
        manager.start_preview.assert_not_called()


if __name__ == "__main__":
    unittest.main()
