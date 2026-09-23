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
                "evaluation_is_release_authority": True,
            },
        }


class ReleaseGateRunner:
    """Local release/readiness gates for LEVIATHAN foundation.

    Wave 2: evaluation relevance can BLOCK promotion when configured as BLOCK.
    """

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


def evaluation_relevance_gate(
    relevance: dict[str, Any],
    *,
    gate_id: str = "evaluation_relevance",
    name: str = "Relevant evaluation recorded",
    severity: GateSeverity = GateSeverity.BLOCK,
    require_pass: bool = False,
) -> GateCheck:
    """Map EvaluationStore/Platform.has_relevant_eval → GateCheck (U335).

    UNMEASURED never counts as passed for promotion when require_pass=True.
    """
    recorded = bool(relevance.get("recorded"))
    measurement = str(relevance.get("measurement") or "UNMEASURED")
    promotable = bool(relevance.get("promotable"))
    detail = str(relevance.get("detail") or measurement)

    if not recorded:
        return GateCheck(
            gate_id=gate_id,
            name=name,
            severity=severity,
            passed=False,
            detail=detail or "no relevant eval report recorded",
        )

    if require_pass:
        ok = promotable and measurement == "PASS"
    else:
        # Recorded + no FAIL is enough for soft relevance; UNMEASURED still fails require_pass.
        ok = measurement != "FAIL" and recorded

    if measurement == "UNMEASURED" and require_pass:
        ok = False
        detail = f"{detail}; UNMEASURED ≠ PASS"

    return GateCheck(
        gate_id=gate_id,
        name=name,
        severity=severity,
        passed=ok,
        detail=detail,
    )
