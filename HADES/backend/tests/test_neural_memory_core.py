"""Phase 1 core tests: association, parameters, safe writes, determinism."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _torch_or_skip(test: unittest.TestCase):
    from neural.deps import neural_available

    if not neural_available():
        test.skipTest("torch unavailable")
    import torch

    return torch


class NeuralMemoryCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.torch = _torch_or_skip(self)
        from neural.config import NeuralMemoryConfig
        from neural.contracts import NeuralMode
        from neural.memory import NeuralMemory

        self.NeuralMemory = NeuralMemory
        self.NeuralMode = NeuralMode
        self.config = NeuralMemoryConfig(
            dim=24,
            hidden_dim=64,
            fast_hidden_dim=32,
            mode=NeuralMode.LEARN,
            seed=7,
            learning_rate=0.2,
            max_update_steps=80,
            loss_tolerance=0.08,
            replay_enabled=True,
            replay_batch_size=3,
            max_parameter_delta_norm=100.0,
        )
        self.memory = NeuralMemory(self.config)

    def test_has_trainable_parameters(self) -> None:
        n = self.memory.trainable_parameter_count()
        self.assertGreater(n, 100)
        metrics = self.memory.metrics()
        self.assertEqual(metrics.parameter_count, n)
        self.assertGreater(metrics.slow_parameter_count, 0)
        self.assertGreater(metrics.fast_parameter_count, 0)

    def test_basic_association(self) -> None:
        from neural.evals import evaluate_recall, make_association_pairs, train_pairs

        pairs = make_association_pairs(self.config.dim, 3, seed=11)
        results = train_pairs(self.memory, pairs)
        self.assertTrue(all(r["accepted"] for r in results), results)
        report = evaluate_recall(self.memory, pairs, name="basic")
        # Cosine reconstruction target: clearly above chance (~0).
        self.assertGreaterEqual(report.mean_cosine, 0.85, report.to_dict())
        self.assertGreaterEqual(report.min_cosine, 0.70, report.to_dict())

    def test_shadow_read_does_not_write(self) -> None:
        self.memory.set_mode(self.NeuralMode.SHADOW)
        key = self.torch.randn(self.config.dim)
        read = self.memory.read(key)
        self.assertIsNotNone(read.value)
        self.assertTrue(read.diagnostics.get("shadow"))
        write = self.memory.write(key, key)
        self.assertFalse(write.accepted)
        self.assertEqual(write.reason, "mode_shadow_no_writes")

    def test_read_mode_forbids_writes(self) -> None:
        self.memory.set_mode(self.NeuralMode.READ)
        key = self.torch.randn(self.config.dim)
        write = self.memory.write(key, key)
        self.assertFalse(write.accepted)
        self.assertEqual(write.reason, "mode_read_no_writes")

    def test_nan_write_rolls_back(self) -> None:
        key = self.torch.randn(self.config.dim)
        value = self.torch.randn(self.config.dim)
        ok = self.memory.write(key, value)
        self.assertTrue(ok.accepted)
        before = self.memory.snapshot()
        bad = key.clone()
        bad[0] = float("nan")
        with self.assertRaises(Exception):
            # Non-finite inputs raise before mutate; ensure state unchanged.
            from neural.errors import NeuralNumericalInstability

            try:
                self.memory.write(bad, value)
            except NeuralNumericalInstability:
                raise
        # Even if write returns rejected, state must match prior good snapshot.
        # Non-finite raises, so restore path unused — compare equality of params.
        after = self.memory.snapshot()
        for name in ("slow", "fast"):
            for k in before[name]:
                self.assertTrue(self.torch.equal(before[name][k], after[name][k]))

    def test_failed_update_rolls_back(self) -> None:
        from neural.config import NeuralMemoryConfig

        # Force rejection via impossible delta bound after a tiny allowed step budget.
        tight = NeuralMemoryConfig(
            dim=16,
            hidden_dim=32,
            mode=self.NeuralMode.LEARN,
            seed=3,
            learning_rate=0.5,
            max_update_steps=20,
            loss_tolerance=0.01,
            max_parameter_delta_norm=1e-8,
            replay_enabled=False,
        )
        memory = self.NeuralMemory(tight)
        before = memory.snapshot()
        key = self.torch.randn(16)
        value = self.torch.randn(16)
        result = memory.write(key, value)
        self.assertFalse(result.accepted)
        self.assertTrue(result.rolled_back)
        self.assertGreaterEqual(memory.metrics().rollback_count, 1)
        after = memory.snapshot()
        for name in ("slow", "fast"):
            for k in before[name]:
                self.assertTrue(self.torch.allclose(before[name][k], after[name][k], atol=0, rtol=0))

    def test_reset_fast_memory(self) -> None:
        from neural.evals import make_association_pairs, train_pairs

        pairs = make_association_pairs(self.config.dim, 2, seed=21)
        train_pairs(self.memory, pairs)
        before_fast = {k: v.detach().clone() for k, v in self.memory.fast.state_dict().items()}
        # Fast should have moved for at least one tensor.
        moved = any(float(v.abs().sum()) > 0 for v in before_fast.values())
        self.assertTrue(moved)
        self.memory.reset_fast_memory()
        for v in self.memory.fast.state_dict().values():
            self.assertEqual(float(v.abs().sum()), 0.0)

    def test_determinism_within_tolerance(self) -> None:
        from neural.config import NeuralMemoryConfig
        from neural.evals import evaluate_recall, make_association_pairs, train_pairs

        pairs = make_association_pairs(16, 3, seed=42)

        def run_once() -> float:
            cfg = NeuralMemoryConfig(
                dim=16,
                hidden_dim=48,
                mode=self.NeuralMode.LEARN,
                seed=42,
                learning_rate=0.2,
                max_update_steps=60,
                loss_tolerance=0.08,
                replay_enabled=True,
                replay_batch_size=2,
            )
            mem = self.NeuralMemory(cfg)
            train_pairs(mem, pairs)
            return evaluate_recall(mem, pairs).mean_cosine

        a = run_once()
        b = run_once()
        # Documented tolerance: identical seed/config should match within 1e-4 cosine.
        self.assertAlmostEqual(a, b, delta=1e-4)


if __name__ == "__main__":
    unittest.main()
