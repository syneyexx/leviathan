from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class MasterGateStatus(str, Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    DEGRADED = "DEGRADED"
    UNMEASURED = "UNMEASURED"


@dataclass(frozen=True)
class MasterGateCheck:
    check_id: str
    name: str
    status: MasterGateStatus
    detail: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class MasterGateReport:
    status: MasterGateStatus
    checks: tuple[MasterGateCheck, ...]
    phase_span: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "checks": [item.public_dict() for item in self.checks],
            "phase_span": self.phase_span,
            "metadata": self.metadata,
            "truth": {
                "master_ready_is_not_production_certified": True,
                "unmeasured_is_not_passed": True,
                "local_first": True,
            },
        }


class MasterGateRunner:
    """Compose local readiness signals into one Master Program summary."""

    def __init__(self, checks: list[Callable[[], MasterGateCheck]] | None = None) -> None:
        self._checks = list(checks or [])

    def add(self, check: Callable[[], MasterGateCheck]) -> None:
        self._checks.append(check)

    def run(self) -> MasterGateReport:
        results = tuple(check() for check in self._checks)
        if not results:
            status = MasterGateStatus.UNMEASURED
        elif any(item.status == MasterGateStatus.BLOCKED for item in results):
            status = MasterGateStatus.BLOCKED
        elif any(item.status == MasterGateStatus.UNMEASURED for item in results):
            status = MasterGateStatus.UNMEASURED
        elif any(item.status == MasterGateStatus.DEGRADED for item in results):
            status = MasterGateStatus.DEGRADED
        else:
            status = MasterGateStatus.READY
        return MasterGateReport(
            status=status,
            checks=results,
            phase_span="0-54",
            metadata={"program": "LEVIATHAN Master Engineering Program"},
        )
