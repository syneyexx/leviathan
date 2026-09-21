"""Lightweight architecture tests for error taxonomy + correlation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from errors import ErrorCode, HadesError, ensure_correlation, from_native_error, get_correlation, normalize_error_code


class ErrorTaxonomyTests(unittest.TestCase):
    def test_native_aliases(self) -> None:
        self.assertEqual(normalize_error_code("QUEUE_FULL"), ErrorCode.QUEUE_FULL)
        self.assertEqual(normalize_error_code("INVALID_PARAMS"), ErrorCode.VALIDATION_ERROR)
        err = from_native_error("DEADLINE_EXCEEDED", "too late")
        self.assertTrue(err.retryable)
        self.assertEqual(err.http_status(), 504)

    def test_user_facing_flags(self) -> None:
        denied = HadesError(ErrorCode.POLICY_DENIED, "blocked")
        body = denied.as_dict()
        self.assertTrue(body["permission_required"])
        self.assertTrue(body["user_action_required"])
        self.assertFalse(body["retryable"])

    def test_correlation_context(self) -> None:
        ctx = ensure_correlation(run_id="run-1", task_id="task-9")
        self.assertEqual(ctx.run_id, "run-1")
        self.assertEqual(get_correlation().task_id, "task-9")
        child = ctx.child(native_job_id="job-3")
        self.assertEqual(child.trace_id, ctx.trace_id)
        self.assertEqual(child.native_job_id, "job-3")


if __name__ == "__main__":
    unittest.main()
