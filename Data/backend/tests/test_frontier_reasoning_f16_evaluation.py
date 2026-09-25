"""F16 — Frontier reasoning evaluation suite + ablations (R24)."""

from __future__ import annotations

import unittest

from Data.modules.evaluation import (
    FRONTIER_ABLATION_FEATURES,
    EvalOutcome,
    EvaluationHarness,
    EvaluationPlatform,
    MeasurementState,
    run_all_frontier_ablations,
    run_frontier_feature_ablation,
    run_frontier_reasoning_suite,
)


class FrontierReasoningSuiteTests(unittest.TestCase):
    def test_suite_all_probes_pass(self) -> None:
        report = run_frontier_reasoning_suite()
        self.assertEqual(report.suite_id, "frontier_reasoning")
        self.assertGreaterEqual(report.summary["total"], 8)
        self.assertEqual(report.summary["failed"], 0)
        self.assertEqual(report.summary["error"], 0)
        self.assertEqual(report.summary["passed"], report.summary["total"])
        for result in report.results:
            self.assertEqual(result.outcome, EvalOutcome.PASSED)
            self.assertEqual(result.resolved_measurement(), MeasurementState.PASS)

    def test_harness_frontier_probe_check(self) -> None:
        harness = EvaluationHarness()
        report = harness.run_suite(
            "frontier_reasoning",
            harness.frontier_reasoning_suite(),
            suite_id="frontier_reasoning",
        )
        self.assertEqual(report.summary["passed"], report.summary["total"])
        self.assertTrue(report.system_level)


class FrontierAblationTests(unittest.TestCase):
    def test_feature_catalog(self) -> None:
        self.assertIn("belief", FRONTIER_ABLATION_FEATURES)
        self.assertIn("experience_learning", FRONTIER_ABLATION_FEATURES)
        self.assertIn("trajectory_export", FRONTIER_ABLATION_FEATURES)
        self.assertIn("candidate_lifecycle", FRONTIER_ABLATION_FEATURES)

    def test_paired_with_without_measured(self) -> None:
        for feature in FRONTIER_ABLATION_FEATURES:
            report = run_frontier_feature_ablation(feature)
            self.assertEqual(report.feature, feature)
            self.assertTrue(report.with_feature.measured)
            self.assertTrue(report.without_feature.measured)
            self.assertTrue(report.with_feature.success)
            self.assertTrue(report.without_feature.success)
            self.assertTrue(
                report.public_dict()["truth"]["feature_flag_is_not_ablation_result"]
            )
            self.assertTrue(report.public_dict()["truth"]["paired_with_without_required"])

    def test_run_all_frontier_ablations(self) -> None:
        reports = run_all_frontier_ablations()
        self.assertEqual(len(reports), len(FRONTIER_ABLATION_FEATURES))


class PlatformFrontierWireTests(unittest.TestCase):
    def test_named_suite_frontier_reasoning(self) -> None:
        from Data.modules.evaluation.store import EvaluationStore
        import tempfile
        from pathlib import Path

        tmp = tempfile.TemporaryDirectory()
        try:
            store = EvaluationStore(Path(tmp.name) / "e.db")
            store.initialize()
            platform = EvaluationPlatform(
                harness=EvaluationHarness(), store=store, enabled=True
            )
            out = platform.run_named_suite("frontier_reasoning", persist=True)
            self.assertEqual(out["suite_id"], "frontier_reasoning")
            self.assertEqual(out["measurement"], MeasurementState.PASS.value)
            abl = platform.run_named_suite("frontier_ablation", persist=True)
            self.assertEqual(abl["suite_id"], "frontier_ablation")
            self.assertIn("ablations", abl)
            self.assertTrue(abl["truth"]["frontier_reasoning_ablations"])
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
