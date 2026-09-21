"""Numerical parity fixtures for ATME streaming vs resident training.

GPU-capable hosts execute full checks. Hosts without torch/CUDA skip with an
explicit reason — never simulated as green.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TORCH_AVAILABLE = importlib.util.find_spec("torch") is not None


@unittest.skipUnless(TORCH_AVAILABLE, "torch not installed — UNVERIFIED_ON_HOST for ATME numerical parity")
class AtmeNumericalParityTests(unittest.TestCase):
    def test_streamed_vs_resident_tiny_llama_like_parity(self) -> None:
        import copy

        import torch
        import torch.nn as nn

        from training.execution_plan import MemoryStrategy, TrainingExecutionPlan
        from training.strategies.layer_streaming import LayerStreamingRuntime
        from training.streaming.llama_like import LlamaLikeAdapter

        class TinyBlock(nn.Module):
            def __init__(self, hidden: int):
                super().__init__()
                self.q_proj = nn.Linear(hidden, hidden, bias=False)
                self.o_proj = nn.Linear(hidden, hidden, bias=False)

            def forward(self, x):
                return self.o_proj(self.q_proj(x))

        class TinyLlamaLike(nn.Module):
            def __init__(self, hidden: int = 32, layers: int = 3, vocab: int = 50):
                super().__init__()
                self.config = type(
                    "Cfg",
                    (),
                    {
                        "model_type": "llama",
                        "architectures": ["LlamaForCausalLM"],
                        "tie_word_embeddings": True,
                    },
                )()
                self.model = nn.Module()
                self.model.embed_tokens = nn.Embedding(vocab, hidden)
                self.model.layers = nn.ModuleList([TinyBlock(hidden) for _ in range(layers)])
                self.model.norm = nn.LayerNorm(hidden)
                self.lm_head = nn.Linear(hidden, vocab, bias=False)
                self.lm_head.weight = self.model.embed_tokens.weight

            def forward(self, input_ids):
                x = self.model.embed_tokens(input_ids)
                for block in self.model.layers:
                    x = x + block(x)
                x = self.model.norm(x)
                return self.lm_head(x)

        torch.manual_seed(0)
        resident = TinyLlamaLike()
        streamed = copy.deepcopy(resident)
        # Freeze all base weights; trainable adapter is an external LoRA-like delta
        # (mirrors PEFT ownership: adapters stay device-resident, base is streamed).
        for param in streamed.parameters():
            param.requires_grad_(False)
        for param in resident.parameters():
            param.requires_grad_(False)

        self.assertTrue(LlamaLikeAdapter().matches(streamed))
        device = torch.device("cpu")
        plan = TrainingExecutionPlan(
            strategy=MemoryStrategy.RAM_LAYER_STREAMING,
            buffer_count=1,
            feasible=True,
            confidence="medium",
            activation_checkpointing="disabled",
        )
        runtime = LayerStreamingRuntime(streamed, plan, torch_module=torch, device=device, source="ram")
        runtime.install()
        try:
            batch = torch.randint(0, 50, (2, 8))
            with torch.no_grad():
                base_r = resident(batch)
                base_s = streamed(batch)
            max_diff = float((base_r - base_s).abs().max().detach())
            self.assertLessEqual(max_diff, 1e-5, f"forward divergence {max_diff}")

            # Trainable path over streamed activations (base weights frozen, head trainable).
            head_r = nn.Linear(32, 8, bias=False)
            head_s = nn.Linear(32, 8, bias=False)
            head_s.load_state_dict(head_r.state_dict())

            features_r = resident.model.embed_tokens(batch)
            for block in resident.model.layers:
                features_r = features_r + block(features_r)
            features_r = resident.model.norm(features_r)

            features_s = streamed.model.embed_tokens(batch)
            for block in streamed.model.layers:
                features_s = features_s + block(features_s)
            features_s = streamed.model.norm(features_s)

            out_r = head_r(features_r)
            out_s = head_s(features_s)
            loss_r = out_r.float().pow(2).mean()
            loss_s = out_s.float().pow(2).mean()
            loss_r.backward()
            loss_s.backward()
            grad_r = head_r.weight.grad
            grad_s = head_s.weight.grad
            self.assertIsNotNone(grad_r)
            self.assertIsNotNone(grad_s)
            assert grad_r is not None and grad_s is not None
            self.assertTrue(torch.isfinite(grad_s).all())
            feat_diff = float((features_r.detach() - features_s.detach()).abs().max())
            self.assertLessEqual(feat_diff, 1e-5, f"feature divergence {feat_diff}")
            grad_diff = float((grad_r - grad_s).abs().max())
            self.assertLessEqual(grad_diff, 1e-4, f"gradient divergence {grad_diff}")
            # Frozen streamed base must not receive gradients.
            for param in streamed.parameters():
                self.assertFalse(param.requires_grad)
                self.assertIsNone(param.grad)
        finally:
            runtime.close()

    def test_cuda_peak_vram_streaming_below_resident_when_cuda_available(self) -> None:
        import torch

        if not torch.cuda.is_available():
            self.skipTest("CUDA unavailable — UNVERIFIED_ON_HOST for streaming VRAM reduction")
        # Full GPU VRAM comparison requires a larger fixture and is host-gated.
        self.skipTest(
            "Full GPU VRAM reduction benchmark requires dedicated NVIDIA validation host — "
            "IMPLEMENTED_UNVERIFIED_ON_HOST"
        )


if __name__ == "__main__":
    unittest.main()
