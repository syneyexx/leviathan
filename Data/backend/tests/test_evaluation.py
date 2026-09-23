from __future__ import annotations

import unittest

from Data.modules.evaluation import EvalOutcome, EvaluationHarness, MeasurementState
from Data.modules.execution import build_default_catalog


class EvaluationHarnessTests(unittest.TestCase):
    def test_foundation_suite_unmeasured_not_passed(self) -> None:
        harness = EvaluationHarness(catalog=build_default_catalog())
        report = harness.run_suite("foundation", harness.default_foundation_suite())
        self.assertEqual(report.summary["passed"], 0)
        self.assertGreaterEqual(report.summary["unmeasured"], 3)
        self.assertEqual(report.summary["passed"] + report.summary["unmeasured"] + report.summary["failed"] + report.summary["error"], report.summary["total"])
        embedding = next(r for r in report.results if r.case_id == "embedding-quality")
        self.assertEqual(embedding.outcome, EvalOutcome.UNMEASURED)
        self.assertEqual(embedding.resolved_measurement(), MeasurementState.UNMEASURED)
        # Registration presence must not appear as operational PASS.
        for case_id in ("cap-file-read", "cap-knowledge"):
            row = next((r for r in report.results if r.case_id == case_id), None)
            if row is not None:
                self.assertEqual(row.outcome, EvalOutcome.UNMEASURED)
        self.assertTrue(report.public_dict()["truth"]["unmeasured_is_not_passed"])
        self.assertNotEqual(embedding.resolved_measurement(), MeasurementState.PASS)


if __name__ == "__main__":
    unittest.main()
