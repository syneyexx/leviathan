"""W65 — Security hardening helpers: least privilege checks + redaction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, DEFAULT_TRUTH
from .ai_governance import redact_mapping, SENSITIVE_KEYS


@dataclass(frozen=True)
class PrivilegeRequirement:
    action: str
    min_role: str
    resource: str = "*"

    def public_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "minRole": self.min_role,
            "resource": self.resource,
        }


DEFAULT_PRIVILEGES: tuple[PrivilegeRequirement, ...] = (
    PrivilegeRequirement("read_portfolio", "viewer"),
    PrivilegeRequirement("place_paper_order", "trader"),
    PrivilegeRequirement("loosen_limits", "risk_officer"),
    PrivilegeRequirement("approve_change", "risk_officer"),
    PrivilegeRequirement("view_secrets", "security_admin"),
    PrivilegeRequirement("enable_live", "BLOCKED"),
)


@dataclass
class PrivilegeCheckResult:
    allowed: bool
    action: str
    reasons: list[str] = field(default_factory=list)
    status: str = MeasurementState.OBSERVED.value

    def public_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "action": self.action,
            "reasons": list(self.reasons),
            "status": self.status,
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "least_privilege_default_deny": True,
            },
        }


_ROLE_RANK = {
    "viewer": 10,
    "operator": 20,
    "trader": 30,
    "risk_officer": 40,
    "compliance": 50,
    "admin": 60,
    "security_admin": 70,
}


def check_least_privilege(
    *,
    action: str,
    roles: Sequence[str],
    requirements: Sequence[PrivilegeRequirement] = DEFAULT_PRIVILEGES,
) -> PrivilegeCheckResult:
    action_u = str(action)
    req = next((r for r in requirements if r.action == action_u), None)
    if req is None:
        return PrivilegeCheckResult(
            allowed=False,
            action=action_u,
            reasons=["default_deny_unknown_action"],
        )
    if req.min_role == "BLOCKED":
        return PrivilegeCheckResult(
            allowed=False,
            action=action_u,
            reasons=["action_BLOCKED"],
            status=MeasurementState.BLOCKED.value,
        )
    max_rank = max((_ROLE_RANK.get(r.lower(), 0) for r in roles), default=0)
    need = _ROLE_RANK.get(req.min_role.lower(), 999)
    if max_rank < need:
        return PrivilegeCheckResult(
            allowed=False,
            action=action_u,
            reasons=[f"insufficient_role:need_{req.min_role}"],
        )
    return PrivilegeCheckResult(allowed=True, action=action_u, reasons=[])


def redact_secrets(payload: Mapping[str, Any]) -> dict[str, Any]:
    redacted, _found = redact_mapping(payload)
    return {
        "payload": redacted,
        "redactedKeys": _found,
        "sensitiveKeyUniverse": sorted(SENSITIVE_KEYS),
        "truth": {
            **DEFAULT_TRUTH.public_dict(),
            "redaction_is_best_effort_key_match": True,
        },
    }


def security_posture_snapshot(
    *,
    roles_present: Sequence[str],
    live_trading_blocked: bool = True,
) -> dict[str, Any]:
    checks = [
        check_least_privilege(action=r.action, roles=roles_present).public_dict()
        for r in DEFAULT_PRIVILEGES
    ]
    return {
        "rolesPresent": list(roles_present),
        "checks": checks,
        "liveTradingBlocked": live_trading_blocked,
        "status": (
            MeasurementState.OBSERVED.value
            if live_trading_blocked
            else MeasurementState.FAIL.value
        ),
        "truth": DEFAULT_TRUTH.public_dict(),
    }
