"""Technical AuthorityProfile — capability scopes and side-effect policy.

Separate from BehaviorProfile (SYSTEM_PROMPT / behavioral steering).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ApprovalMode(str, Enum):
    """Operator-configurable technical approval posture."""

    STRICT = "strict"  # gated side-effects always require approval
    STANDARD = "standard"  # current PolicyEngine defaults
    PERMISSIVE = "permissive"  # operator may widen auto-allowed effects
    DISABLED = "disabled"  # approvals mechanistically off (still audited when used)


@dataclass(frozen=True)
class ResourceCeilings:
    """Hard technical ceilings for a scope (U010 companion)."""

    max_wall_time_seconds: float | None = None
    max_tokens: int | None = None
    max_tool_calls: int | None = None
    max_cpu_percent: float | None = None
    max_ram_mb: float | None = None
    max_gpu_count: int | None = None
    max_vram_mb: float | None = None
    max_disk_mb: float | None = None
    max_monetary_cost: float | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "max_wall_time_seconds": self.max_wall_time_seconds,
            "max_tokens": self.max_tokens,
            "max_tool_calls": self.max_tool_calls,
            "max_cpu_percent": self.max_cpu_percent,
            "max_ram_mb": self.max_ram_mb,
            "max_gpu_count": self.max_gpu_count,
            "max_vram_mb": self.max_vram_mb,
            "max_disk_mb": self.max_disk_mb,
            "max_monetary_cost": self.max_monetary_cost,
        }


@dataclass(frozen=True)
class AuthorityProfile:
    """Technical capability authority — not behavioral content policy."""

    id: str
    version: str
    capability_scopes: tuple[str, ...] = ()
    side_effect_policy: str = "standard"
    approval_mode: ApprovalMode = ApprovalMode.STANDARD
    resource_ceilings: ResourceCeilings = field(default_factory=ResourceCeilings)
    network_scopes: tuple[str, ...] = ()
    filesystem_scopes: tuple[str, ...] = ()
    credential_grants: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "capability_scopes": list(self.capability_scopes),
            "side_effect_policy": self.side_effect_policy,
            "approval_mode": self.approval_mode.value,
            "resource_ceilings": self.resource_ceilings.public_dict(),
            "network_scopes": list(self.network_scopes),
            "filesystem_scopes": list(self.filesystem_scopes),
            "credential_grants": list(self.credential_grants),
            "metadata": self.metadata,
            "truth": {
                "authority_is_not_behavior": True,
                "system_prompt_cannot_grant_host_privileges": True,
                "discoverable_is_not_authorized": True,
                "enforcement_class": "declared_not_enforced",
                "ceilings_are_declarative_until_gateway_enforces": True,
            },
        }


DEFAULT_AUTHORITY_PROFILE = AuthorityProfile(
    id="leviathan.default",
    version="1",
    capability_scopes=("builtin", "knowledge.read"),
    side_effect_policy="standard",
    approval_mode=ApprovalMode.STANDARD,
)
