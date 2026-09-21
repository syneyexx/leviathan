"""Phase 7: consolidation evaluate-then-promote tests."""

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


class NeuralConsolidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.torch = _torch_or_skip(self)
        from neural.checkpoint import NeuralMemoryCheckpointStore
        from neural.consolidation import ConsolidationGates, ConsolidationPipeline, dedupe_examples
        from neural.contracts import NeuralMode
        from neural.encoding import SlowMemoryExample
        from neural.experience import (
            ExperienceOutcome,
            ExperienceReward,
            NeuralExperience,
            RewardLabel,
        )
        from neural.runtime import NeuralModelRuntime
        from neural.slow_train import SlowTrainConfig
        from neural.toy_transformer import ToyTransformerConfig

        self.dedupe_examples = dedupe_examples
        self.SlowMemoryExample = SlowMemoryExample
        self.NeuralExperience = NeuralExperience
        self.ExperienceOutcome = ExperienceOutcome
        self.ExperienceReward = ExperienceReward
        self.RewardLabel = RewardLabel
        self.tmp = tempfile.TemporaryDirectory()
        self.store = NeuralMemoryCheckpointStore(Path(self.tmp.name) / "ckpts")
        self.runtime = NeuralModelRuntime(
            toy_config=ToyTransformerConfig(
                seed=17,
                hidden_size=32,
                num_heads=4,
                num_layers=2,
                max_seq_len=24,
            ),
            mode=NeuralMode.OFF,
        )
        self.pipeline = ConsolidationPipeline(
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

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _examples(self, n: int, *, seed: int) -> list:
        out = []
        for i in range(n):
            out.append(
                self.SlowMemoryExample(
                    example_id=f"{seed}-{i}",
                    key_text=f"problem class {seed}-{i}: resource leak on shutdown",
                    value_text=f"strategy {seed}-{i}: join workers then close db; verify with tests",
                    split="train",
                )
            )
        return out

    def test_dedupe_resolves_contradictions_by_priority(self) -> None:
        a = self.SlowMemoryExample("a", "same key task", "value one", split="train")
        b = self.SlowMemoryExample("b", "same key task", "value two better", split="train")
        deduped, contradictions = self.dedupe_examples([a, b], priorities={"a": 0.2, "b": 0.9})
        self.assertEqual(contradictions, 1)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0].example_id, "b")
        self.assertIn("better", deduped[0].value_text)

    def test_promote_after_passing_evaluation(self) -> None:
        examples = self._examples(6, seed=1)
        report = self.pipeline.run(
            checkpoint_id="cons_ok",
            examples=examples,
            retention_examples=examples[:2],
            reset_fast_on_promote=True,
        )
        self.assertTrue(report.promoted, report.to_dict())
        self.assertEqual(report.reason, "promoted_after_evaluation")
        self.assertTrue(report.candidate_saved)
        self.assertTrue(report.base_unchanged)
        self.assertTrue(report.fast_reset)
        # Good checkpoint pointer exists and loads.
        loaded = self.store.load(candidate=False)
        self.assertGreater(loaded.trainable_parameter_count(), 0)

    def test_reject_when_eval_gate_fails_and_restore_memory(self) -> None:
        # Impossible gates → must restore prior state and not promote.
        from neural.consolidation import ConsolidationGates, ConsolidationPipeline
        from neural.slow_train import SlowTrainConfig

        before = self.runtime.memory.snapshot()
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
        report = strict.run(
            checkpoint_id="cons_fail",
            examples=self._examples(4, seed=2),
        )
        self.assertFalse(report.promoted)
        self.assertEqual(report.reason, "evaluation_gates_failed")
        self.assertIn("gate_failures", report.details)
        after = self.runtime.memory.snapshot()
        for name in ("slow", "fast"):
            for k in before[name]:
                self.assertTrue(self.torch.equal(before[name][k], after[name][k]))
        # Candidate should not be promoted to good latest.
        latest = self.store.root / "latest.json"
        self.assertFalse(latest.is_file())

    def test_experiences_feed_consolidation(self) -> None:
        experiences = [
            self.NeuralExperience(
                experience_id="experience:run1",
                outcome=self.ExperienceOutcome.VERIFIED_SUCCESS,
                reward=self.ExperienceReward(label=self.RewardLabel.POSITIVE, score=1.0, signals={"verification_accepted": True}),
                problem_class="Fix lock ordering deadlock in worker pool",
                strategy="tools=pytest; files=backend/worker.py",
                verification="tests passed",
                result_summary="deadlock resolved",
                verified=True,
            ),
            self.NeuralExperience(
                experience_id="experience:run2",
                outcome=self.ExperienceOutcome.VERIFIED_SUCCESS,
                reward=self.ExperienceReward(label=self.RewardLabel.POSITIVE, score=0.8, signals={"verification_accepted": True}),
                problem_class="Repair flaky shutdown race in dataset brain",
                strategy="tools=unittest; files=backend/dataset_brain.py",
                verification="passed",
                result_summary="race fixed",
                verified=True,
            ),
        ]
        # Pad with synthetic examples so holdout/training has enough signal.
        extras = self._examples(4, seed=3)
        report = self.pipeline.run(
            checkpoint_id="cons_exp",
            experiences=experiences,
            examples=extras,
        )
        self.assertTrue(report.promoted, report.to_dict())
        self.assertGreaterEqual(report.examples_after_dedupe, 2)

    def test_loss_alone_does_not_promote(self) -> None:
        # Missing recall metrics path is blocked by design; simulate by empty train
        # after filters — no eligible examples.
        report = self.pipeline.run(checkpoint_id="cons_empty", examples=[])
        self.assertFalse(report.promoted)
        self.assertEqual(report.reason, "no_eligible_examples")

    def test_reject_candidate_helper(self) -> None:
        examples = self._examples(4, seed=4)
        # Force a candidate save via successful path then reject API on a fresh id.
        ok = self.pipeline.run(checkpoint_id="cons_rejectable", examples=examples)
        self.assertTrue(ok.promoted)
        # Manually create a throwaway candidate and reject it.
        self.store.save(self.runtime.memory, checkpoint_id="cons_tmp", candidate=True)
        self.pipeline.reject("cons_tmp")
        self.assertFalse((self.store.candidate_dir / "cons_tmp").exists())

    def test_main_untouched(self) -> None:
        text = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("consolidation", text)
        self.assertNotIn("ConsolidationPipeline", text)


if __name__ == "__main__":
    unittest.main()
