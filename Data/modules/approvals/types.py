from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    capability_id: str
    side_effects: tuple[str, ...]
    status: ApprovalStatus
    requested_by: str
    created_at: str
    reason: str | None = None
    run_id: str | None = None
    decided_by: str | None = None
    decided_at: str | None = None
    expires_at: str | None = None
    single_use: bool = True
    arguments_digest: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "capability_id": self.capability_id,
            "side_effects": list(self.side_effects),
            "status": self.status.value,
            "requested_by": self.requested_by,
            "created_at": self.created_at,
            "reason": self.reason,
            "run_id": self.run_id,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at,
            "expires_at": self.expires_at,
            "single_use": self.single_use,
            "arguments_digest": self.arguments_digest,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class PolicyDecision:
    requires_approval: bool
    reason: str
    auto_effects: tuple[str, ...] = ()
    gated_effects: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "requires_approval": self.requires_approval,
            "reason": self.reason,
            "auto_effects": list(self.auto_effects),
            "gated_effects": list(self.gated_effects),
        }
