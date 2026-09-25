"""Evaluation domain commit handlers."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from Data.modules.db_commit.handlers.registry import FunctionHandler
from Data.modules.db_commit.types import CommitIntent, CommitReceipt, CommitReceiptStatus, utc_now


def handlers() -> list[FunctionHandler]:
    return [
        FunctionHandler(
            operation="evaluation.commit_results",
            fn=_commit_results,
            required_payload_keys=("evaluation_id", "results"),
        ),
    ]


def _commit_results(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    from Data.modules.evaluation.store import EvaluationStore
    from Data.modules.evaluation.types import (
        EvalCaseResult,
        EvalOutcome,
        EvalReport,
        JudgmentKind,
        MeasurementState,
    )

    store = EvaluationStore(db_path)
    store.initialize()
    evaluation_id = str(payload["evaluation_id"])
    raw_results = list(payload.get("results") or [])
    report_meta = dict(payload.get("report") or {})

    case_results: list[EvalCaseResult] = []
    for row in raw_results:
        outcome_raw = str(row.get("outcome") or "UNMEASURED")
        try:
            outcome = EvalOutcome(outcome_raw)
        except Exception:  # noqa: BLE001
            outcome = EvalOutcome.UNMEASURED
        measurement_raw = str(row.get("measurement") or "UNMEASURED")
        try:
            measurement = MeasurementState(measurement_raw)
        except Exception:  # noqa: BLE001
            measurement = MeasurementState.UNMEASURED
        judgment_raw = str(row.get("judgment_kind") or "DETERMINISTIC")
        try:
            judgment = JudgmentKind(judgment_raw)
        except Exception:  # noqa: BLE001
            judgment = JudgmentKind.DETERMINISTIC
        case_results.append(
            EvalCaseResult(
                case_id=str(row.get("case_id") or uuid.uuid4()),
                outcome=outcome,
                measurement=measurement,
                judgment_kind=judgment,
                detail=str(row.get("detail") or "") or None,
                component=str(row.get("component") or "default"),
                artifact_refs=tuple(row.get("artifact_refs") or ()),
                evidence_refs=tuple(row.get("evidence_refs") or ()),
            )
        )

    summary = dict(report_meta.get("summary") or {})
    summary.setdefault("cases", len(case_results))
    report = EvalReport(
        suite_id=str(report_meta.get("suite_id") or evaluation_id),
        name=str(report_meta.get("name") or intent.safe_human_title or evaluation_id),
        results=tuple(case_results),
        summary=summary,
        suite_version=str(report_meta.get("suite_version") or "1"),
        report_id=str(report_meta.get("report_id") or evaluation_id),
        component_scope=tuple(report_meta.get("component_scope") or ()),
        system_level=bool(report_meta.get("system_level") or False),
        artifact_refs=tuple(report_meta.get("artifact_refs") or ()),
    )
    store.save_report(report)
    return CommitReceipt(
        commit_id=intent.commit_id,
        idempotency_key=intent.idempotency_key,
        domain="evaluation",
        operation=intent.operation,
        status=CommitReceiptStatus.APPLIED.value,
        entity_type="evaluation",
        entity_id=evaluation_id,
        payload_hash=intent.payload_hash,
        applied_at=utc_now(),
        record_count=len(case_results),
        producer_job_id=intent.source_job_id,
        trace_id=intent.trace_id,
        result={"evaluation_id": evaluation_id, "results": len(case_results)},
    )
