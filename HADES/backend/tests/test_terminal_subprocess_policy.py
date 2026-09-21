from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


class TerminalSubprocessPolicyTests(unittest.TestCase):
    def test_terminal_run_respects_subprocess_block_before_execution(self) -> None:
        client = TestClient(main.app)
        settings = {
            "file_write_policy": "allow",
            "subprocess_policy": "block",
        }
        with patch.object(main.database, "get_settings", return_value=settings), patch(
            "terminal_tool.run_isolated",
            side_effect=AssertionError("execution must not be reached under subprocess block"),
        ) as run:
            response = client.post(
                "/api/terminal/run",
                json={"argv": ["python", "--version"], "approved": True},
            )

        self.assertEqual(response.status_code, 403)
        run.assert_not_called()

    def test_terminal_run_requires_distinct_subprocess_approval_when_policy_is_ask(self) -> None:
        """Open remainder: file-write approval must not silently stand in for subprocess approval."""
        client = TestClient(main.app)
        settings = {
            "file_write_policy": "allow",
            "subprocess_policy": "ask",
        }
        with patch.object(main.database, "get_settings", return_value=settings), patch(
            "terminal_tool.run_isolated",
            side_effect=AssertionError("execution reached before subprocess ask approval"),
        ) as run:
            response = client.post(
                "/api/terminal/run",
                json={"argv": ["python", "--version"], "approved": True},
            )

        self.assertEqual(response.status_code, 409)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
