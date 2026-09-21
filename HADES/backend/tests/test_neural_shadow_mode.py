"""Phase 3 mode-specific contracts for the experimental neural runtime."""

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


class NeuralShadowReadModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.torch = _torch_or_skip(self)
        from neural.contracts import NeuralMode
        from neural.runtime import NeuralModelRuntime
        from neural.toy_transformer import ToyTransformerConfig

        self.NeuralMode = NeuralMode
        self.rt = NeuralModelRuntime(
            toy_config=ToyTransformerConfig(seed=21, hidden_size=32, num_heads=4, num_layers=2),
            injection_layers=[0, 1],
            fusion_scale=0.0,
        )
        self.ids = self.torch.randint(0, 64, (1, 6))

    def test_shadow_records_per_injection_layer(self) -> None:
        self.rt.set_mode(self.NeuralMode.SHADOW)
        out = self.rt.forward(self.ids)
        layers = sorted(ev["layer"] for ev in out.fusion_events)
        self.assertEqual(layers, [0, 1])
        self.assertTrue(all(isinstance(ev.get("gate_mean"), float) for ev in out.fusion_events))

    def test_off_does_not_touch_memory_read_counters(self) -> None:
        before = self.rt.memory.metrics().read_count
        self.rt.set_mode(self.NeuralMode.OFF)
        self.rt.forward(self.ids)
        self.assertEqual(self.rt.memory.metrics().read_count, before)

    def test_main_still_does_not_import_runtime(self) -> None:
        main_path = Path(__file__).resolve().parents[1] / "main.py"
        text = main_path.read_text(encoding="utf-8")
        self.assertNotIn("neural.runtime", text)
        self.assertNotIn("NeuralModelRuntime", text)


if __name__ == "__main__":
    unittest.main()
