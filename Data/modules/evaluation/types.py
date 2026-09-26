from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EvalOutcome(str, Enum):
    """Legacy harness outcomes — kept for compatibility."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    UNMEASURED = "UNMEASURED"
    ERROR = "ERROR"


class MeasurementState(str, Enum):
    """Wave 2 explicit measurement vocabulary (U338).

    UNMEASURED must never be treated as PASS.
    Round 10: NOT_APPLICABLE is scoped-out — also never PASS.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    PARTIAL = "PARTIAL"
    UNMEASURED = "UNMEASURED"
    UNAVAILABLE = "UNAVAILABLE"
    DISABLED = "DISABLED"
    DEGRADED = "DEGRADED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class JudgmentKind(str, Enum):
    """How a case result was obtained (U337)."""

    DETERMINISTIC = "DETERMINISTIC"
    EXECUTABLE_VERIFIER = "EXECUTABLE_VERIFIER"
    RETRIEVAL_EVIDENCE = "RETRIEVAL_EVIDENCE"
    HUMAN = "HUMAN"
    LLM_JUDGE = "LLM_JUDGE"
    STATISTICAL = "STATISTICAL"  # W12 paired bootstrap / compute analysis


def outcome_to_measurement(outcome: EvalOutcome) -> MeasurementState:
    return {
        EvalOutcome.PASSED: MeasurementState.PASS,
        EvalOutcome.FAILED: MeasurementState.FAIL,
        EvalOutcome.UNMEASURED: MeasurementState.UNMEASURED,
        EvalOutcome.ERROR: MeasurementState.FAIL,
    }[outcome]


def measurement_is_pass(state: MeasurementState) -> bool:
    """Only PASS counts as pass. UNMEASURED/PARTIAL/DEGRADED/NOT_APPLICABLE never do."""
    return state == MeasurementState.PASS


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    name: str
    description: str
    check: str  # capability_exists | evidence_verified | always_unmeasured | ...
    params: dict[str, Any] = field(default_factory=dict)
    # Wave 2 versioning / taxonomy
    version: str = "1"
    suite_id: str | None = None
    judgment_kind: JudgmentKind = JudgmentKind.DETERMINISTIC
    component: str | None = None
    system_level: bool = False
    sealed: bool = False
    tags: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "name": self.name,
            "description": self.description,
            "check": self.check,
            "params": self.params,
            "version": self.version,
            "suite_id": self.suite_id,
            "judgment_kind": self.judgment_kind.value,
            "component": self.component,
            "system_level": self.system_level,
            "sealed": self.sealed,
            "tags": list(self.tags),
        }


@dataclass(frozen=True)
class EvalCaseResult:
    case_id: str
    outcome: EvalOutcome
    detail: str | None = None
    judgment_kind: JudgmentKind = JudgmentKind.DETERMINISTIC
    measurement: MeasurementState | None = None
    artifact_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    model_revision: str | None = None
    runtime_revision: str | None = None
    sample_size: int | None = None
    effect_size: float | None = None
    confidence_interval: tuple[float, float] | None = None
    paired_with: str | None = None
    component: str | None = None

    def resolved_measurement(self) -> MeasurementState:
        if self.measurement is not None:
            return self.measurement
        return outcome_to_measurement(self.outcome)

    def public_dict(self) -> dict[str, Any]:
        measurement = self.resolved_measurement()
        return {
            "case_id": self.case_id,
            "outcome": self.outcome.value,
            "detail": self.detail,
            "judgment_kind": self.judgment_kind.value,
            "measurement": measurement.value,
            "artifact_refs": list(self.artifact_refs),
            "evidence_refs": list(self.evidence_refs),
            "model_revision": self.model_revision,
            "runtime_revision": self.runtime_revision,
            "sample_size": self.sample_size,
            "effect_size": self.effect_size,
            "confidence_interval": list(self.confidence_interval)
            if self.confidence_interval
            else None,
            "paired_with": self.paired_with,
            "component": self.component,
            "truth": {
                "unmeasured_is_not_passed": True,
                "measurement_pass_only_when_pass": measurement_is_pass(measurement),
                "judgment_kind_required": True,
            },
        }


@dataclass(frozen=True)
class EvalReport:
    suite_id: str
    name: str
    results: tuple[EvalCaseResult, ...]
    summary: dict[str, int]
    suite_version: str = "1"
    recorded_at: str | None = None
    report_id: str | None = None
    component_scope: tuple[str, ...] = ()
    system_level: bool = False
    artifact_refs: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        measurements = [r.resolved_measurement() for r in self.results]
        return {
            "report_id": self.report_id or self.suite_id,
            "suite_id": self.suite_id,
            "suite_version": self.suite_version,
            "name": self.name,
            "recorded_at": self.recorded_at,
            "results": [item.public_dict() for item in self.results],
            "summary": self.summary,
            "measurement_summary": {
                state.value: sum(1 for m in measurements if m == state)
                for state in MeasurementState
            },
            "component_scope": list(self.component_scope),
            "system_level": self.system_level,
            "artifact_refs": list(self.artifact_refs),
            "truth": {
                "unmeasured_is_not_passed": True,
                "evaluation_is_not_production_proof": True,
                "missing_measurement_is_visible": True,
            },
        }


@dataclass(frozen=True)
class ScorecardEntry:
    component: str
    measurement: MeasurementState
    case_count: int
    passed: int
    failed: int
    unmeasured: int
    detail: str | None = None
    latest_report_id: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "measurement": self.measurement.value,
            "case_count": self.case_count,
            "passed": self.passed,
            "failed": self.failed,
            "unmeasured": self.unmeasured,
            "detail": self.detail,
            "latest_report_id": self.latest_report_id,
            "truth": {
                "unmeasured_is_not_passed": True,
                "promotable": self.measurement == MeasurementState.PASS and self.failed == 0,
            },
        }


@dataclass(frozen=True)
class Scorecard:
    scorecard_id: str
    name: str
    entries: tuple[ScorecardEntry, ...]
    system_measurement: MeasurementState
    generated_at: str
    source_report_ids: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "scorecard_id": self.scorecard_id,
            "name": self.name,
            "entries": [e.public_dict() for e in self.entries],
            "system_measurement": self.system_measurement.value,
            "generated_at": self.generated_at,
            "source_report_ids": list(self.source_report_ids),
            "truth": {
                "unmeasured_is_not_passed": True,
                "system_pass_requires_all_required_components": True,
            },
        }


@dataclass(frozen=True)
class RegressionCase:
    """Incident converted into a durable regression eval case (U325)."""

    regression_id: str
    title: str
    incident_ref: str
    case: EvalCase
    created_at: str
    reproducible: bool = True
    notes: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "regression_id": self.regression_id,
            "title": self.title,
            "incident_ref": self.incident_ref,
            "case": self.case.public_dict(),
            "created_at": self.created_at,
            "reproducible": self.reproducible,
            "notes": self.notes,
        }
