from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class IsolationMode(str, Enum):
    NONE = "NONE"
    PROCESS = "PROCESS"
    NETWORK_DENY = "NETWORK_DENY"
    WORKSPACE = "WORKSPACE"


@dataclass(frozen=True)
class IsolationRequest:
    requested: tuple[IsolationMode, ...]
    reason: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "requested": [item.value for item in self.requested],
            "reason": self.reason,
        }


@dataclass(frozen=True)
class IsolationEffective:
    effective: tuple[IsolationMode, ...]
    matched: bool
    notes: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "effective": [item.value for item in self.effective],
            "matched": self.matched,
            "notes": list(self.notes),
            "truth": {
                "requested_isolation_is_not_effective_isolation": True,
                "matched_means_application_intended_only": True,
                "matched_is_not_os_enforcement": True,
            },
        }


@dataclass(frozen=True)
class IsolationReport:
    request: IsolationRequest
    effective: IsolationEffective
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.public_dict(),
            "effective": self.effective.public_dict(),
            "metadata": self.metadata,
            "truth": {
                "requested_isolation_is_not_effective_isolation": True,
                "application_intended_is_not_os_enforced": True,
                "configuration_is_not_enforcement_proof": True,
            },
        }
