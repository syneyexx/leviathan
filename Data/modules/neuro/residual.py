from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class ResidualHookPoint:
    layer_index: int
    name: str
    site: str = "post_attn"  # post_attn | post_mlp | block_out

    def public_dict(self) -> dict[str, Any]:
        return {
            "layer_index": self.layer_index,
            "name": self.name,
            "site": self.site,
        }


@dataclass(frozen=True)
class ResidualReadRequest:
    hook: ResidualHookPoint
    token_span: tuple[int, int] | None = None
    run_id: str | None = None


@dataclass(frozen=True)
class ResidualTensorRef:
    """Opaque residual reference — never fabricates production tensor bytes as evidence."""

    hook: ResidualHookPoint
    dtype: str
    shape: tuple[int, ...]
    available: bool
    note: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "hook": self.hook.public_dict(),
            "dtype": self.dtype,
            "shape": list(self.shape),
            "available": self.available,
            "note": self.note,
            "metadata": self.metadata,
            "truth": {"tensor_bytes_not_fabricated_as_evidence": True},
        }


@dataclass(frozen=True)
class ResidualInjectRequest:
    hook: ResidualHookPoint
    mode: str  # ADDITIVE | GATED | REPLACE_SLICE | DISABLED
    scale: float = 0.0
    source: str = "neuro.memory"
    payload_ref: str | None = None  # id into working memory / artifact — not raw weights in API
    run_id: str | None = None


@dataclass(frozen=True)
class ResidualInjectReceipt:
    """Honest inject receipt. applied=False is never success."""

    implemented: bool
    mode: str
    hook: ResidualHookPoint
    applied: bool
    detail: str
    reason: str = ""
    degraded_to_chat_completions: bool = False

    def __post_init__(self) -> None:
        if not self.reason:
            object.__setattr__(self, "reason", self.detail)

    def public_dict(self) -> dict[str, Any]:
        return {
            "implemented": self.implemented,
            "mode": self.mode,
            "hook": self.hook.public_dict(),
            "applied": self.applied,
            "detail": self.detail,
            "reason": self.reason or self.detail,
            "degraded_to_chat_completions": self.degraded_to_chat_completions,
            "truth": {
                "neural_signal_is_not_authority": True,
                "residual_injection_is_not_authority": True,
                "residual_implemented": bool(self.implemented),
                "residual_applied": bool(self.applied),
                "unapplied_is_not_success": True,
                "unsupported_is_not_failure_of_core": True,
                "streaming_degraded": False,
            },
        }


@dataclass(frozen=True)
class ResidualForwardRequest:
    messages: list[dict[str, str]]
    engage_cortex: bool = False
    critic_rounds: int = 0
    inject: tuple[ResidualInjectRequest, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResidualForwardResult:
    implemented: bool
    text: str | None
    degraded_to_chat_completions: bool
    detail: str
    receipts: tuple[ResidualInjectReceipt, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.reason:
            object.__setattr__(self, "reason", self.detail)

    def public_dict(self) -> dict[str, Any]:
        return {
            "implemented": self.implemented,
            "text": self.text,
            "degraded_to_chat_completions": self.degraded_to_chat_completions,
            "detail": self.detail,
            "reason": self.reason or self.detail,
            "receipts": [item.public_dict() for item in self.receipts],
            "metadata": self.metadata,
            "truth": {
                "model_output_is_not_evidence": True,
                "neural_signal_is_not_authority": True,
                "residual_implemented": bool(self.implemented),
                "residual_applied": any(r.applied for r in self.receipts),
                "unapplied_is_not_success": True,
                "unsupported_is_not_failure_of_core": True,
                "streaming_degraded": bool(
                    (self.metadata or {}).get("streaming_degraded", False)
                ),
            },
        }


@runtime_checkable
class ResidualStreamPort(Protocol):
    def supports_residuals(self) -> bool: ...

    def list_hook_points(self) -> Sequence[ResidualHookPoint]: ...

    def read(self, request: ResidualReadRequest) -> ResidualTensorRef: ...

    def inject(self, request: ResidualInjectRequest) -> ResidualInjectReceipt: ...

    def run_forward(self, request: ResidualForwardRequest) -> ResidualForwardResult: ...


class UnsupportedResidualRuntime:
    """Honest null adapter for OpenAI-compatible servers without residual hooks."""

    protocol_version = "1.0"

    def supports_residuals(self) -> bool:
        return False

    def supports_streaming_forward(self) -> bool:
        return False

    def runtime_info(self) -> dict[str, Any]:
        return {
            "kind": "unsupported",
            "protocol_version": self.protocol_version,
            "production_grade": False,
            "available": False,
            "supports_streaming_forward": False,
            "truth": {
                "residual_injection_is_not_authority": True,
                "unsupported_is_not_failure_of_core": True,
            },
        }

    def list_hook_points(self) -> Sequence[ResidualHookPoint]:
        return ()

    def read(self, request: ResidualReadRequest) -> ResidualTensorRef:
        return ResidualTensorRef(
            hook=request.hook,
            dtype="none",
            shape=(),
            available=False,
            note="Active model runtime does not expose residual stream hooks",
            metadata=self.runtime_info(),
        )

    def inject(self, request: ResidualInjectRequest) -> ResidualInjectReceipt:
        return ResidualInjectReceipt(
            implemented=False,
            mode=request.mode,
            hook=request.hook,
            applied=False,
            detail="Residual injection unavailable — UnsupportedResidualRuntime",
            reason="unsupported_runtime",
            degraded_to_chat_completions=True,
        )

    def run_forward(self, request: ResidualForwardRequest) -> ResidualForwardResult:
        receipts = tuple(self.inject(item) for item in request.inject)
        return ResidualForwardResult(
            implemented=False,
            text=None,
            degraded_to_chat_completions=True,
            detail="No residual-capable runtime wired; caller must use chat completions",
            reason="unsupported_runtime",
            receipts=receipts,
            metadata=self.runtime_info(),
        )
