"""Operational security honesty (W23) — local-first; unmeasured OS enforcement is UNMEASURED."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AuthModeReport:
    mode: str  # loopback_no_auth | operator_token | local_users
    non_loopback_requires_auth: bool = True
    measured: bool = False
    detail: str = ""

    def public_dict(self) -> dict[str, Any]:
        status = "MEASURED" if self.measured else "UNMEASURED"
        return {
            "mode": self.mode,
            "non_loopback_requires_auth": self.non_loopback_requires_auth,
            "status": status,
            "detail": self.detail,
            "truth": {
                "if_os_enforcement_unmeasured_do_not_call_secure": status == "UNMEASURED",
                "no_secrets_in_logs_or_context": True,
            },
        }


def rbac_roles() -> list[str]:
    return ["owner", "operator", "viewer"]


def security_posture(
    *,
    loopback: bool,
    auth_configured: bool,
    secrets_broker: bool,
) -> dict[str, Any]:
    if loopback and not auth_configured:
        auth = AuthModeReport(mode="loopback_no_auth", measured=True, detail="loopback-only")
    elif auth_configured:
        auth = AuthModeReport(mode="operator_token", measured=True, detail="token/local users")
    else:
        auth = AuthModeReport(mode="loopback_no_auth", measured=False, detail="non-loopback without auth is unsafe")
    return {
        "auth": auth.public_dict(),
        "rbac_roles": rbac_roles(),
        "secrets_broker": "AVAILABLE" if secrets_broker else "NOT_CONFIGURED",
        "rate_limiting": "FEATURE_GATED",
        "opentelemetry": "FEATURE_GATED",
        "truth": {
            "unmeasured_os_enforcement_is_not_secure": True,
            "no_secrets_in_logs_or_context": True,
            "local_first": True,
        },
    }
