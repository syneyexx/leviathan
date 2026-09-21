from __future__ import annotations

import unittest

from execution_truth import tool_execution_from_invoke


class ExecutionTruthUnknownStatusHonestyTests(unittest.TestCase):
    def test_unknown_nonempty_statuses_fail_closed(self) -> None:
        for raw_status in ("timeout", "interrupted", "provider_pending", "mystery"):
            with self.subTest(status=raw_status):
                result = tool_execution_from_invoke(
                    {
                        "id": f"exec-{raw_status}",
                        "plugin_id": "audit",
                        "tool_name": "fixture",
                        "status": raw_status,
                        "exit_code": 0,
                    }
                )
                self.assertFalse(result.success)
                self.assertEqual(result.status, "failed")

    def test_known_success_status_remains_success(self) -> None:
        result = tool_execution_from_invoke(
            {
                "id": "exec-completed",
                "plugin_id": "audit",
                "tool_name": "fixture",
                "status": "completed",
                "exit_code": 0,
            }
        )
        self.assertTrue(result.success)
        self.assertEqual(result.status, "succeeded")


if __name__ == "__main__":
    unittest.main()
