"""Configuration for Phase 1 neural associative memory."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from neural.contracts import NeuralMode


@dataclass(frozen=True)
class NeuralMemoryConfig:
    """Bounded configuration for the vector-level neural memory prototype.

    V2 defaults target the production embedding-backed architecture. Toy /
    research fixtures must pass explicit ``dim`` / ``architecture_version`` /
    ``schema_version`` (or use ``memory_config_for_encoder``).
    """

    dim: int = 32
    hidden_dim: int = 64
    slow_depth: int = 2
    fast_hidden_dim: int = 32
    fast_depth: int = 1
    mode: NeuralMode = NeuralMode.OFF
    seed: int = 0
    # Write safety
    learning_rate: float = 0.05
    max_learning_rate: float = 0.5
    max_update_steps: int = 64
    min_update_steps: int = 1
    max_grad_norm: float = 1.0
    max_parameter_delta_norm: float = 25.0
    loss_tolerance: float = 0.05
    # Replay
    replay_enabled: bool = True
    replay_batch_size: int = 4
    replay_buffer_limit: int = 256
    replay_loss_weight: float = 0.5
    # Regularization
    weight_decay: float = 1e-4
    # Numerical
    atol: float = 1e-5
    rtol: float = 1e-4
    # V2: embedding-dim production memory; toy fixtures override explicitly.
    architecture_version: str = "parametric_mlp_v2_embedding"
    schema_version: int = 2
    device: str = "cpu"
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.dim < 1:
            raise ValueError("dim must be >= 1")
        if self.hidden_dim < 1:
            raise ValueError("hidden_dim must be >= 1")
        if self.learning_rate <= 0 or self.learning_rate > self.max_learning_rate:
            raise ValueError("learning_rate must be in (0, max_learning_rate]")
        if self.max_update_steps < 1:
            raise ValueError("max_update_steps must be >= 1")
        if self.replay_batch_size < 0:
            raise ValueError("replay_batch_size must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["mode"] = self.mode.value
        return payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "NeuralMemoryConfig":
        data = dict(raw)
        mode = data.get("mode", NeuralMode.OFF)
        if isinstance(mode, str):
            data["mode"] = NeuralMode(mode)
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)
