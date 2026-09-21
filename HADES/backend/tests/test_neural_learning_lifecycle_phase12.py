"""Phase 12: continual learning safety lifecycle tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _exp(**kwargs):
    from neural.experience import ExperienceOutcome, ExperienceReward, NeuralExperience, RewardLabel

    defaults = dict(
        experience_id="exp-1",
        outcome=ExperienceOutcome.VERIFIED_SUCCESS,
        reward=ExperienceReward(label=RewardLabel.POSITIVE, score=1.0, signals={"tests_passed": True}),
        problem_class="shutdown",
        strategy="join-then-close",
        verification="tests_passed",
        result_summary="ok",
        tools=("pytest",),
        files=("backend/worker.py",),
        source="verified_experience",
        verified=True,
        contains_chain_of_thought=False,
    )
    defaults.update(kwargs)
    return NeuralExperience(**defaults)


class LearningLifecycleTests(unittest.TestCase):
    def test_raw_model_output_rejected(self) -> None:
        from neural.learning_lifecycle import ExperienceLifecycle, ExperienceLifecycleState

        life = ExperienceLifecycle("raw-1", source_kind="raw_model_output")
        record = life.admit_from_neural_experience(
            _exp(source="raw_model_output", verified=False, verification="", tools=(), files=())
        )
        self.assertEqual(record.state, ExperienceLifecycleState.REJECTED)
        self.assertEqual(record.rejection_reason, "raw_model_output_not_trainable")

    def test_unverified_completion_rejected(self) -> None:
        from neural.experience import ExperienceOutcome, ExperienceReward, RewardLabel
        from neural.learning_lifecycle import ExperienceLifecycle, ExperienceLifecycleState

        life = ExperienceLifecycle("u1")
        record = life.admit_from_neural_experience(
            _exp(
                outcome=ExperienceOutcome.UNVERIFIED_SUCCESS,
                reward=ExperienceReward(label=RewardLabel.INELIGIBLE, score=0.0),
                verified=False,
                verification="",
            )
        )
        self.assertEqual(record.state, ExperienceLifecycleState.REJECTED)

    def test_verified_success_becomes_training_eligible(self) -> None:
        from neural.learning_lifecycle import ExperienceLifecycle, ExperienceLifecycleState

        life = ExperienceLifecycle("ok1", source_kind="verified_experience")
        record = life.admit_from_neural_experience(_exp())
        self.assertEqual(record.state, ExperienceLifecycleState.TRAINING_ELIGIBLE)
        self.assertIn(ExperienceLifecycleState.VERIFICATION.value, record.history)
        self.assertIn(ExperienceLifecycleState.ACCEPTED.value, record.history)

    def test_verified_failure_can_be_failure_memory(self) -> None:
        from neural.experience import ExperienceOutcome, ExperienceReward, RewardLabel
        from neural.learning_lifecycle import ExperienceLifecycle, ExperienceLifecycleState

        life = ExperienceLifecycle("fail2")
        record = life.admit_from_neural_experience(
            _exp(
                outcome=ExperienceOutcome.VERIFIED_FAILURE,
                reward=ExperienceReward(label=RewardLabel.NEGATIVE, score=-0.8),
                verified=True,
                verification="tests_failed",
            )
        )
        self.assertEqual(record.state, ExperienceLifecycleState.TRAINING_ELIGIBLE)
        self.assertTrue(record.metadata.get("failure_memory"))

    def test_illegal_transition_fails_closed(self) -> None:
        from neural.learning_lifecycle import (
            ExperienceLifecycle,
            ExperienceLifecycleState,
            LearningLifecycleError,
        )

        life = ExperienceLifecycle("x")
        with self.assertRaises(LearningLifecycleError):
            life.transition(ExperienceLifecycleState.PROMOTED)

    def test_promote_path_requires_evaluation(self) -> None:
        from neural.learning_lifecycle import ExperienceLifecycle, ExperienceLifecycleState

        life = ExperienceLifecycle("p1")
        life.admit_from_neural_experience(_exp())
        life.mark_fast_memory_written()
        life.mark_consolidation_candidate()
        life.mark_slow_candidate()
        life.mark_evaluation()
        life.mark_promoted()
        self.assertEqual(life.state, ExperienceLifecycleState.PROMOTED)

    def test_learn_remains_disabled_by_default(self) -> None:
        from neural.errors import NeuralModeUnsupported
        from neural.learning_lifecycle import assert_learn_disabled_by_default

        assert_learn_disabled_by_default(learn_enabled=False)
        with self.assertRaises(NeuralModeUnsupported):
            assert_learn_disabled_by_default(learn_enabled=True)

    def test_hidden_reasoning_rejected(self) -> None:
        from neural.learning_lifecycle import ExperienceLifecycle, ExperienceLifecycleState

        life = ExperienceLifecycle("cot")
        record = life.admit_from_neural_experience(_exp(contains_chain_of_thought=True))
        self.assertEqual(record.state, ExperienceLifecycleState.REJECTED)
        self.assertEqual(record.rejection_reason, "hidden_reasoning_rejected")

    def test_runtime_learn_still_rejected(self) -> None:
        from neural.deps import neural_available

        if not neural_available():
            self.skipTest("torch unavailable")
        from neural.contracts import NeuralMode
        from neural.errors import NeuralModeUnsupported
        from neural.runtime_lifecycle import NeuralRuntimeBoundary, NeuralRuntimeStartConfig

        rt = NeuralRuntimeBoundary()
        rt.start(NeuralRuntimeStartConfig(mode=NeuralMode.OFF))
        from neural.contracts import NeuralInferRequest

        with self.assertRaises(NeuralModeUnsupported):
            rt.infer(NeuralInferRequest(request_id="l", input_ids=[[1, 2]], mode=NeuralMode.LEARN))
        rt.stop()


if __name__ == "__main__":
    unittest.main()
