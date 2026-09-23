"""Round 5 — Evaluation platform exit gates."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.evaluation import (
    ABLATION_FEATURES,
    AssistantBenchmarkRunner,
    EvaluationHarness,
    EvaluationPlatform,
    EvaluationStore,
    TaskFamily,
    default_assistant_tasks,
    run_all_ablations,
    run_feature_ablation,
    run_paired_evaluation,
)
from Data.modules.execution import build_default_catalog


class AssistantBenchmarkTests(unittest.TestCase):
    def test_all_families_covered(self) -> None:
        tasks = default_assistant_tasks()
        families = {t.family for t in tasks}
        for family in TaskFamily:
            self.assertIn(family, families)

    def test_metrics_tracked_on_runs(self) -> None:
        runner = AssistantBenchmarkRunner(profile="leviathan")
        results = runner.run_suite()
        self.assertGreaterEqual(len(results), 10)
        for run in results:
            m = run.metrics
            self.assertTrue(m.measured)
            self.assertIsNotNone(m.latency_ms)
            self.assertIn("first_attempt_success", m.public_dict())
            self.assertIn("false_success", m.public_dict())
            self.assertIn("tool_calls", m.public_dict())
            # Most leviathan tasks should succeed against real modules.
        passed = sum(1 for r in results if r.success)
        self.assertGreaterEqual(passed, 10, [r.task_id for r in results if not r.success])


class PairedEvaluationTests(unittest.TestCase):
    def test_paired_exposes_per_task_deltas_not_single_score(self) -> None:
        report = run_paired_evaluation()
        payload = report.public_dict()
        self.assertTrue(payload["truth"]["regressions_not_hidden_in_aggregate"])
        self.assertEqual(len(report.deltas), len(report.baseline_runs))
        # Baseline should underperform on tool/retrieval families.
        self.assertGreaterEqual(report.improved_count, 1)
        # Every delta retains both sides.
        for delta in report.deltas:
            self.assertIn("first_attempt_success", delta.baseline_metrics)
            self.assertIn("first_attempt_success", delta.leviathan_metrics)


class AblationTests(unittest.TestCase):
    def test_flag_is_not_ablation_both_conditions_run(self) -> None:
        for feature in ABLATION_FEATURES:
            report = run_feature_ablation(feature)
            self.assertTrue(report.with_feature.measured)
            self.assertTrue(report.without_feature.measured)
            self.assertTrue(report.with_feature.raw_evidence)
            self.assertTrue(report.without_feature.raw_evidence)
            self.assertTrue(
                report.public_dict()["truth"]["feature_flag_is_not_ablation_result"]
            )

    def test_delegation_ablation_actually_differs(self) -> None:
        report = run_feature_ablation("delegation")
        self.assertTrue(report.with_feature.success)
        self.assertTrue(report.without_feature.success)
        # With delegation: session created; without: refused.
        self.assertNotEqual(
            report.with_feature.raw_evidence.get("obs_success"),
            report.without_feature.raw_evidence.get("obs_success"),
        )


class PlatformIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "eval.db"
        MigrationRunner(self.db).apply_all()
        self.platform = EvaluationPlatform(
            harness=EvaluationHarness(catalog=build_default_catalog()),
            store=EvaluationStore(self.db),
            enabled=True,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_platform_assistant_paired_ablations(self) -> None:
        bench = self.platform.run_assistant_benchmark(persist=True)
        self.assertGreaterEqual(bench["report"]["summary"]["passed"], 8)
        self.assertTrue(bench["truth"]["end_to_end_assistant_benchmark"])

        paired = self.platform.run_paired_evaluation(persist=True)
        self.assertIn("deltas", paired)
        self.assertTrue(paired["truth"]["regressions_not_hidden_in_aggregate"])
        self.assertIsNotNone(paired.get("persisted_report_id"))

        abl = self.platform.run_ablations(persist=True)
        self.assertEqual(len(abl["ablations"]), len(ABLATION_FEATURES))
        self.assertTrue(abl["truth"]["feature_flag_is_not_ablation_result"])
        self.assertIsNotNone(abl.get("persisted_report_id"))

        # Scorecard default suite_ids include Round 5 suites once reports exist.
        scorecard = self.platform.build_system_scorecard()
        components = {e.component for e in scorecard.entries}
        self.assertIn("assistant", components)


class ServingHonestyTests(unittest.TestCase):
    def test_unprobed_stream_cancel_is_unmeasured(self) -> None:
        from Data.modules.evaluation import EvalOutcome, EvaluationHarness, MeasurementState

        harness = EvaluationHarness()
        report = harness.run_suite(
            "serving_conformance",
            harness.serving_conformance_suite(
                managed_load_ok=False,
                stream_cancel_ok=True,
                dead_worker_honest=True,
                multi_model_route_ok=False,
                measured_route_recorded=False,
                managed_load_probed=False,
                stream_cancel_probed=False,
                dead_worker_probed=False,
                multi_route_probed=False,
                measured_route_probed=False,
            ),
            suite_id="serving_conformance",
        )
        cancel = next(r for r in report.results if r.case_id == "serving-stream-cancel")
        self.assertEqual(cancel.outcome, EvalOutcome.UNMEASURED)
        self.assertEqual(cancel.resolved_measurement(), MeasurementState.UNMEASURED)


if __name__ == "__main__":
    unittest.main()
