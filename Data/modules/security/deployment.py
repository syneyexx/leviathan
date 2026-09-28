"""Deployment mode honesty — local single-user vs multi-user (Round 8)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from Data.backend.config import Settings


@dataclass(frozen=True)
class DeploymentSecurityPosture:
    mode: str  # local_single_user | multi_user_network
    authentication_required: bool
    authorization_required: bool
    authentication_implemented: bool
    authorization_implemented: bool
    loopback_only: bool
    notes: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        multi = self.mode == "multi_user_network"
        auth_ok = (not multi) or (self.authentication_implemented and self.authorization_implemented)
        return {
            "mode": self.mode,
            "authentication_required": self.authentication_required,
            "authorization_required": self.authorization_required,
            "authentication_implemented": self.authentication_implemented,
            "authorization_implemented": self.authorization_implemented,
            "loopback_only": self.loopback_only,
            "notes": list(self.notes),
            "truth": {
                "local_single_user_preserved_without_enterprise_complexity": not multi,
                "multi_user_requires_real_auth": multi,
                "auth_posture_honest": auth_ok,
                "configuration_is_not_enforcement_proof": True,
                "approval_is_not_authentication": True,
            },
        }


def assess_deployment_security(settings: Settings) -> DeploymentSecurityPosture:
    loopback = bool(getattr(settings.runtime, "loopback_only", True))
    # Multi-user/network is not a first-class LEVIATHAN mode in this tree unless
    # explicitly non-loopback with an auth feature. Keep local single-user default.
    auth_feature = bool(getattr(settings.features, "multi_user_auth", False)) if hasattr(settings, "features") else False
    operator_token = bool((os.environ.get("LEVIATHAN_OPERATOR_TOKEN") or "").strip())
    if not loopback or auth_feature:
        return DeploymentSecurityPosture(
            mode="multi_user_network",
            authentication_required=True,
            authorization_required=True,
            # Operator token is a real caller-auth boundary for mutations, not IdP/RBAC.
            authentication_implemented=operator_token,
            authorization_implemented=bool(getattr(settings.features, "capability_world", False)),
            loopback_only=loopback,
            notes=(
                "Non-loopback requires LEVIATHAN_OPERATOR_TOKEN for all /api mutations",
                "Operator token authenticates the caller; ApprovalService is separate authorization",
                "Scoped RBAC / actor identities are not yet a product mode",
            ),
        )
    return DeploymentSecurityPosture(
        mode="local_single_user",
        authentication_required=False,
        authorization_required=False,
        authentication_implemented=False,
        authorization_implemented=bool(getattr(settings.features, "capability_world", False)),
        loopback_only=True,
        notes=(
            "Local single-user / loopback deployment — no enterprise IdP required",
            "Capability approvals still gate side effects when capability_world is on",
        ),
    )
