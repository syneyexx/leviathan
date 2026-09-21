"""Phase 12: ContinualLearningPipeline end-to-end safety tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _torch_or_skip(test: unittest.TestCase):
    from neural.deps import neural_available

    if not neural_available():
        test.skipTest("torch unavailable")
    import torch

    return torch


def _exp(**kwargs):
    from neural.experience import ExperienceOutcome, ExperienceReward, NeuralExperience, RewardLabel

    defaults = dict(
        experience_id="exp-1",
        outcome=ExperienceOutcome.VERIFIED_SUCCESS,
        reward=ExperienceReward(label=RewardLabel.POSITIVE, score=1.0, signals={"tests_passed": True}),
        problem_class="shutdown race on worker pool",
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


class ContinualEligibilityTests(unittest.TestCase):
    def test_verified_success_eligible(self) -> None:
        from neural.continual_learning import evaluate_learning_eligibility

        decision = evaluate_learning_eligibility(_exp())
        self.assertTrue(decision.eligible)
        self.assertTrue(decision.fast_memory_eligible)
        self.assertTrue(decision.consolidation_eligible)
        self.assertEqual(decision.reason, "verified_success")

    def test_raw_model_output_rejected(self) -> None:
        from neural.continual_learning import evaluate_learning_eligibility

        decision = evaluate_learning_eligibility(
            _exp(source="raw_model_output", verified=False, verification="", tools=(), files=())
        )
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.reason, "raw_model_output_not_trainable")

    def test_failed_experience_not_positive_success_memory(self) -> None:
        from neural.continual_learning import evaluate_learning_eligibility
        from neural.experience import ExperienceOutcome, ExperienceReward, RewardLabel

        decision = evaluate_learning_eligibility(
            _exp(
                outcome=ExperienceOutcome.VERIFIED_FAILURE,
                reward=ExperienceReward(label=RewardLabel.NEGATIVE, score=-1.0),
                verification="tests_failed",
            )
        )
        self.assertTrue(decision.eligible)
        self.assertTrue(decision.failure_memory)
        self.assertFalse(decision.fast_memory_eligible)
        self.assertFalse(decision.consolidation_eligible)

    def test_secret_containing_experience_rejected(self) -> None:
        from neural.continual_learning import (
            ContinualLearningPipeline,
            evaluate_learning_eligibility,
            raise_if_unsafe_for_slow_memory,
        )
        from neural.errors import NeuralSecretRejected
        from neural.learning_lifecycle import ExperienceLifecycleState

        secret_exp = _exp(
            experience_id="secret-1",
            result_summary="set api_key=sk-live-secret-token-12345 and continue",
        )
        decision = evaluate_learning_eligibility(secret_exp)
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.reason, "secret_material_rejected")

        pipe = ContinualLearningPipeline()
        result = pipe.process_experience(secret_exp)
        self.assertEqual(result.lifecycle_state, ExperienceLifecycleState.REJECTED.value)
        self.assertIsNone(result.fast_write)
        self.assertIsNone(result.consolidation)

        with self.assertRaises(NeuralSecretRejected):
            raise_if_unsafe_for_slow_memory(secret_exp)

    def test_personal_data_rejected_from_slow_path(self) -> None:
        from neural.continual_learning import evaluate_learning_eligibility, raise_if_unsafe_for_slow_memory
        from neural.errors import NeuralPersonalDataRejected

        personal = _exp(
            experience_id="p1",
            problem_class="store user home address for future replies",
            result_summary="saved street address for profile",
        )
        decision = evaluate_learning_eligibility(personal)
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.reason, "personal_data_rejected")
        with self.assertRaises(NeuralPersonalDataRejected):
            raise_if_unsafe_for_slow_memory(personal)

    def test_partial_and_rejected_outcomes_blocked(self) -> None:
        from neural.continual_learning import evaluate_learning_eligibility
        from neural.experience import ExperienceOutcome, ExperienceReward, RewardLabel

        for outcome in (ExperienceOutcome.PARTIAL, ExperienceOutcome.REJECTED, ExperienceOutcome.BLOCKED):
            decision = evaluate_learning_eligibility(
                _exp(
                    outcome=outcome,
                    reward=ExperienceReward(label=RewardLabel.NEUTRAL, score=0.0),
                    verified=False,
                )
            )
            self.assertFalse(decision.eligible, outcome)
            self.assertIn(outcome.value, decision.reason)


class ContinualPipelineIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.torch = _torch_or_skip(self)
        from neural.checkpoint import NeuralMemoryCheckpointStore
        from neural.config import NeuralMemoryConfig
        from neural.consolidation import ConsolidationGates, ConsolidationPipeline
        from neural.continual_learning import ContinualLearningPipeline
        from neural.contracts import NeuralMode
        from neural.encoding import SlowMemoryExample
        from neural.fast_memory import FastMemorySession, FastWritePolicy
        from neural.memory import NeuralMemory
        from neural.runtime import NeuralModelRuntime
        from neural.slow_train import SlowTrainConfig
        from neural.toy_transformer import ToyTransformerConfig, parameter_checksum

        self.parameter_checksum = parameter_checksum
        self.SlowMemoryExample = SlowMemoryExample
        self.tmp = tempfile.TemporaryDirectory()
        self.store = NeuralMemoryCheckpointStore(Path(self.tmp.name) / "ckpts")
        self.runtime = NeuralModelRuntime(
            toy_config=ToyTransformerConfig(
                seed=21,
                hidden_size=32,
                num_heads=4,
                num_layers=2,
                max_seq_len=24,
            ),
            mode=NeuralMode.OFF,
        )
        self.memory = NeuralMemory(
            NeuralMemoryConfig(
                dim=32,
                hidden_dim=64,
                fast_hidden_dim=32,
                mode=NeuralMode.OFF,
                seed=11,
            )
        )
        self.fast_session = FastMemorySession(
            self.memory,
            policy=FastWritePolicy(
                require_verified=True,
                min_surprise=0.15,
                max_writes_per_session=8,
                max_update_steps=40,
                learning_rate=0.15,
                loss_tolerance=0.08,
            ),
        )
        self.consolidation = ConsolidationPipeline(
            self.runtime,
            self.store,
            gates=ConsolidationGates(
                min_train_recall=0.70,
                min_eval_recall=0.55,
                max_retention_drop=0.35,
                require_eval_examples=True,
                max_final_loss=0.5,
            ),
            train_config=SlowTrainConfig(
                learning_rate=0.12,
                max_steps_per_batch=80,
                batch_size=2,
                loss_tolerance=0.05,
                replay_size=2,
            ),
        )
        self.pipe = ContinualLearningPipeline(
            consolidation=self.consolidation,
            fast_session=self.fast_session,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _pair(self, seed: int):
        g = self.torch.Generator().manual_seed(seed)
        key = self.torch.nn.functional.normalize(self.torch.randn(32, generator=g), dim=0)
        value = self.torch.nn.functional.normalize(self.torch.randn(32, generator=g), dim=0)
        return key, value

    def _pad_examples(self, n: int, *, seed: int):
        out = []
        for i in range(n):
            out.append(
                self.SlowMemoryExample(
                    example_id=f"pad-{seed}-{i}",
                    key_text=f"problem class {seed}-{i}: resource leak on shutdown",
                    value_text=f"strategy {seed}-{i}: join workers then close db; verify with tests",
                    split="train",
                )
            )
        return out

    def test_fast_memory_write_from_verified_success(self) -> None:
        key, value = self._pair(4)
        result = self.pipe.process_experience(
            _exp(experience_id="fast-ok"),
            key_vector=key,
            value_vector=value,
            source_reliability=1.0,
        )
        self.assertIsNotNone(result.fast_write)
        self.assertTrue(result.fast_write["accepted"], result.to_dict())
        self.assertIn("fast_memory", result.lifecycle_state)

    def test_fast_memory_update_can_rollback(self) -> None:
        # Force delta-norm rejection → rolled_back write preserves prior fast state.
        from neural.fast_memory import FastWritePolicy

        strict = FastWritePolicy(
            require_verified=True,
            min_surprise=0.0,
            max_surprise=2.0,
            max_writes_per_session=8,
            max_update_steps=40,
            learning_rate=0.2,
            max_parameter_delta_norm=1e-9,
            loss_tolerance=0.0,
            min_source_reliability=0.0,
        )
        self.fast_session.policy = strict
        before = {k: v.detach().clone() for k, v in self.memory.fast.state_dict().items()}
        key, value = self._pair(7)
        result = self.pipe.process_experience(
            _exp(experience_id="fast-rb"),
            key_vector=key,
            value_vector=value,
            source_reliability=1.0,
        )
        self.assertIsNotNone(result.fast_write)
        self.assertFalse(result.fast_write["accepted"])
        write = result.fast_write.get("write") or {}
        self.assertTrue(
            write.get("rolled_back")
            or "delta" in str(write.get("reason") or "").lower()
            or "not_converged" in str(write.get("reason") or "").lower(),
            result.to_dict(),
        )
        for k, v in self.memory.fast.state_dict().items():
            self.assertTrue(self.torch.equal(before[k], v), k)
        self.assertGreaterEqual(self.fast_session.rollbacks, 1)

    def test_candidate_evaluation_can_reject_and_preserve_known_good(self) -> None:
        from neural.consolidation import ConsolidationGates, ConsolidationPipeline
        from neural.slow_train import SlowTrainConfig

        # Establish a known-good promoted checkpoint first.
        ok_examples = self._pad_examples(6, seed=1)
        ok = self.consolidation.run(checkpoint_id="known_good", examples=ok_examples)
        self.assertTrue(ok.promoted, ok.to_dict())
        known_good = self.store.load(candidate=False)
        good_count = known_good.trainable_parameter_count()
        good_slow = {k: v.detach().clone() for k, v in known_good.slow.state_dict().items()}

        # Impossible gates → reject candidate; known-good must survive.
        strict = ConsolidationPipeline(
            self.runtime,
            self.store,
            gates=ConsolidationGates(
                min_train_recall=0.999,
                min_eval_recall=0.999,
                require_eval_examples=True,
                max_final_loss=0.0001,
            ),
            train_config=SlowTrainConfig(
                learning_rate=0.01,
                max_steps_per_batch=2,
                batch_size=2,
                loss_tolerance=0.0001,
            ),
        )
        pipe = type(self.pipe)(consolidation=strict, fast_session=self.fast_session)
        before_mem = self.runtime.memory.snapshot()
        result = pipe.process_experience(
            _exp(experience_id="cand-reject"),
            run_consolidation=True,
            checkpoint_id="bad_candidate",
            pad_examples=self._pad_examples(4, seed=9),
        )
        self.assertTrue(result.rolled_back)
        self.assertEqual(result.lifecycle_state, "promotion_rejected")
        self.assertFalse(result.consolidation["promoted"])
        after_mem = self.runtime.memory.snapshot()
        for bank in ("slow", "fast"):
            for k in before_mem[bank]:
                self.assertTrue(self.torch.equal(before_mem[bank][k], after_mem[bank][k]))
        still_good = self.store.load(candidate=False)
        self.assertEqual(still_good.trainable_parameter_count(), good_count)
        for k, v in still_good.slow.state_dict().items():
            self.assertTrue(self.torch.equal(good_slow[k], v), k)
        latest = self.store.root / "latest.json"
        self.assertTrue(latest.is_file())

    def test_candidate_promotion_is_atomic_and_base_unchanged(self) -> None:
        from neural.toy_transformer import parameter_checksum

        base_before = parameter_checksum(self.runtime.base_model)
        self.assertEqual(base_before, self.runtime.base_checksum)
        pad = self._pad_examples(6, seed=3)
        retention = pad[:2]
        result = self.pipe.process_experience(
            _exp(experience_id="promote-ok", problem_class="Fix lock ordering deadlock in worker pool"),
            run_consolidation=True,
            checkpoint_id="cons_promote",
            pad_examples=pad,
            retention_examples=retention,
        )
        self.assertTrue(result.consolidation["promoted"], result.to_dict())
        self.assertTrue(result.base_unchanged)
        self.assertEqual(result.lifecycle_state, "promoted")
        base_after = parameter_checksum(self.runtime.base_model)
        self.assertEqual(base_before, base_after)
        loaded = self.store.load(candidate=False)
        self.assertGreater(loaded.trainable_parameter_count(), 0)
        # Retention measured when provided.
        self.assertIsNotNone(result.retention_before)
        self.assertIsNotNone(result.retention_after)

    def test_slow_candidate_isolated_from_live_until_promote(self) -> None:
        from neural.consolidation import ConsolidationGates, ConsolidationPipeline
        from neural.slow_train import SlowTrainConfig

        # Strict gates keep candidate from promoting; live good pointer absent.
        strict = ConsolidationPipeline(
            self.runtime,
            self.store,
            gates=ConsolidationGates(
                min_train_recall=0.999,
                min_eval_recall=0.999,
                max_final_loss=1e-9,
            ),
            train_config=SlowTrainConfig(learning_rate=0.01, max_steps_per_batch=2, batch_size=2),
        )
        pipe = type(self.pipe)(consolidation=strict)
        result = pipe.process_experience(
            _exp(experience_id="iso-1"),
            run_consolidation=True,
            checkpoint_id="isolated_cand",
            pad_examples=self._pad_examples(4, seed=5),
        )
        self.assertFalse(result.consolidation["promoted"])
        self.assertFalse((self.store.root / "latest.json").is_file())

    def test_normal_hades_off_path_unchanged(self) -> None:
        from neural.contracts import NeuralMode
        from neural.errors import NeuralModeUnsupported
        from neural.learning_lifecycle import assert_learn_disabled_by_default
        from neural.runtime_lifecycle import NeuralRuntimeBoundary, NeuralRuntimeStartConfig
        from neural.contracts import NeuralInferRequest

        assert_learn_disabled_by_default(learn_enabled=False)
        rt = NeuralRuntimeBoundary()
        rt.start(NeuralRuntimeStartConfig(mode=NeuralMode.OFF))
        with self.assertRaises(NeuralModeUnsupported):
            rt.infer(NeuralInferRequest(request_id="off-learn", input_ids=[[1, 2]], mode=NeuralMode.LEARN))
        # OFF infer path still works as a hard bypass (no neural fusion).
        out = rt.infer(NeuralInferRequest(request_id="off-ok", input_ids=[[1, 2, 3]], mode=NeuralMode.OFF))
        self.assertIsNotNone(out)
        rt.stop()

    def test_secret_batch_item_excluded_from_consolidation(self) -> None:
        secret = _exp(
            experience_id="batch-secret",
            result_summary="password=hunter2 leaked into notes",
        )
        pad = self._pad_examples(6, seed=8)
        result = self.pipe.process_experience(
            _exp(experience_id="batch-ok", problem_class="Repair flaky shutdown race"),
            run_consolidation=True,
            checkpoint_id="batch_safe",
            pad_examples=pad,
            additional_experiences=[secret],
        )
        self.assertTrue(any("batch_excluded:batch-secret" in n for n in result.notes))
        self.assertTrue(result.consolidation["promoted"] or result.rolled_back)


if __name__ == "__main__":
    unittest.main()
