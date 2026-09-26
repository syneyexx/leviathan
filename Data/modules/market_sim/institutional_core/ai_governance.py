"""W54 — LLM / AI governance without duplicating MCP ownership.

Does not create McpBridge, ModelControlPlane, or prompt assemblers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, DEFAULT_TRUTH


ALLOWED_AUTONOMY_CEILING = "A4"  # live is never a level


@dataclass(frozen=True)
class LlmUseCase:
    use_case_id: str
    purpose: str
    human_in_the_loop: bool
    can_place_orders: bool = False
    can_loosen_limits: bool = False
    can_enable_live: bool = False
    max_tokens: int = 24_000

    def public_dict(self) -> dict[str, Any]:
        return {
            "useCaseId": self.use_case_id,
            "purpose": self.purpose,
            "humanInTheLoop": self.human_in_the_loop,
            "canPlaceOrders": self.can_place_orders,
            "canLoosenLimits": self.can_loosen_limits,
            "canEnableLive": False,  # hard override
            "maxTokens": self.max_tokens,
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "does_not_own_mcp": True,
                "does_not_duplicate_model_control_plane": True,
            },
        }


@dataclass
class AiGovernanceDecision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    redactions: list[str] = field(default_factory=list)
    status: str = MeasurementState.OBSERVED.value

    def public_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reasons": list(self.reasons),
            "redactions": list(self.redactions),
            "status": self.status,
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "llm_output_is_not_authority": True,
            },
        }


SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apiKey",
        "secret",
        "password",
        "token",
        "authorization",
        "private_key",
        "privateKey",
    }
)


def redact_mapping(payload: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    redacted: dict[str, Any] = {}
    found: list[str] = []
    for key, value in payload.items():
        if key in SENSITIVE_KEYS or any(s in key.lower() for s in ("secret", "password", "token", "api_key")):
            redacted[key] = "***REDACTED***"
            found.append(key)
        elif isinstance(value, Mapping):
            child, child_found = redact_mapping(value)
            redacted[key] = child
            found.extend(f"{key}.{c}" for c in child_found)
        else:
            redacted[key] = value
    return redacted, found


def evaluate_llm_action(
    use_case: LlmUseCase | Mapping[str, Any],
    *,
    action: str,
    autonomy_level: str = "A0",
    payload: Mapping[str, Any] | None = None,
) -> AiGovernanceDecision:
    if isinstance(use_case, Mapping):
        use_case = LlmUseCase(
            use_case_id=str(use_case.get("use_case_id") or use_case.get("useCaseId") or ""),
            purpose=str(use_case.get("purpose") or ""),
            human_in_the_loop=bool(use_case.get("human_in_the_loop", use_case.get("humanInTheLoop", True))),
            can_place_orders=bool(use_case.get("can_place_orders", use_case.get("canPlaceOrders", False))),
            can_loosen_limits=bool(use_case.get("can_loosen_limits", use_case.get("canLoosenLimits", False))),
            can_enable_live=False,
            max_tokens=int(use_case.get("max_tokens") or use_case.get("maxTokens") or 24_000),
        )

    reasons: list[str] = []
    action_u = str(action).upper()
    level = str(autonomy_level).upper()

    if action_u in {"ENABLE_LIVE", "LIVE_ORDER", "UNLOCK_LIVE"}:
        reasons.append("live_trading_BLOCKED")
        _, redactions = redact_mapping(payload or {})
        return AiGovernanceDecision(allowed=False, reasons=reasons, redactions=redactions)

    if action_u in {"PLACE_ORDER", "ORDER_INTENT"} and not use_case.can_place_orders:
        reasons.append("use_case_cannot_place_orders")

    if action_u in {"LOOSEN_LIMITS", "RAISE_LIMIT"} and not use_case.can_loosen_limits:
        reasons.append("use_case_cannot_loosen_limits")

    if level > ALLOWED_AUTONOMY_CEILING or level.startswith("A5"):
        reasons.append("autonomy_ceiling_exceeded")

    if not use_case.human_in_the_loop and action_u in {"PLACE_ORDER", "LOOSEN_LIMITS", "PROMOTE_MODEL"}:
        reasons.append("human_in_the_loop_required")

    redacted_payload, redactions = redact_mapping(payload or {})
    _ = redacted_payload
    return AiGovernanceDecision(allowed=not reasons, reasons=reasons, redactions=redactions)


def governance_inventory(use_cases: Sequence[LlmUseCase]) -> dict[str, Any]:
    return {
        "useCases": [u.public_dict() for u in use_cases],
        "mcpOwner": "modules.mcp / McpBridge",
        "modelControlPlaneOwner": "modules.models / ModelControlPlane",
        "thisModule": "market_sim.institutional_core.ai_governance",
        "truth": {
            **DEFAULT_TRUTH.public_dict(),
            "no_mcp_duplicate": True,
            "no_model_control_plane_duplicate": True,
        },
    }
