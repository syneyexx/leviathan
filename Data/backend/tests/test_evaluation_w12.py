"""W12 — Evaluation platform: paired compute, judge calibration, suite coverage."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.evaluation import (
    EvaluationHarness,
    EvaluationPlatform,
    EvaluationStore,
    TaskFamily,
    calibrate_judge,
    default_assistant_tasks,
    judge_or_unmeasured,
    run_paired_compute_evaluation,
)
from Data.modules.evaluation.compute_paired import (
    ComputeTrial,
    analyze_paired_compute,
    build_paired_deltas,
    paired_bootstrap,
)
from Data.modules.evaluation.judge_calibration import LabeledJudgeExample
from Data.modules.execution import build_default_catalog


class PairedComputeTests(unittest.TestCase):
    def test_bootstrap_ci_and_hard_easy_criteria(self) -> None:
        report = run_paired_compute_evaluation(bootstrap_samples=200, seed=7)
        payload = report.public_dict()
        self.assertTrue(payload["truth"]["uses_paired_bootstrap_of_deltas"])
        self.assertTrue(payload["truth"]["deep_not_required_to_beat_fast_on_every_easy_task"])
        self.assertTrue(report.hard_positive_supported)
        self.assertTrue(report.easy_no_material_regression)
        self.assertEqual(report.measurement, "PASSED")
        self.assertIn("latency_summary", payload)
        self.assertIn("cost_summary", payload)
        self.assertGreater(payload["cost_summary"]["deep_mean_model_calls"], payload["cost_summary"]["fast_mean_model_calls"])

    def test_easy_regression_fails(self) -> None:
        fast = [
            ComputeTrial("e1", "FAST", True, 0.95, 20, suite="easy"),
            ComputeTrial("e2", "FAST", True, 0.95, 20, suite="easy"),
            ComputeTrial("h1", "FAST", False, 0.3, 40, suite="hard"),
            ComputeTrial("h2", "FAST", False, 0.3, 40, suite="hard"),
            ComputeTrial("h3", "FAST", False, 0.35, 40, suite="hard"),
        ]
        deep = [
            ComputeTrial("e1", "DEEP", True, 0.70, 100, suite="easy"),  # regress
            ComputeTrial("e2", "DEEP", True, 0.70, 100, suite="easy"),
            ComputeTrial("h1", "DEEP", True, 0.8, 200, suite="hard"),
            ComputeTrial("h2", "DEEP", True, 0.8, 200, suite="hard"),
            ComputeTrial("h3", "DEEP", True, 0.85, 200, suite="hard"),
        ]
        deltas = build_paired_deltas(fast, deep)
        report = analyze_paired_compute(deltas, bootstrap_samples=200)
        self.assertFalse(report.easy_no_material_regression)
        self.assertEqual(report.measurement, "FAILED")

    def test_too_few_hard_is_unmeasured(self) -> None:
        boot = paired_bootstrap([0.1], samples=50)
        self.assertEqual(boot.n, 1)
        fast = [ComputeTrial("h1", "FAST", False, 0.2, 10, suite="hard")]
        deep = [ComputeTrial("h1", "DEEP", True, 0.9, 50, suite="hard")]
        report = analyze_paired_compute(build_paired_deltas(fast, deep), bootstrap_samples=50)
        self.assertEqual(report.measurement, "UNMEASURED")


class JudgeCalibrationTests(unittest.TestCase):
    def test_below_threshold_is_unmeasured(self) -> None:
        examples = [
            LabeledJudgeExample(f"e{i}", prediction="pass", gold="fail" if i < 4 else "pass")
            for i in range(6)
        ]
        report = calibrate_judge(examples, threshold=0.8, min_examples=5)
        self.assertFalse(report.reliable)
        self.assertEqual(report.measurement, "UNMEASURED")
        result = judge_or_unmeasured(calibrated=report, judge_fn=lambda t: "pass", text="x")
        self.assertEqual(result["measurement"], "UNMEASURED")

    def test_calibrated_judge_may_run(self) -> None:
        examples = [LabeledJudgeExample(f"e{i}", prediction="ok", gold="ok") for i in range(8)]
        report = calibrate_judge(examples, threshold=0.7)
        self.assertTrue(report.reliable)
        result = judge_or_unmeasured(calibrated=report, judge_fn=lambda t: "ok", text="hi")
        self.assertEqual(result["measurement"], "MEASURED")
        self.assertEqual(result["label"], "ok")


class SuiteCoverageTests(unittest.TestCase):
    def test_w12_families_present(self) -> None:
        tasks = default_assistant_tasks()
        families = {t.family for t in tasks}
        for required in (
            TaskFamily.REASONING,
            TaskFamily.PROMPT_INJECTION,
            TaskFamily.LANGUAGE_FOLLOWING,
            TaskFamily.BROWSER,
            TaskFamily.MULTIMODAL,
            TaskFamily.TRADING_DECISIONS,
            TaskFamily.RESEARCH_GROUNDING,
        ):
            self.assertIn(required, families)

    def test_new_family_runners_succeed_honestly(self) -> None:
        from Data.modules.evaluation import AssistantBenchmarkRunner

        runner = AssistantBenchmarkRunner(profile="leviathan")
        by_id = {t.task_id: t for t in default_assistant_tasks()}
        for tid in (
            "asst-reasoning-001",
            "asst-prompt-inj-001",
            "asst-lang-follow-001",
            "asst-browser-001",
            "asst-multimodal-001",
            "asst-trading-001",
            "asst-research-ground-001",
        ):
            result = runner.run_task(by_id[tid])
            self.assertTrue(result.success, msg=f"{tid}: {result.detail}")
            self.assertTrue(result.metrics.measured)


class PlatformPairedComputeTests(unittest.TestCase):
    def test_platform_persists_compute_suite(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "e.db"
        MigrationRunner(db).apply_all()
        store = EvaluationStore(db)
        platform = EvaluationPlatform(
            harness=EvaluationHarness(catalog=build_default_catalog()),
            store=store,
            enabled=True,
        )
        payload = platform.run_paired_compute_evaluation(persist=True, bootstrap_samples=100)
        self.assertEqual(payload["measurement"], "PASSED")
        latest = platform.latest_report("paired_compute")
        self.assertIsNotNone(latest)


if __name__ == "__main__":
    unittest.main()
