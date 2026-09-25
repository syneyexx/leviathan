"""F7 — Adaptive compute: expected_gain calibration + neural-axis adaptation."""

from __future__ import annotations

import unittest

from Data.modules.cognition.adaptive_compute import (
    adapt_neural_budget,
    calibrate_expected_gain,
)
from Data.modules.cognition.meta_controller import MetaController
from Data.modules.cognition.neural_compute import NativeEffort, NeuralComputeBudget
from Data.modules.cognition.task_model import TaskModelBuilder
from Data.modules.cognition.types import ReasoningMode


class ExpectedGainCalibrationTests(unittest.TestCase):
    def test_high_uncertainty_low_evidence_raises_gain(self) -> None:
        high = calibrate_expected_gain(
            uncertainty=0.9,
            evidence_coverage=0.1,
            contradiction_density=0.5,
            requires_research=True,
        )
        low = calibrate_expected_gain(
            uncertainty=0.2,
            evidence_coverage=0.9,
            contradiction_density=0.0,
            information_gain_recent=0.02,
            plan_progress=0.8,
        )
        self.assertGreater(high.total, 0.55)
        self.assertLess(low.total, 0.3)
        self.assertIn("high_expected_gain", high.notes)
        self.assertTrue(low.diminishing_returns > 0)

    def test_public_dict_marks_heuristic(self) -> None:
        gain = calibrate_expected_gain(uncertainty=0.5, evidence_coverage=0.4)
        public = gain.public_dict()
        self.assertTrue(public["truth"]["expected_gain_is_heuristic_not_bayesian"])
        self.assertTrue(public["truth"]["calibrated_for_neural_axis"])


class NeuralAxisAdaptationTests(unittest.TestCase):
    def test_escalates_candidates_on_high_gain(self) -> None:
        base = NeuralComputeBudget(
            native_effort=NativeEffort.MEDIUM,
            candidate_count=3,
            max_parallel_candidates=2,
            self_consistency_samples=3,
            diversity_temperature=0.2,
        )
        gain = calibrate_expected_gain(
            uncertainty=0.85,
            evidence_coverage=0.1,
            contradiction_density=0.5,
        )
        adapted, label, notes = adapt_neural_budget(
            base,
            gain=gain,
            resource_pressure=0.0,
            mode=ReasoningMode.DEEP,
        )
        self.assertEqual(label, "escalated")
        self.assertGreater(adapted.candidate_count, base.candidate_count)
        self.assertTrue(any("escalated" in n for n in notes))

    def test_deescalates_on_low_gain(self) -> None:
        base = NeuralComputeBudget(
            native_effort=NativeEffort.HIGH,
            candidate_count=5,
            max_parallel_candidates=3,
            self_consistency_samples=5,
            diversity_temperature=0.4,
        )
        gain = calibrate_expected_gain(
            uncertainty=0.15,
            evidence_coverage=0.9,
            contradiction_density=0.0,
            information_gain_recent=0.01,
            plan_progress=0.7,
        )
        adapted, label, _notes = adapt_neural_budget(
            base,
            gain=gain,
            resource_pressure=0.0,
            mode=ReasoningMode.DEEP,
        )
        self.assertEqual(label, "deescalated")
        self.assertLess(adapted.candidate_count, base.candidate_count)

    def test_resource_pressure_clamps_after_adapt(self) -> None:
        base = NeuralComputeBudget(
            native_effort=NativeEffort.HIGH,
            candidate_count=6,
            max_parallel_candidates=4,
        )
        gain = calibrate_expected_gain(uncertainty=0.9, evidence_coverage=0.05)
        adapted, label, _notes = adapt_neural_budget(
            base,
            gain=gain,
            resource_pressure=0.95,
            mode=ReasoningMode.MAXIMUM,
            clamp_threshold=0.8,
        )
        self.assertEqual(label, "clamped")
        self.assertEqual(adapted.max_parallel_candidates, 1)
        self.assertLessEqual(adapted.candidate_count, 4)


class MetaAdaptiveIntegrationTests(unittest.TestCase):
    def test_decision_exposes_expected_gain_and_neural_adaptation(self) -> None:
        task = TaskModelBuilder().build(
            "Deep research the latest contradictions in fusion energy claims"
        )
        ctrl = MetaController()
        decision = ctrl.decide(
            task,
            uncertainty=0.85,
            evidence_coverage=0.1,
            contradiction_density=0.45,
            information_gain_recent=0.4,
            resource_pressure=0.1,
        )
        self.assertIsNotNone(decision.expected_gain)
        self.assertIsNotNone(decision.expected_gain_detail)
        self.assertIn(decision.neural_adaptation, {"escalated", "held", "deescalated", "clamped"})
        public = decision.public_dict()
        self.assertIn("expected_gain", public)
        self.assertTrue(public["truth"]["neural_axis_adapts_on_expected_gain"])
        self.assertIn("expected_gain", decision.value_scores)
        self.assertIsNotNone(decision.neural_budgets)

    def test_low_gain_mid_run_reduces_neural_candidates(self) -> None:
        task = TaskModelBuilder().build("hello")
        ctrl = MetaController()
        first = ctrl.decide(
            task,
            uncertainty=0.8,
            evidence_coverage=0.1,
            contradiction_density=0.4,
            user_requested_depth="adaptive",
        )
        second = ctrl.decide(
            task,
            uncertainty=0.2,
            evidence_coverage=0.9,
            contradiction_density=0.05,
            information_gain_recent=0.02,
            plan_progress=0.8,
            previous_mode=first.mode,
            user_requested_depth="adaptive",
        )
        self.assertIsNotNone(first.neural_budgets)
        self.assertIsNotNone(second.neural_budgets)
        self.assertIsNotNone(first.expected_gain)
        self.assertIsNotNone(second.expected_gain)
        self.assertLessEqual(
            second.neural_budgets.candidate_count,  # type: ignore[union-attr]
            first.neural_budgets.candidate_count,  # type: ignore[union-attr]
        )
        self.assertLess(float(second.expected_gain), float(first.expected_gain))


if __name__ == "__main__":
    unittest.main()
