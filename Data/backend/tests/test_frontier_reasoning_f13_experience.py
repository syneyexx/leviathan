"""F13 — ExperienceStore v2 aggregates + active-learning triggers (R20/R21)."""

from __future__ import annotations

import unittest

from Data.modules.cognition.experience import (
    ACTIVE_LEARNING_TRIGGERS,
    ExperienceStore,
    evaluate_active_learning_triggers,
    wilson_interval,
)
from Data.modules.cognition.hypotheses import HypothesisBoard, HypothesisStatus
from Data.modules.cognition.meta_controller import MetaDecision
from Data.modules.cognition.neural_compute import NativeEffort, NeuralComputeBudget
from Data.modules.cognition.runtime import CognitiveRuntime
from Data.modules.cognition.task_model import TaskModelBuilder
from Data.modules.cognition.types import (
    CognitiveBudgets,
    CognitiveRunStatus,
    ReasoningMode,
    ReasoningStrategy,
)


class WilsonIntervalTests(unittest.TestCase):
    def test_zero_n_returns_none(self) -> None:
        self.assertIsNone(wilson_interval(0, 0))

    def test_interval_bounds(self) -> None:
        low, high = wilson_interval(8, 10)
        self.assertGreaterEqual(low, 0.0)
        self.assertLessEqual(high, 1.0)
        self.assertLessEqual(low, high)
        self.assertGreater(low, 0.4)


class ExperienceV2AggregateTests(unittest.TestCase):
    def test_bucket_n_and_ci_by_domain_mode_strategy(self) -> None:
        store = ExperienceStore()
        task = TaskModelBuilder().build("Fix reconnect race with tests")
        for status, verif in (
            (CognitiveRunStatus.COMPLETED_VERIFIED, "PASSED"),
            (CognitiveRunStatus.COMPLETED_VERIFIED, "PASSED"),
            (CognitiveRunStatus.COMPLETED_UNVERIFIED, "UNMEASURED"),
            (CognitiveRunStatus.FAILED, "FAILED"),
        ):
            exp = store.build_from_run(
                task=task,
                status=status,
                strategy=ReasoningStrategy.CODING_REPAIR,
                action_summaries=["RETRIEVE", "VERIFY"],
                verification_status=verif,
                mode="DEEP",
                neural_effort="HIGH",
                expected_gain=0.62,
            )
            store.admit(exp)

        agg = store.public_aggregates(domain=task.domain)
        self.assertEqual(agg["schema_version"], "2")
        self.assertEqual(agg["total_n"], 4)
        self.assertEqual(agg["total_successes"], 2)
        self.assertEqual(agg["total_verified_successes"], 2)
        self.assertIsNotNone(agg["overall_wilson_ci_95"])
        self.assertTrue(agg["truth"]["n_and_ci_required"])
        self.assertTrue(agg["truth"]["unverified_is_not_training_truth"])
        self.assertTrue(agg["truth"]["auto_promote_forbidden"])

        buckets = agg["buckets"]
        self.assertEqual(len(buckets), 1)
        b = buckets[0]
        self.assertEqual(b["n"], 4)
        self.assertEqual(b["mode"], "DEEP")
        self.assertEqual(b["strategy"], ReasoningStrategy.CODING_REPAIR.value)
        self.assertEqual(b["verified_successes"], 2)
        self.assertIsNotNone(b["wilson_ci_95"])
        self.assertTrue(b["truth"]["unverified_is_not_counted_as_verified_success"])

        hints = store.procedural_hints(domain=task.domain)
        self.assertEqual(len(hints), 1)
        hint_pub = hints[0].public_dict()
        self.assertEqual(hint_pub["attempts"], 2)  # only admitted verified
        self.assertEqual(hint_pub["successes"], 2)
        self.assertIsNotNone(hint_pub["wilson_ci_95"])
        self.assertTrue(hint_pub["truth"]["n_statistics_required"])

    def test_public_dict_carries_v2_axes(self) -> None:
        store = ExperienceStore()
        task = TaskModelBuilder().build("summarize tides")
        exp = store.build_from_run(
            task=task,
            status=CognitiveRunStatus.COMPLETED_VERIFIED,
            strategy=ReasoningStrategy.DIRECT,
            action_summaries=["RESPOND"],
            verification_status="PASSED",
            mode="STANDARD",
            neural_effort="MEDIUM",
            expected_gain=0.4,
        )
        pub = store.admit(exp).public_dict()
        self.assertEqual(pub["schema_version"], "2")
        self.assertEqual(pub["mode"], "STANDARD")
        self.assertEqual(pub["neural_effort"], "MEDIUM")
        self.assertEqual(pub["expected_gain"], 0.4)
        self.assertTrue(pub["truth"]["experience_v2_aggregates"])


