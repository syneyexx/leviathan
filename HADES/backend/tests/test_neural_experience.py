"""Phase 6: verified experiences → neural learning signals."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.flight_recorder import record
from gen2.store import Gen2Store
from neural.experience import (
    ExperienceOutcome,
    ExperienceReward,
    NeuralExperience,
    RewardLabel,
    apply_experience_to_fast_session,
    experience_eligible_for_fast_memory,
    experience_to_slow_example,
    experiences_from_store,
    neural_experience_from_verified_item,
    reward_from_signals,
)


class NeuralExperienceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "experience.db"))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _verified_success(self, run_id: str = "run-success") -> None:
        record(
            self.store,
            run_id,
            "PLAN",
            {
                "goal": "Fix multiprocessing shutdown corruption",
                "reasoning": "private scratchpad that must never become neural memory",
                "chain_of_thought": "also forbidden",
            },
        )
        record(self.store, run_id, "TOOL", {"tool_name": "pytest", "ok": True, "path": "backend/tests"})
        record(
            self.store,
            run_id,
            "VERIFY",
            {"passed": True, "summary": "152/152 tests passed"},
        )
        record(
            self.store,
            run_id,
            "TERMINAL",
            {"ok": True, "status": "completed", "summary": "shutdown race fixed"},
        )

    def test_reward_signals_are_explicit(self) -> None:
        positive = reward_from_signals(verification_accepted=True, tests_passed=True, task_completed=True)
        self.assertEqual(positive.label, RewardLabel.POSITIVE)
        self.assertGreater(positive.score, 0)
        unverified = reward_from_signals(task_completed=True, verification_accepted=None)
        self.assertEqual(unverified.label, RewardLabel.INELIGIBLE)
        negative = reward_from_signals(verification_rejected=True)
        self.assertEqual(negative.label, RewardLabel.NEGATIVE)

    def test_experiences_exclude_hidden_reasoning(self) -> None:
        self._verified_success()
        experiences = experiences_from_store(self.store, "multiprocessing shutdown", limit=5)
        self.assertTrue(experiences)
        exp = experiences[0]
        self.assertFalse(exp.contains_chain_of_thought)
        blob = " ".join(
            [
                exp.problem_class,
                exp.strategy,
                exp.verification,
                exp.result_summary,
                str(exp.metadata),
            ]
        )
        self.assertNotIn("private scratchpad", blob)
        self.assertNotIn("chain_of_thought", blob.lower())
        self.assertNotIn("also forbidden", blob)
        self.assertEqual(exp.outcome, ExperienceOutcome.VERIFIED_SUCCESS)
        self.assertTrue(exp.verified)
        self.assertEqual(exp.reward.label, RewardLabel.POSITIVE)

    def test_unverified_completion_not_eligible(self) -> None:
        record(self.store, "unverified", "PLAN", {"goal": "Fix multiprocessing shutdown corruption"})
        record(self.store, "unverified", "TERMINAL", {"ok": True, "status": "completed"})
        experiences = experiences_from_store(self.store, "multiprocessing shutdown", limit=5)
        # retrieve_verified_experiences should already exclude unverified; double-check.
        self.assertTrue(all(exp.verified for exp in experiences))
        self.assertTrue(all(experience_eligible_for_fast_memory(exp) for exp in experiences))

    def test_slow_example_from_positive_experience(self) -> None:
        self._verified_success()
        exp = experiences_from_store(self.store, "multiprocessing shutdown", limit=1)[0]
        example = experience_to_slow_example(exp)
        self.assertIsNotNone(example)
        assert example is not None
        self.assertIn("multiprocessing", example.key_text.lower())
        self.assertIn("verification", example.value_text.lower())
        self.assertNotIn("scratchpad", example.value_text.lower())

    def test_negative_reward_maps_to_negative_slow_not_positive(self) -> None:
        exp = NeuralExperience(
            experience_id="exp-neg",
            outcome=ExperienceOutcome.VERIFIED_FAILURE,
            reward=ExperienceReward(label=RewardLabel.NEGATIVE, score=-1.0, signals={"verification_rejected": True}),
            problem_class="broken patch",
            strategy="tools=apply_patch",
            verification="rejected",
            result_summary="tests failed",
            verified=True,
        )
        from neural.experience import experience_to_negative_slow_example

        self.assertIsNone(experience_to_slow_example(exp))
        self.assertFalse(experience_eligible_for_fast_memory(exp))
        neg = experience_to_negative_slow_example(exp)
        self.assertIsNotNone(neg)
        assert neg is not None
        self.assertTrue(neg.value_text.startswith("AVOID:"))
        self.assertEqual(neg.sample_type, "verified_failure_avoidance")

    def test_fast_session_accepts_only_eligible_experience_vectors(self) -> None:
        from neural.deps import neural_available

        if not neural_available():
            self.skipTest("torch unavailable")
        import torch
        from neural.config import NeuralMemoryConfig
        from neural.contracts import NeuralMode
        from neural.fast_memory import FastMemorySession, FastWritePolicy
        from neural.memory import NeuralMemory

        self._verified_success()
        exp = experiences_from_store(self.store, "multiprocessing shutdown", limit=1)[0]
        self.assertTrue(experience_eligible_for_fast_memory(exp))
        memory = NeuralMemory(NeuralMemoryConfig(dim=16, hidden_dim=32, mode=NeuralMode.OFF, seed=2))
        session = FastMemorySession(
            memory,
            policy=FastWritePolicy(
                require_verified=True,
                min_surprise=0.05,
                max_update_steps=30,
                learning_rate=0.2,
                max_writes_per_session=4,
            ),
        )
        key = torch.nn.functional.normalize(torch.randn(16), dim=0)
        value = torch.nn.functional.normalize(torch.randn(16), dim=0)
        result = apply_experience_to_fast_session(session, exp, key_vector=key, value_vector=value)
        self.assertTrue(result.decision.verified)
        # May accept or skip on surprise; must not be unverified rejection.
        self.assertNotEqual(result.decision.reason, "unverified_experience")

        ineligible = NeuralExperience(
            experience_id="exp-raw",
            outcome=ExperienceOutcome.UNVERIFIED_SUCCESS,
            reward=ExperienceReward(label=RewardLabel.INELIGIBLE, score=0.0, signals={}),
            problem_class="hallucinated fix",
            strategy="tools=none",
            verification="",
            result_summary="model said it worked",
            verified=False,
        )
        blocked = apply_experience_to_fast_session(session, ineligible, key_vector=key, value_vector=value)
        self.assertFalse(blocked.accepted)
        self.assertEqual(blocked.decision.reason, "unverified_experience")

    def test_hidden_key_in_item_rejected(self) -> None:
        from neural.experience import NeuralExperienceError

        with self.assertRaises(NeuralExperienceError):
            neural_experience_from_verified_item(
                {
                    "item_id": "experience:bad",
                    "content": "Task: x\nVerification: ok",
                    "metadata": {"run_id": "bad", "outcome": "verified_success", "reasoning": "nope"},
                }
            )

    def test_main_does_not_import_neural_experience(self) -> None:
        text = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("neural.experience", text)


if __name__ == "__main__":
    unittest.main()
