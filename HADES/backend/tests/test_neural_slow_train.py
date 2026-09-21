"""Phase 4: slow neural-memory training from frozen encodings."""

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


class NeuralSlowTrainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.torch = _torch_or_skip(self)
        from neural.checkpoint import NeuralMemoryCheckpointStore
        from neural.contracts import NeuralMode
        from neural.encoding import SlowMemoryExample, example_from_row
        from neural.runtime import NeuralModelRuntime
        from neural.slow_train import SlowNeuralMemoryTrainer, SlowTrainConfig
        from neural.toy_transformer import ToyTransformerConfig

        self.NeuralMode = NeuralMode
        self.SlowMemoryExample = SlowMemoryExample
        self.example_from_row = example_from_row
        self.tmp = tempfile.TemporaryDirectory()
        self.store = NeuralMemoryCheckpointStore(Path(self.tmp.name) / "ckpts")
        self.runtime = NeuralModelRuntime(
            toy_config=ToyTransformerConfig(
                vocab_size=64,
                hidden_size=32,
                num_layers=2,
                num_heads=4,
                intermediate_size=64,
                max_seq_len=24,
                seed=42,
            ),
            mode=NeuralMode.OFF,
            fusion_scale=0.0,
        )
        self.trainer = SlowNeuralMemoryTrainer(
            self.runtime,
            config=SlowTrainConfig(
                learning_rate=0.1,
                max_steps_per_batch=80,
                batch_size=2,
                loss_tolerance=0.05,
                replay_size=2,
            ),
            checkpoint_store=self.store,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _examples(self, n: int = 4, *, seed: int = 0) -> list:
        examples = []
        for i in range(n):
            examples.append(
                self.SlowMemoryExample(
                    example_id=f"ex-{seed}-{i}",
                    key_text=f"problem class {seed}-{i}: lock ordering in subsystem",
                    value_text=f"strategy {seed}-{i}: inspect shutdown boundary then verify tests",
                    split="train",
                )
            )
        return examples

    def test_base_checksum_unchanged_after_slow_training(self) -> None:
        examples = self._examples(4)
        report = self.trainer.fit(examples, checkpoint_id="slow_001")
        self.assertTrue(report.base_unchanged, report.to_dict())
        self.assertEqual(report.base_checksum_before, report.base_checksum_after)
        self.assertGreater(report.examples_seen, 0)
        self.assertGreater(report.batches, 0)

    def test_slow_memory_learns_associations(self) -> None:
        examples = self._examples(3, seed=1)
        before = self.trainer.evaluate_recall(examples)
        report = self.trainer.fit(examples, checkpoint_id="slow_learn")
        after = report.train_recall
        self.assertIsNotNone(after)
        self.assertGreaterEqual(after or 0.0, 0.75, report.to_dict())
        self.assertGreaterEqual((after or 0.0) - before, 0.2, {"before": before, "after": after})

    def test_only_slow_parameters_change_by_default(self) -> None:
        slow_before = {k: v.detach().clone() for k, v in self.runtime.memory.slow.state_dict().items()}
        fast_before = {k: v.detach().clone() for k, v in self.runtime.memory.fast.state_dict().items()}
        self.trainer.fit(self._examples(4, seed=2), checkpoint_id="slow_params")
        slow_changed = any(
            not self.torch.equal(slow_before[k], v) for k, v in self.runtime.memory.slow.state_dict().items()
        )
        fast_unchanged = all(
            self.torch.equal(fast_before[k], v) for k, v in self.runtime.memory.fast.state_dict().items()
        )
        self.assertTrue(slow_changed)
        self.assertTrue(fast_unchanged)

    def test_sequential_retention_after_second_batch(self) -> None:
        first = self._examples(3, seed=10)
        second = self._examples(3, seed=20)
        self.trainer.fit(first, checkpoint_id="ret_a")
        first_score = self.trainer.evaluate_recall(first)
        self.trainer.fit(second, checkpoint_id="ret_b")
        retained = self.trainer.evaluate_recall(first)
        new_score = self.trainer.evaluate_recall(second)
        self.assertGreaterEqual(first_score, 0.75)
        self.assertGreaterEqual(retained, 0.45, {"first": first_score, "retained": retained})
        self.assertGreaterEqual(new_score, 0.70)

    def test_example_from_row_respects_hidden_and_structure(self) -> None:
        row = {
            "instruction": "Fix flaky shutdown",
            "output": "Join worker threads before closing DB",
            "reasoning": "secret-chain-must-not-become-key",
        }
        example = self.example_from_row(1, row, dataset_id="ds_test")
        self.assertIsNotNone(example)
        assert example is not None
        self.assertEqual(example.sample_type, "instruction_response")
        self.assertNotIn("secret-chain", example.key_text)
        self.assertNotIn("secret-chain", example.value_text)

    def test_streaming_rows_do_not_require_materialized_list_api(self) -> None:
        from neural.slow_train import iter_examples_from_jsonl_rows

        rows = [
            (1, {"query": "Q-alpha", "answer": "A-alpha"}),
            (2, {"query": "Q-beta", "answer": "A-beta"}),
            (3, {"text": "short"}),
        ]
        stream = iter_examples_from_jsonl_rows(rows, dataset_id="ds_stream")
        examples = list(stream)
        self.assertEqual(len(examples), 2)
        report = self.trainer.fit(examples, checkpoint_id="stream_1")
        self.assertTrue(report.base_unchanged)
        self.assertGreaterEqual(report.train_recall or 0.0, 0.7)

    def test_candidate_checkpoint_saved(self) -> None:
        report = self.trainer.fit(self._examples(2, seed=3), checkpoint_id="cand_slow")
        self.assertEqual(report.candidate_checkpoint_id, "cand_slow")
        loaded = self.store.load("cand_slow", candidate=True)
        # Loaded memory should still recall roughly after restore.
        self.runtime.memory.restore(loaded.snapshot())
        score = self.trainer.evaluate_recall(self._examples(2, seed=3))
        self.assertGreaterEqual(score, 0.7)

    def test_runtime_stays_off_and_rejects_learn(self) -> None:
        from neural.errors import NeuralModeUnsupported

        self.assertEqual(self.runtime.mode, self.NeuralMode.OFF)
        with self.assertRaises(NeuralModeUnsupported):
            self.runtime.set_mode(self.NeuralMode.LEARN)


if __name__ == "__main__":
    unittest.main()
