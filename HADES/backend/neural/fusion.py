"""Residual neural-memory fusion into Transformer hidden states.

Conservative first design:

    q = query_proj(h)
    m = memory_net(q)
    g = sigmoid(gate(h))
    h_new = h + scale * g * out_proj(m)

Safe initialization: ``scale`` defaults near zero and ``out_proj`` is zero-init
so an untrained READ path approximates OFF until memory is deliberately enabled.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from neural.deps import require_torch
from neural.errors import NeuralNumericalInstability


@dataclass
class FusionDiagnostics:
    applied: bool
    gate_mean: float | None = None
    gate_std: float | None = None
    memory_norm_mean: float | None = None
    residual_norm_mean: float | None = None
    scale: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "gate_mean": self.gate_mean,
            "gate_std": self.gate_std,
            "memory_norm_mean": self.memory_norm_mean,
            "residual_norm_mean": self.residual_norm_mean,
            "scale": self.scale,
        }


def build_residual_fusion(
    *,
    hidden_size: int,
    memory_dim: int,
    scale: float = 0.0,
    gate_bias: float = -4.0,
) -> Any:
    torch = require_torch()

    class ResidualMemoryFusion(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.hidden_size = int(hidden_size)
            self.memory_dim = int(memory_dim)
            self.scale = float(scale)
            self.query_proj = torch.nn.Linear(hidden_size, memory_dim, bias=False)
            self.gate = torch.nn.Linear(hidden_size, 1)
            self.out_proj = torch.nn.Linear(memory_dim, hidden_size, bias=False)
            # Safe init: near-closed gate + zero residual projection.
            torch.nn.init.zeros_(self.out_proj.weight)
            torch.nn.init.zeros_(self.gate.weight)
            torch.nn.init.constant_(self.gate.bias, float(gate_bias))

        def set_scale(self, value: float) -> None:
            self.scale = float(value)

        def forward(
            self,
            hidden: Any,
            memory_value: Any,
            *,
            apply: bool,
        ) -> tuple[Any, FusionDiagnostics]:
            if not apply:
                return hidden, FusionDiagnostics(applied=False, scale=self.scale)
            if hidden.shape[-1] != self.hidden_size:
                raise ValueError(
                    f"hidden last dim {hidden.shape[-1]} != fusion hidden_size {self.hidden_size}"
                )
            if memory_value.shape[-1] != self.memory_dim:
                raise ValueError(
                    f"memory last dim {memory_value.shape[-1]} != memory_dim {self.memory_dim}"
                )
            if not torch.isfinite(hidden).all() or not torch.isfinite(memory_value).all():
                raise NeuralNumericalInstability("non-finite fusion inputs")
            gate = torch.sigmoid(self.gate(hidden))
            residual = self.out_proj(memory_value)
            delta = self.scale * gate * residual
            if not torch.isfinite(delta).all():
                raise NeuralNumericalInstability("non-finite fusion residual")
            out = hidden + delta
            diag = FusionDiagnostics(
                applied=True,
                gate_mean=float(gate.mean().detach().item()),
                gate_std=float(gate.std(unbiased=False).detach().item()),
                memory_norm_mean=float(memory_value.norm(dim=-1).mean().detach().item()),
                residual_norm_mean=float(delta.norm(dim=-1).mean().detach().item()),
                scale=self.scale,
            )
            return out, diag

    return ResidualMemoryFusion()