class ActiveLearningTriggerTests(unittest.TestCase):
    def test_trigger_catalog_covers_required_reasons(self) -> None:
        required = {
            "verification_failed",
            "high_uncertainty",
            "run_failed",
            "contradiction_dense",
            "low_evidence_research",
            "budget_exhausted",
            "partial_completion",
            "repeated_critic_replan",
            "user_correction",
            "capability_blocked",
            "unresolved_hypotheses",
            "timeout",
        }
        self.assertTrue(required.issubset(ACTIVE_LEARNING_TRIGGERS))

    def test_evaluate_fires_multiple_triggers(self) -> None:
        triggers = evaluate_active_learning_triggers(
            {
                "uncertainty": 0.9,
                "verification_passed": False,
                "status": CognitiveRunStatus.PARTIAL.value,
                "contradiction_density": 0.5,
                "evidence_coverage": 0.1,
                "requires_research": True,
                "budget_exhausted": True,
                "critic_replan_count": 3,
                "user_correction_count": 1,
                "capability_block_count": 2,
                "open_unresolved_hypothesis_count": 3,
                "timed_out": False,
            }
        )
        reasons = {t["reason"] for t in triggers}
        for expected in (
            "verification_failed",
            "high_uncertainty",
            "contradiction_dense",
            "low_evidence_research",
            "budget_exhausted",
            "partial_completion",
            "repeated_critic_replan",
            "user_correction",
            "capability_blocked",
            "unresolved_hypotheses",
        ):
            self.assertIn(expected, reasons)
        self.assertTrue(all(t["auto_promote_forbidden"] for t in triggers))
        self.assertTrue(all(t["requires_human_or_policy_approval"] for t in triggers))

    def test_capture_never_auto_trains(self) -> None:
        store = ExperienceStore()
        captured = store.capture_active_learning_from_context(
            {
                "uncertainty": 0.8,
                "verification_passed": False,
                "status": CognitiveRunStatus.FAILED.value,
            },
            run_id="r-al",
            domain="coding",
            goal="broken verify",
        )
        self.assertGreaterEqual(len(captured), 2)
        self.assertTrue(all(c["auto_promote_forbidden"] for c in captured))
        self.assertTrue(all(c["requires_human_or_policy_approval"] for c in captured))
        self.assertTrue(all(c["truth"]["active_learning_never_auto_trains"] for c in captured))
        for c in store.training_candidates():
            self.assertTrue(c["auto_promote_forbidden"])


class RuntimeExperienceV2WireTests(unittest.TestCase):
    def test_finalize_records_mode_neural_and_active_learning(self) -> None:
        store = ExperienceStore()
        runtime = CognitiveRuntime(
            enabled=True,
            shadow=True,
            iterative=False,
            belief_enabled=True,
            experience_learning=True,
            experience_store=store,
        )
        status = runtime.submit("Research current tide tables deeply", run=False)
        run_id = status["run_id"]
        state = runtime._require(run_id)
        state.decision = MetaDecision(
            mode=ReasoningMode.DEEP,
            strategy=ReasoningStrategy.RESEARCH_SYNTHESIS,
            budgets=CognitiveBudgets(),
            value_scores={},
            notes=(),
            neural_budgets=NeuralComputeBudget(native_effort=NativeEffort.HIGH),
            expected_gain=0.71,
        )
        state.verification_passed = False
        state.response_text = "Unverified draft"
        state.task.requires_research = True
        state.task.constraints.append("correction:use official buoy data")
        state.usage.critic_passes = 2
        state.usage.replans = 1
        # Seed unresolved hypotheses for trigger coverage.
        board = HypothesisBoard()
        h1 = board.add("tides rising", prior_plausibility=0.4)
        h2 = board.add("storm surge", prior_plausibility=0.3)
        h1.current_status = HypothesisStatus.UNRESOLVED
        h2.current_status = HypothesisStatus.UNRESOLVED
        state.hypothesis_board = board
        state.events.append(
            {
                "event_type": "capability_state_blocked",
                "payload": {"axis": "network"},
            }
        )

        runtime._finalize(state, budget_exhausted=True)

        self.assertIsNotNone(state.experience)
        self.assertEqual(state.experience["mode"], "DEEP")
        self.assertEqual(state.experience["neural_effort"], "HIGH")
        self.assertEqual(state.experience["expected_gain"], 0.71)
        self.assertEqual(state.experience["schema_version"], "2")

        al = store.list_active_learning()
        reasons = {c["reason"] for c in al}
        self.assertIn("verification_failed", reasons)
        self.assertTrue(
            reasons
            & {
                "budget_exhausted",
                "low_evidence_research",
                "repeated_critic_replan",
                "user_correction",
                "capability_blocked",
                "unresolved_hypotheses",
            }
        )
        self.assertTrue(all(c["auto_promote_forbidden"] for c in al))
        emitted = [
            e for e in state.events if e.get("event_type") == "active_learning_candidate"
        ]
        self.assertGreaterEqual(len(emitted), 1)


if __name__ == "__main__":
    unittest.main()
