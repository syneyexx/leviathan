"""Explicit Model Runtime selection (Phase 10).

Chooses Standard (LM Studio / existing chat_fn) vs Neural Runtime without
creating a second reasoning engine. Selection is auditable; fallbacks are
explicit. Default remains Standard + NeuralMode.OFF.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping


class RuntimeKind(str, Enum):
    STANDARD = "standard"
    NEURAL = "neural"


class NeuralRequirement(str, Enum):
    """How strongly the caller requires Neural Runtime.

    OFF — never select neural (conventional HADES).
    PREFERRED — try neural when mode/capability allow; else Standard + reason.
    REQUIRED — fail closed if neural cannot serve the request.
    """

    OFF = "off"
    PREFERRED = "preferred"
    REQUIRED = "required"


@dataclass(frozen=True)
class RuntimeSelectionRequest:
    neural_mode: str = "off"  # NeuralMode value; avoid hard import of neural package
    neural_requirement: NeuralRequirement = NeuralRequirement.OFF
    shadow_sample_rate: float = 0.0
    neural_available: bool = False
    neural_ready: bool = False
    allow_neural: bool = False  # explicit capability/config gate

    def __post_init__(self) -> None:
        rate = float(self.shadow_sample_rate)
        if rate < 0.0 or rate > 1.0:
            raise ValueError("shadow_sample_rate must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["neural_requirement"] = self.neural_requirement.value
        return payload

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> "RuntimeSelectionRequest":
        if not raw:
            return cls()
        req = raw.get("neural_requirement", NeuralRequirement.OFF)
        if isinstance(req, str):
            req = NeuralRequirement(req)
        return cls(
            neural_mode=str(raw.get("neural_mode") or "off"),
            neural_requirement=req,
            shadow_sample_rate=float(raw.get("shadow_sample_rate") or 0.0),
            neural_available=bool(raw.get("neural_available", False)),
            neural_ready=bool(raw.get("neural_ready", False)),
            allow_neural=bool(raw.get("allow_neural", False)),
        )


@dataclass
class RuntimeSelectionDecision:
    primary: RuntimeKind
    neural_mode: str
    shadow: bool
    fallback_reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary": self.primary.value,
            "neural_mode": self.neural_mode,
            "shadow": self.shadow,
            "fallback_reason": self.fallback_reason,
            "detail": dict(self.detail),
        }


def select_model_runtime(request: RuntimeSelectionRequest | Mapping[str, Any] | None) -> RuntimeSelectionDecision:
    """Pure policy: decide Standard vs Neural without performing inference."""
    req = (
        request
        if isinstance(request, RuntimeSelectionRequest)
        else RuntimeSelectionRequest.from_dict(request)
    )
    mode = (req.neural_mode or "off").strip().lower()
    if mode not in {"off", "shadow", "read", "learn"}:
        raise ValueError(f"unsupported neural_mode: {mode}")

    # Conventional HADES path.
    if req.neural_requirement is NeuralRequirement.OFF or mode == "off":
        return RuntimeSelectionDecision(
            primary=RuntimeKind.STANDARD,
            neural_mode="off",
            shadow=False,
            fallback_reason=None,
            detail={"policy": "neural_off"},
        )

    if mode == "learn":
        # LEARN remains high risk — never select as primary via gateway yet.
        return RuntimeSelectionDecision(
            primary=RuntimeKind.STANDARD,
            neural_mode="off",
            shadow=False,
            fallback_reason="neural_learn_unsupported",
            detail={
                "policy": "learn_rejected",
                "fail_closed": req.neural_requirement is NeuralRequirement.REQUIRED,
            },
        )

    if mode == "read":
        # F-06: READ must not replace LM output until real fusion exists.
        # Diagnostic neural infer returns a research string, not a fused answer.
        return RuntimeSelectionDecision(
            primary=RuntimeKind.STANDARD,
            neural_mode="off",
            shadow=False,
            fallback_reason="neural_read_not_product_ready",
            detail={
                "policy": "read_rejected_no_fusion",
                "research_only": True,
                "not_product_ready": True,
                "fail_closed": req.neural_requirement is NeuralRequirement.REQUIRED,
            },
        )

    capable = bool(req.allow_neural and req.neural_available and req.neural_ready)

    if mode == "shadow":
        # Primary remains Standard; optional neural diagnostics.
        if not capable and req.neural_requirement is NeuralRequirement.REQUIRED:
            return RuntimeSelectionDecision(
                primary=RuntimeKind.STANDARD,
                neural_mode="off",
                shadow=False,
                fallback_reason="neural_runtime_unavailable",
                detail={"policy": "shadow_required_but_unavailable", "fail_closed": True},
            )
        shadow = capable and req.shadow_sample_rate > 0.0
        return RuntimeSelectionDecision(
            primary=RuntimeKind.STANDARD,
            neural_mode="shadow" if capable else "off",
            shadow=shadow,
            fallback_reason=None if capable else "neural_runtime_unavailable",
            detail={"policy": "shadow_secondary", "capable": capable},
        )

    # Unknown mode → Standard fail-safe.
    return RuntimeSelectionDecision(
        primary=RuntimeKind.STANDARD,
        neural_mode="off",
        shadow=False,
        fallback_reason="neural_mode_unsupported",
        detail={"policy": "unknown_mode_fallback", "mode": mode},
    )


def should_fail_closed(decision: RuntimeSelectionDecision) -> bool:
    if not decision.detail.get("fail_closed"):
        return False
    return decision.fallback_reason in {
        "neural_runtime_unavailable",
        "neural_learn_unsupported",
        "neural_read_not_product_ready",
    }
