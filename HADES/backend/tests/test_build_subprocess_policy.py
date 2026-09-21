from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import main


class BuildSubprocessPolicyTests(unittest.TestCase):
    def test_sync_build_goal_respects_subprocess_block_before_execution(self) -> None:
        client = TestClient(main.app)
        settings = {
            "file_write_policy": "allow",
            "subprocess_policy": "block",
        }
        with patch.object(main.database, "get_settings", return_value=settings), patch(
            "coding_agent.CodingAgentService.run_from_goal",
            return_value={"status": "verified"},
        ) as run:
            response = client.post(
                "/api/build/goal",
                json={"source_repo": ".", "goal": "noop audit goal"},
            )

        self.assertIn(response.status_code, {403, 409, 428})
        run.assert_not_called()

    def test_async_build_goal_respects_subprocess_block_before_dispatch(self) -> None:
        client = TestClient(main.app)
        settings = {
            "file_write_policy": "allow",
            "subprocess_policy": "block",
        }
        store = MagicMock()
        store.recover_stale.return_value = {"ok": True}
        store.start.return_value = {"id": "job_audit", "status": "queued", "created_at": 0}
        with patch.object(main.database, "get_settings", return_value=settings), patch(
            "coding_jobs.get_coding_job_store",
            return_value=store,
        ):
            response = client.post(
                "/api/build/goal/async",
                json={"source_repo": ".", "goal": "noop audit goal"},
            )

        self.assertIn(response.status_code, {403, 409, 428})
        store.start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
