"""Phase 3: frozen toy Transformer + residual neural-memory fusion."""

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


class NeuralModelBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.torch = _torch_or_skip(self)
        from neural.contracts import NeuralMode
        from neural.runtime import NeuralModelRuntime
        from neural.toy_transformer import ToyTransformerConfig

        self.NeuralMode = NeuralMode
        self.runtime = NeuralModelRuntime(
            toy_config=ToyTransformerConfig(
                vocab_size=48,
                hidden_size=32,
                num_layers=2,
                num_heads=4,
                intermediate_size=64,
                max_seq_len=16,
                seed=11,
            ),
            mode=NeuralMode.OFF,
            fusion_scale=0.0,
            injection_layers=[1],
        )
        self.ids = self.torch.randint(0, 48, (2, 8))

    def test_off_hard_bypass_matches_bare_backbone(self) -> None:
        from neural.toy_transformer import build_toy_causal_lm, freeze_module

        bare, _ = build_toy_causal_lm(self.runtime.toy_config)
        bare.load_state_dict(self.runtime.base_model.state_dict())
        freeze_module(bare)
        with self.torch.no_grad():
            expected = bare(self.ids)
        self.runtime.set_mode(self.NeuralMode.OFF)
        result = self.runtime.forward(self.ids)
        self.assertTrue(result.bypassed)
        self.assertEqual(result.fusion_events, [])
        self.assertTrue(self.torch.equal(result.logits, expected))

    def test_off_equivalence_is_deterministic(self) -> None:
        self.runtime.set_mode(self.NeuralMode.OFF)
        a = self.runtime.forward(self.ids).logits
        b = self.runtime.forward(self.ids).logits
        self.assertTrue(self.torch.equal(a, b))

    def test_shadow_matches_off_logits_but_emits_diagnostics(self) -> None:
        self.runtime.set_mode(self.NeuralMode.OFF)
        off = self.runtime.forward(self.ids)
        self.runtime.set_mode(self.NeuralMode.SHADOW)
        # Even with non-zero scale, SHADOW must not mutate outputs.
        self.runtime.set_fusion_scale(1.0)
        with self.torch.no_grad():
            self.runtime.fusion.out_proj.weight.copy_(0.25 * self.torch.eye(32))
        shadow = self.runtime.forward(self.ids)
        self.assertFalse(shadow.bypassed)
        self.assertTrue(shadow.fusion_events)
        self.assertTrue(all(ev.get("applied") for ev in shadow.fusion_events))
        self.assertTrue(all(ev.get("mutate") is False for ev in shadow.fusion_events))
        self.assertTrue(self.torch.equal(off.logits, shadow.logits))

    def test_read_safe_init_matches_off(self) -> None:
        # Zero scale + zero out_proj => READ ≈ OFF.
        self.runtime.set_fusion_scale(0.0)
        self.runtime.set_mode(self.NeuralMode.OFF)
        off = self.runtime.forward(self.ids).logits
        self.runtime.set_mode(self.NeuralMode.READ)
        read = self.runtime.forward(self.ids)
        self.assertTrue(read.fusion_events)
        self.assertTrue(self.torch.allclose(off, read.logits, atol=0, rtol=0))

    def test_read_can_influence_logits_when_enabled(self) -> None:
        self.runtime.set_mode(self.NeuralMode.OFF)
        off = self.runtime.forward(self.ids).logits
        self.runtime.set_fusion_scale(1.0)
        with self.torch.no_grad():
            self.runtime.fusion.out_proj.weight.copy_(0.5 * self.torch.eye(32))
        self.runtime.set_mode(self.NeuralMode.READ)
        read = self.runtime.forward(self.ids)
        self.assertTrue(read.fusion_events)
        self.assertTrue(all(ev.get("mutate") is True for ev in read.fusion_events))
        self.assertFalse(self.torch.allclose(off, read.logits, atol=1e-6, rtol=1e-5))

    def test_base_model_remains_frozen_after_memory_write(self) -> None:
        before = self.runtime.verify_base_frozen()
        key = self.torch.randn(32)
        value = self.torch.randn(32)
        self.runtime.memory.set_mode(self.NeuralMode.LEARN)
        result = self.runtime.memory.write(key, value)
        self.assertTrue(result.accepted, result)
        after = self.runtime.verify_base_frozen()
        self.assertEqual(before, after)
        # Memory params may change; base must not.
        for p in self.runtime.base_model.parameters():
            self.assertFalse(p.requires_grad)

    def test_learn_mode_rejected_on_runtime(self) -> None:
        from neural.errors import NeuralModeUnsupported

        with self.assertRaises(NeuralModeUnsupported):
            self.runtime.set_mode(self.NeuralMode.LEARN)

    def test_checkpoint_compatibility_fingerprint(self) -> None:
        from neural.errors import NeuralCheckpointIncompatible
        from neural.runtime import NeuralModelRuntime
        from neural.toy_transformer import ToyTransformerConfig

        fp = self.runtime.compatibility_fingerprint()
        other = NeuralModelRuntime(
            toy_config=ToyTransformerConfig(
                vocab_size=48,
                hidden_size=16,  # incompatible
                num_layers=2,
                num_heads=4,
                intermediate_size=32,
                max_seq_len=16,
                seed=11,
            ),
            mode=self.NeuralMode.OFF,
        )
        other_fp = other.compatibility_fingerprint()
        self.assertNotEqual(fp["hidden_size"], other_fp["hidden_size"])
        # Explicit compatibility gate used by future checkpoint loads.
        if fp["hidden_size"] != other_fp["hidden_size"] or fp["family"] != other_fp["family"]:
            raised = NeuralCheckpointIncompatible(
                "runtime incompatible",
                detail={"expected": fp, "got": other_fp},
            )
            self.assertEqual(raised.code, "neural_checkpoint_incompatible")
        else:  # pragma: no cover
            self.fail("expected incompatible geometries")

    def test_injection_layer_validation(self) -> None:
        with self.assertRaises(ValueError):
            self.runtime.adapter.resolve_layers([99])


class NeuralBaseModelFrozenTests(unittest.TestCase):
    def test_freeze_helpers(self) -> None:
        torch = _torch_or_skip(self)
        from neural.toy_transformer import (
            assert_module_frozen,
            build_toy_causal_lm,
            freeze_module,
            parameter_checksum,
            ToyTransformerConfig,
        )

        model, _ = build_toy_causal_lm(ToyTransformerConfig(seed=3, hidden_size=16, num_heads=4, num_layers=1))
        freeze_module(model)
        assert_module_frozen(model)
        a = parameter_checksum(model)
        with torch.no_grad():
            for p in model.parameters():
                p.add_(0.0)  # no-op
        self.assertEqual(a, parameter_checksum(model))
        with torch.no_grad():
            next(model.parameters()).add_(1.0)
        self.assertNotEqual(a, parameter_checksum(model))


if __name__ == "__main__":
    unittest.main()
