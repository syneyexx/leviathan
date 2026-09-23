from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from .ci import GateMeasurement, measurement_blocks_release, measurement_counts_as_success


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
    measurement: GateMeasurement = GateMeasurement.PASS

    def public_dict(self) -> dict[str, Any]:
        measurement = self.measurement
        # If callers only set passed=False without measurement, treat as FAIL.
        if not self.passed and measurement == GateMeasurement.PASS:
            measurement = GateMeasurement.FAIL
        return {
            "gate_id": self.gate_id,
            "name": self.name,
            "severity": self.severity.value,
            "passed": self.passed,
            "detail": self.detail,
            "measurement": measurement.value,
            "truth": {
                "unmeasured_is_not_passed": not measurement_counts_as_success(measurement),
                "not_applicable_is_not_pass": measurement != GateMeasurement.PASS,
                "skipped_unavailable_is_not_success": True,
            },
        }


@dataclass(frozen=True)
class ReleaseGateReport:
    ready: bool
    checks: tuple[GateCheck, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        measurements = []
        for item in self.checks:
            m = item.measurement
            if not item.passed and m == GateMeasurement.PASS:
                m = GateMeasurement.FAIL
            measurements.append(m)
        return {
            "ready": self.ready,
            "checks": [item.public_dict() for item in self.checks],
            "metadata": {
                **self.metadata,
                "pass_count": sum(1 for m in measurements if m == GateMeasurement.PASS),
                "fail_count": sum(1 for m in measurements if m == GateMeasurement.FAIL),
                "unmeasured_count": sum(1 for m in measurements if m == GateMeasurement.UNMEASURED),
                "not_applicable_count": sum(
                    1 for m in measurements if m == GateMeasurement.NOT_APPLICABLE
                ),
            },
            "truth": {
                "unmeasured_is_not_passed": True,
                "not_applicable_is_not_pass": True,
                "skipped_unavailable_is_not_success": True,
                "release_ready_is_not_production_certified": True,
                "evaluation_is_release_authority": True,
            },
        }


class ReleaseGateRunner:
    """Local release/readiness gates for LEVIATHAN foundation.

    Wave 2: evaluation relevance can BLOCK promotion when configured as BLOCK.
    Round 10: NOT_APPLICABLE / UNMEASURED never count as PASS.
    """

    def __init__(self, checks: list[Callable[[], GateCheck]] | None = None) -> None:
        self._checks = list(checks or [])

    def add(self, check: Callable[[], GateCheck]) -> None:
        self._checks.append(check)

    def run(self) -> ReleaseGateReport:
        results = tuple(check() for check in self._checks)
        blocked = any(
            measurement_blocks_release(
                (
                    item.measurement
                    if not (not item.passed and item.measurement == GateMeasurement.PASS)
                    else GateMeasurement.FAIL
                ),
                severity=item.severity.value,
            )
            or ((not item.passed) and item.severity == GateSeverity.BLOCK)
            for item in results
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
    measurement_raw = str(relevance.get("measurement") or "UNMEASURED")
    promotable = bool(relevance.get("promotable"))
    detail = str(relevance.get("detail") or measurement_raw)

    if not recorded:
        return GateCheck(
            gate_id=gate_id,
            name=name,
            severity=severity,
            passed=False,
            detail=detail or "no relevant eval report recorded",
            measurement=GateMeasurement.FAIL,
        )

    if require_pass:
        ok = promotable and measurement_raw == "PASS"
        m = GateMeasurement.PASS if ok else (
            GateMeasurement.UNMEASURED
            if measurement_raw == "UNMEASURED"
            else GateMeasurement.FAIL
        )
    else:
        # Recorded + no FAIL is enough for soft relevance; UNMEASURED still fails require_pass.
        if measurement_raw == "FAIL":
            ok, m = False, GateMeasurement.FAIL
        elif measurement_raw == "UNMEASURED":
            ok, m = True, GateMeasurement.UNMEASURED  # soft ready, not a PASS claim
        elif measurement_raw == "PASS":
            ok, m = True, GateMeasurement.PASS
        else:
            ok, m = True, GateMeasurement.UNMEASURED

    if measurement_raw == "UNMEASURED" and require_pass:
        ok = False
        m = GateMeasurement.UNMEASURED
        detail = f"{detail}; UNMEASURED ≠ PASS"

    return GateCheck(
        gate_id=gate_id,
        name=name,
        severity=severity,
        passed=ok,
        detail=detail,
        measurement=m,
    )
