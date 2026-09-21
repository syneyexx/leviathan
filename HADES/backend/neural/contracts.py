"""Typed contracts for HADES Neural Memory (Phase 1)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, runtime_checkable


class NeuralMode(str, Enum):
    """Explicit neural subsystem modes.

    OFF bypasses the subsystem completely (default).
    SHADOW may compute diagnostics without mutating generation.
    READ may influence hidden states (later phases).
    LEARN may perform controlled online writes (disabled experimentally).
    """

    OFF = "off"
    SHADOW = "shadow"
    READ = "read"
    LEARN = "learn"


@dataclass(frozen=True)
class NeuralMemoryMetrics:
    association_count: int = 0
    write_count: int = 0
    read_count: int = 0
    rollback_count: int = 0
    last_write_loss: float | None = None
    last_write_latency_ms: float | None = None
    last_read_latency_ms: float | None = None
    parameter_count: int = 0
    parameter_delta_norm: float | None = None
    fast_parameter_count: int = 0
    slow_parameter_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AssociationSample:
    """Vector key → value pair for Phase 1 associative training."""

    key: Any  # torch.Tensor when torch is available
    value: Any
    sample_id: str = ""


@dataclass
class WriteResult:
    accepted: bool
    steps: int = 0
    final_loss: float | None = None
    parameter_delta_norm: float | None = None
    latency_ms: float = 0.0
    rolled_back: bool = False
    reason: str | None = None
    replay_count: int = 0


@dataclass
class ReadResult:
    value: Any
    latency_ms: float = 0.0
    mode: NeuralMode = NeuralMode.OFF
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CheckpointMeta:
    schema_version: int
    architecture_version: str
    dim: int
    hidden_dim: int
    created_at: str
    parent_checkpoint: str | None
    integrity_hash: str
    metrics: Mapping[str, Any]
    dtype: str
    config: Mapping[str, Any]


@runtime_checkable
class NeuralMemoryContract(Protocol):
    def write(self, key: Any, value: Any, *, sample_id: str = "") -> WriteResult: ...

    def read(self, query: Any) -> ReadResult: ...

    def snapshot(self) -> dict[str, Any]: ...

    def restore(self, state: Mapping[str, Any]) -> None: ...

    def reset_fast_memory(self) -> None: ...

    def consolidate(self, **kwargs: Any) -> dict[str, Any]: ...

    def metrics(self) -> NeuralMemoryMetrics: ...


# --- Phase 9 Neural Runtime boundary contracts ---

NEURAL_RUNTIME_PROTOCOL_VERSION = 1


class NeuralRuntimeState(str, Enum):
    """Lifecycle states for the Neural Runtime boundary.

    ``ready`` means inference readiness, not merely that a process exists.
    """

    STOPPED = "stopped"
    STARTING = "starting"
    LOADING = "loading"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"
    STOPPING = "stopping"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class NeuralRuntimeIdentity:
    protocol_version: int
    base_model_id: str
    base_model_fingerprint: str
    tokenizer_id: str | None
    neural_architecture_version: str
    adapter_checkpoint_id: str | None
    slow_memory_checkpoint_id: str | None
    fast_memory_state_id: str | None
    injection_layers: tuple[int, ...]
    fusion_scale: float
    dtype: str
    quantization: str | None
    hidden_size: int
    num_layers: int
    mode: NeuralMode

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["mode"] = self.mode.value
        payload["injection_layers"] = list(self.injection_layers)
        return payload


@dataclass
class NeuralRuntimeHealth:
    state: NeuralRuntimeState
    process_alive: bool
    runtime_initialized: bool
    base_model_loaded: bool
    memory_loaded: bool
    adapter_loaded: bool
    cuda_available: bool
    gpu_oom_state: bool
    last_inference_success: bool | None
    last_error: dict[str, Any] | None
    checkpoint_compatible: bool | None
    isolation: str
    identity: NeuralRuntimeIdentity | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "process_alive": self.process_alive,
            "runtime_initialized": self.runtime_initialized,
            "base_model_loaded": self.base_model_loaded,
            "memory_loaded": self.memory_loaded,
            "adapter_loaded": self.adapter_loaded,
            "cuda_available": self.cuda_available,
            "gpu_oom_state": self.gpu_oom_state,
            "last_inference_success": self.last_inference_success,
            "last_error": dict(self.last_error) if self.last_error else None,
            "checkpoint_compatible": self.checkpoint_compatible,
            "isolation": self.isolation,
            "identity": self.identity.to_dict() if self.identity else None,
        }


@dataclass
class NeuralRuntimeMetrics:
    model_load_ms: float | None = None
    checkpoint_load_ms: float | None = None
    first_token_latency_ms: float | None = None
    total_inference_latency_ms: float | None = None
    neural_memory_read_latency_ms: float | None = None
    fusion_overhead_ms: float | None = None
    vram_allocated_bytes: int | None = None
    vram_reserved_bytes: int | None = None
    peak_vram_bytes: int | None = None
    ram_usage_bytes: int | None = None
    tokens_generated: int | None = None
    inference_count: int = 0
    cancel_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NeuralModelSpec:
    """Toy / research model load specification (no remote downloads)."""

    model_id: str = "toy_causal_v1"
    vocab_size: int = 48
    hidden_size: int = 32
    num_layers: int = 2
    num_heads: int = 4
    intermediate_size: int = 64
    max_seq_len: int = 16
    seed: int = 11
    tokenizer_id: str | None = "toy_tokenizer_v1"
    dtype: str = "float32"
    quantization: str | None = None
    injection_layers: tuple[int, ...] = (1,)
    fusion_scale: float = 0.0
    device: str = "cpu"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["injection_layers"] = list(self.injection_layers)
        return payload

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "NeuralModelSpec":
        data = dict(raw)
        layers = data.get("injection_layers", (1,))
        data["injection_layers"] = tuple(int(x) for x in layers)
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class NeuralInferRequest:
    request_id: str
    input_ids: list[list[int]]
    mode: NeuralMode = NeuralMode.OFF

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "input_ids": self.input_ids,
            "mode": self.mode.value,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "NeuralInferRequest":
        mode = raw.get("mode", NeuralMode.OFF)
        if isinstance(mode, str):
            mode = NeuralMode(mode)
        return cls(
            request_id=str(raw["request_id"]),
            input_ids=[list(row) for row in raw["input_ids"]],
            mode=mode,
        )


@dataclass
class NeuralInferResult:
    request_id: str
    mode: NeuralMode
    logits: Any
    bypassed: bool
    base_checksum: str
    fusion_events: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: float = 0.0
    cancelled: bool = False

    def to_dict(self, *, include_logits: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "request_id": self.request_id,
            "mode": self.mode.value,
            "bypassed": self.bypassed,
            "base_checksum": self.base_checksum,
            "fusion_events": list(self.fusion_events),
            "latency_ms": self.latency_ms,
            "cancelled": self.cancelled,
        }
        if include_logits:
            payload["logits"] = self.logits
        return payload
