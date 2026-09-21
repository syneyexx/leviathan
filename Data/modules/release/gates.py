from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class GateSeverity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class GateCheck:
    gate_id: str
    name: str
    severity: GateSeverity
    passed: bool
    detail: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "name": self.name,
            "severity": self.severity.value,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ReleaseGateReport:
    ready: bool
    checks: tuple[GateCheck, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "checks": [item.public_dict() for item in self.checks],
            "metadata": self.metadata,
            "truth": {
                "unmeasured_is_not_passed": True,
                "release_ready_is_not_production_certified": True,
            },
        }


class ReleaseGateRunner:
    """Local release/readiness gates for LEVIATHAN foundation."""

    def __init__(self, checks: list[Callable[[], GateCheck]] | None = None) -> None:
        self._checks = list(checks or [])

    def add(self, check: Callable[[], GateCheck]) -> None:
        self._checks.append(check)

    def run(self) -> ReleaseGateReport:
        results = tuple(check() for check in self._checks)
        blocked = any(
            (not item.passed) and item.severity == GateSeverity.BLOCK for item in results
        )
        return ReleaseGateReport(
            ready=not blocked,
            checks=results,
            metadata={"check_count": len(results)},
        )
