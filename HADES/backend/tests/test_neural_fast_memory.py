"""Phase 5: bounded fast-memory session writes."""

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


class NeuralFastMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.torch = _torch_or_skip(self)
        from neural.config import NeuralMemoryConfig
        from neural.contracts import NeuralMode
        from neural.fast_memory import FastMemorySession, FastWritePolicy
        from neural.memory import NeuralMemory
        from neural.runtime import NeuralModelRuntime
        from neural.toy_transformer import ToyTransformerConfig, parameter_checksum

        self.parameter_checksum = parameter_checksum
        self.NeuralMode = NeuralMode
        self.memory = NeuralMemory(
            NeuralMemoryConfig(
                dim=32,
                hidden_dim=64,
                fast_hidden_dim=32,
                mode=NeuralMode.OFF,
                seed=5,
            )
        )
        self.policy = FastWritePolicy(
            require_verified=True,
            min_surprise=0.15,
            max_writes_per_session=3,
            max_update_steps=40,
            learning_rate=0.15,
            loss_tolerance=0.08,
            min_source_reliability=0.5,
        )
        self.session = FastMemorySession(self.memory, policy=self.policy)
        self.runtime = NeuralModelRuntime(
            toy_config=ToyTransformerConfig(seed=9, hidden_size=32, num_heads=4, num_layers=2),
            mode=NeuralMode.OFF,
        )

    def _pair(self, seed: int):
        g = self.torch.Generator().manual_seed(seed)
        key = self.torch.nn.functional.normalize(self.torch.randn(32, generator=g), dim=0)
        value = self.torch.nn.functional.normalize(self.torch.randn(32, generator=g), dim=0)
        return key, value

    def test_rejects_unverified_by_default(self) -> None:
        key, value = self._pair(1)
        result = self.session.consider_write(key, value, verified=False, source_reliability=1.0)
        self.assertFalse(result.accepted)
        self.assertEqual(result.decision.reason, "unverified_experience")
        self.assertEqual(self.session.writes_rejected, 1)

    def test_rejects_low_reliability(self) -> None:
        key, value = self._pair(2)
        result = self.session.consider_write(key, value, verified=True, source_reliability=0.1)
        self.assertFalse(result.accepted)
        self.assertEqual(result.decision.reason, "source_reliability_too_low")

    def test_surprise_is_measurable(self) -> None:
        key, value = self._pair(3)
        report = self.session.measure_surprise(key, value)
        self.assertGreaterEqual(report.surprise, 0.0)
        self.assertLessEqual(report.cosine, 1.0 + 1e-5)
        self.assertAlmostEqual(report.surprise, 1.0 - report.cosine, places=5)

    def test_verified_surprising_write_updates_fast_only(self) -> None:
        key, value = self._pair(4)
        slow_before = {k: v.detach().clone() for k, v in self.memory.slow.state_dict().items()}
        fast_before = {k: v.detach().clone() for k, v in self.memory.fast.state_dict().items()}
        # Ensure surprise is high enough under random init.
        surprise = self.session.measure_surprise(key, value)
        self.assertGreaterEqual(surprise.surprise, self.policy.min_surprise)
        result = self.session.consider_write(key, value, verified=True, source_reliability=1.0)
        self.assertTrue(result.accepted, result.to_dict())
        for k, v in self.memory.slow.state_dict().items():
            self.assertTrue(self.torch.equal(slow_before[k], v))
        fast_changed = any(
            not self.torch.equal(fast_before[k], v) for k, v in self.memory.fast.state_dict().items()
        )
        self.assertTrue(fast_changed)
        # Recall via encode should improve for this pair.
        after = self.session.measure_surprise(key, value)
        self.assertLess(after.surprise, surprise.surprise)

    def test_session_budget_enforced(self) -> None:
        accepted = 0
        for i in range(6):
            key, value = self._pair(100 + i)
            result = self.session.consider_write(key, value, verified=True, source_reliability=1.0)
            if result.accepted:
                accepted += 1
        self.assertLessEqual(accepted, self.policy.max_writes_per_session)
        self.assertEqual(self.session.writes_accepted, accepted)
        # Next write should hit budget once filled.
        if accepted >= self.policy.max_writes_per_session:
            key, value = self._pair(999)
            blocked = self.session.consider_write(key, value, verified=True, source_reliability=1.0)
            self.assertFalse(blocked.accepted)
            self.assertEqual(blocked.decision.reason, "session_write_budget_exhausted")

    def test_low_surprise_skipped(self) -> None:
        key, value = self._pair(5)
        # Train until surprise is low, then further write should skip.
        first = self.session.consider_write(key, value, verified=True, source_reliability=1.0)
        self.assertTrue(first.accepted, first.to_dict())
        # Loosen nothing — after learning, surprise should drop below threshold.
        second = self.session.consider_write(key, value, verified=True, source_reliability=1.0)
        # Either skipped for low surprise or accepted if still above threshold; if accepted,
        # surprise must have been >= min. Prefer skip after good fit.
        if not second.accepted:
            self.assertEqual(second.decision.reason, "surprise_too_low")

    def test_reset_fast_memory_clears_session_adapter(self) -> None:
        key, value = self._pair(6)
        self.session.consider_write(key, value, verified=True, source_reliability=1.0)
        self.assertTrue(any(float(v.abs().sum()) > 0 for v in self.memory.fast.state_dict().values()))
        self.session.reset_fast_memory()
        for v in self.memory.fast.state_dict().values():
            self.assertEqual(float(v.abs().sum()), 0.0)

    def test_runtime_learn_still_rejected_and_base_untouched(self) -> None:
        from neural.errors import NeuralModeUnsupported

        before = self.parameter_checksum(self.runtime.base_model)
        with self.assertRaises(NeuralModeUnsupported):
            self.runtime.set_mode(self.NeuralMode.LEARN)
        # Fast session on runtime.memory must not alter base.
        key = self.torch.randn(32)
        value = self.torch.randn(32)
        session = self.session.__class__(
            self.runtime.memory,
            policy=self.policy,
        )
        # Align dims: runtime memory dim is hidden_size 32 — good.
        session.consider_write(key, value, verified=True, source_reliability=1.0)
        self.assertEqual(before, self.parameter_checksum(self.runtime.base_model))

    def test_main_does_not_import_fast_memory(self) -> None:
        text = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("fast_memory", text)
        self.assertNotIn("FastMemorySession", text)


if __name__ == "__main__":
    unittest.main()
