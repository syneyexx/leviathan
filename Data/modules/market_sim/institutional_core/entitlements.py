"""W56 — Entitlements: maker-checker + segregation of duties helpers.

Backend-enforceable pure helpers — cannot_approve_own_change; limit loosening
requires stronger authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, DEFAULT_TRUTH


# Higher number = stronger authority.
AUTHORITY_RANK: dict[str, int] = {
    "viewer": 10,
    "operator": 20,
    "trader": 30,
    "risk_officer": 40,
    "compliance": 50,
    "admin": 60,
    "security_admin": 70,
}


@dataclass(frozen=True)
class ChangeRequest:
    change_id: str
    kind: str  # LIMIT_LOOSEN | LIMIT_TIGHTEN | ROLE_GRANT | CONFIG | PROMOTE
    maker_id: str
    payload: dict[str, Any]
    required_authority: str = "risk_officer"

    def public_dict(self) -> dict[str, Any]:
        return {
            "changeId": self.change_id,
            "kind": self.kind,
            "makerId": self.maker_id,
            "payload": dict(self.payload),
            "requiredAuthority": self.required_authority,
        }


@dataclass
class ApprovalDecision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    status: str = MeasurementState.OBSERVED.value

    def public_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reasons": list(self.reasons),
            "status": self.status,
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "maker_checker_required": True,
            },
        }


def authority_rank(role: str) -> int:
    return AUTHORITY_RANK.get(str(role).lower(), 0)


def cannot_approve_own_change(*, maker_id: str, checker_id: str) -> bool:
    """Return True when checker is blocked (same identity)."""
    return str(maker_id).strip().lower() == str(checker_id).strip().lower()


def required_authority_for_change(kind: str, payload: Mapping[str, Any] | None = None) -> str:
    """Loosening limits requires stronger authority than tightening."""
    kind_u = str(kind).upper()
    payload = payload or {}
    if kind_u in {"LIMIT_LOOSEN", "RAISE_LIMIT", "ENABLE_SHORT", "RAISE_GROSS"}:
        return "risk_officer"
    if kind_u in {"ROLE_GRANT", "SECURITY"}:
        return "security_admin"
    if kind_u in {"PROMOTE", "CHAMPION"}:
        return "admin"
    if kind_u in {"LIMIT_TIGHTEN", "LOWER_LIMIT"}:
        return "operator"
    # Detect loosen via payload deltas.
    for key in ("max_gross_exposure_pct", "maxGrossExposurePct", "max_orders_per_day", "maxOrdersPerDay"):
        if key in payload and payload.get("direction") == "loosen":
            return "risk_officer"
    return "operator"


def evaluate_approval(
    change: ChangeRequest | Mapping[str, Any],
    *,
    checker_id: str,
    checker_roles: Sequence[str],
) -> ApprovalDecision:
    if isinstance(change, Mapping):
        change = ChangeRequest(
            change_id=str(change.get("change_id") or change.get("changeId") or ""),
            kind=str(change.get("kind") or ""),
            maker_id=str(change.get("maker_id") or change.get("makerId") or ""),
            payload=dict(change.get("payload") or {}),
            required_authority=str(
                change.get("required_authority")
                or change.get("requiredAuthority")
                or required_authority_for_change(str(change.get("kind") or ""), change.get("payload") or {})
            ),
        )

    reasons: list[str] = []
    if cannot_approve_own_change(maker_id=change.maker_id, checker_id=checker_id):
        reasons.append("cannot_approve_own_change")

    needed = required_authority_for_change(change.kind, change.payload)
    # Use the stronger of declared vs computed requirement.
    if authority_rank(needed) > authority_rank(change.required_authority):
        required = needed
    else:
        required = change.required_authority

    checker_max = max((authority_rank(r) for r in checker_roles), default=0)
    if checker_max < authority_rank(required):
        reasons.append(f"insufficient_authority:need_{required}")

    # SoD: risk_officer cannot both propose and approve limit loosen if sole role conflict set.
    if change.kind.upper() in {"LIMIT_LOOSEN", "RAISE_LIMIT"} and "trader" in {
        r.lower() for r in checker_roles
    } and "risk_officer" not in {r.lower() for r in checker_roles}:
        reasons.append("sod_trader_cannot_approve_limit_loosen")

    return ApprovalDecision(allowed=not reasons, reasons=reasons)


def segregation_matrix() -> dict[str, Any]:
    return {
        "rules": [
            {"action": "approve_change", "forbidden": "same_as_maker"},
            {"action": "limit_loosen", "minAuthority": "risk_officer"},
            {"action": "limit_tighten", "minAuthority": "operator"},
            {"action": "enable_live", "minAuthority": "BLOCKED"},
        ],
        "truth": {
            **DEFAULT_TRUTH.public_dict(),
            "live_trading_approval_path_BLOCKED": True,
        },
    }
