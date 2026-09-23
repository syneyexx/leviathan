"""Component + system scorecards derived from durable eval reports (U330–U334)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from .types import (
    EvalCaseResult,
    EvalOutcome,
    EvalReport,
    MeasurementState,
    Scorecard,
    ScorecardEntry,
    measurement_is_pass,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _aggregate_component(
    component: str,
    results: list[EvalCaseResult],
    *,
    latest_report_id: str | None,
) -> ScorecardEntry:
    passed = sum(1 for r in results if r.outcome == EvalOutcome.PASSED)
    failed = sum(
        1 for r in results if r.outcome in (EvalOutcome.FAILED, EvalOutcome.ERROR)
    )
    unmeasured = sum(1 for r in results if r.outcome == EvalOutcome.UNMEASURED)
    if failed:
        measurement = MeasurementState.FAIL
        detail = f"{failed} failed/error"
    elif unmeasured and passed:
        measurement = MeasurementState.PARTIAL
        detail = f"{unmeasured} unmeasured, {passed} passed"
    elif unmeasured:
        measurement = MeasurementState.UNMEASURED
        detail = f"{unmeasured} unmeasured (not pass)"
    elif passed:
        measurement = MeasurementState.PASS
        detail = f"{passed} passed"
    else:
        measurement = MeasurementState.UNMEASURED
        detail = "no cases"
    return ScorecardEntry(
        component=component,
        measurement=measurement,
        case_count=len(results),
        passed=passed,
        failed=failed,
        unmeasured=unmeasured,
        detail=detail,
        latest_report_id=latest_report_id,
    )


def build_scorecard(
    reports: Iterable[EvalReport],
    *,
    name: str = "system scorecard",
    scorecard_id: str | None = None,
    required_components: tuple[str, ...] | None = None,
) -> Scorecard:
    """Build a scorecard. System PASS only if every required component is PASS."""
    by_component: dict[str, list[EvalCaseResult]] = {}
    report_ids: list[str] = []
    latest_by_component: dict[str, str | None] = {}

    for report in reports:
        rid = report.report_id or report.suite_id
        report_ids.append(rid)
        for result in report.results:
            component = result.component or "unscoped"
            by_component.setdefault(component, []).append(result)
            latest_by_component[component] = rid

    entries = tuple(
        _aggregate_component(
            component,
            results,
            latest_report_id=latest_by_component.get(component),
        )
        for component, results in sorted(by_component.items())
    )

    required = required_components
    if required is None:
        required = tuple(e.component for e in entries)

    required_set = set(required)
    relevant = [e for e in entries if e.component in required_set] if required_set else list(entries)

    if not relevant:
        system = MeasurementState.UNMEASURED
    elif any(e.measurement == MeasurementState.FAIL for e in relevant):
        system = MeasurementState.FAIL
    elif any(
        e.measurement
        in (
            MeasurementState.UNMEASURED,
            MeasurementState.PARTIAL,
            MeasurementState.UNAVAILABLE,
            MeasurementState.DISABLED,
            MeasurementState.DEGRADED,
        )
        for e in relevant
    ):
        # Any non-PASS required component → system is not PASS (U338).
        if all(e.measurement == MeasurementState.PARTIAL for e in relevant):
            system = MeasurementState.PARTIAL
        elif any(e.measurement == MeasurementState.DEGRADED for e in relevant):
            system = MeasurementState.DEGRADED
        else:
            system = MeasurementState.UNMEASURED
    elif all(measurement_is_pass(e.measurement) for e in relevant):
        system = MeasurementState.PASS
    else:
        system = MeasurementState.UNMEASURED

    return Scorecard(
        scorecard_id=scorecard_id or str(uuid.uuid4()),
        name=name,
        entries=entries,
        system_measurement=system,
        generated_at=_utc_now(),
        source_report_ids=tuple(report_ids),
    )


def scorecard_from_report_dicts(
    report_dicts: Iterable[dict[str, Any]],
    *,
    name: str = "system scorecard",
    required_components: tuple[str, ...] | None = None,
) -> Scorecard:
    """Rebuild EvalReport-ish objects from store dicts for scorecard aggregation."""
    reports: list[EvalReport] = []
    for raw in report_dicts:
        results: list[EvalCaseResult] = []
        for item in raw.get("results") or []:
            try:
                outcome = EvalOutcome(str(item.get("outcome") or EvalOutcome.UNMEASURED.value))
            except ValueError:
                outcome = EvalOutcome.UNMEASURED
            measurement_raw = item.get("measurement")
            measurement: MeasurementState | None = None
            if measurement_raw:
                try:
                    measurement = MeasurementState(str(measurement_raw))
                except ValueError:
                    measurement = None
            from .types import JudgmentKind

            try:
                judgment = JudgmentKind(
                    str(item.get("judgment_kind") or JudgmentKind.DETERMINISTIC.value)
                )
            except ValueError:
                judgment = JudgmentKind.DETERMINISTIC
            results.append(
                EvalCaseResult(
                    case_id=str(item.get("case_id") or "unknown"),
                    outcome=outcome,
                    detail=item.get("detail"),
                    judgment_kind=judgment,
                    measurement=measurement,
                    artifact_refs=tuple(item.get("artifact_refs") or ()),
                    evidence_refs=tuple(item.get("evidence_refs") or ()),
                    component=item.get("component"),
                )
            )
        reports.append(
            EvalReport(
                suite_id=str(raw.get("suite_id") or "unknown"),
                name=str(raw.get("name") or "report"),
                results=tuple(results),
                summary=dict(raw.get("summary") or {}),
                suite_version=str(raw.get("suite_version") or "1"),
                recorded_at=raw.get("recorded_at"),
                report_id=raw.get("report_id"),
                component_scope=tuple(raw.get("component_scope") or ()),
                system_level=bool(raw.get("system_level")),
                artifact_refs=tuple(raw.get("artifact_refs") or ()),
            )
        )
    return build_scorecard(
        reports,
        name=name,
        required_components=required_components,
    )
