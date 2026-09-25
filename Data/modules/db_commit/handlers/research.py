"""Research domain commit handlers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from Data.modules.db_commit.handlers.registry import FunctionHandler
from Data.modules.db_commit.types import CommitIntent, CommitReceipt, CommitReceiptStatus, utc_now


def handlers() -> list[FunctionHandler]:
    return [
        FunctionHandler(
            operation="research.commit_evidence",
            fn=_commit_evidence,
            required_payload_keys=("project_id", "evidence"),
        ),
        FunctionHandler(
            operation="research.commit_report",
            fn=_commit_report,
            required_payload_keys=("project_id",),
        ),
        FunctionHandler(
            operation="research.commit_claims",
            fn=_commit_claims,
            required_payload_keys=("project_id", "claims"),
        ),
    ]


def _store(db_path: Path) -> Any:
    from Data.modules.research.store import ResearchStore

    store = ResearchStore(db_path)
    store.initialize()
    return store


def _commit_evidence(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    from Data.modules.research.types import (
        BrainStatus,
        ParseStatus,
        ResearchEvidence,
        ResearchSource,
        SourceType,
    )

    store = _store(db_path)
    project_id = str(payload["project_id"])
    if store.get_project(project_id) is None:
        store.create_project(
            title=str(payload.get("title") or intent.safe_human_title or project_id),
            topic=str(payload.get("topic") or intent.safe_human_title or project_id),
            project_id=project_id,
        )
    evidence_items = list(payload.get("evidence") or [])
    applied = 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for item in evidence_items:
        evidence_id = str(item.get("evidence_id") or item.get("id") or uuid.uuid4())
        if store.get_evidence(evidence_id) is not None:
            applied += 1
            continue
        source_id = str(item.get("source_id") or f"prepared:{project_id}")
        if store.get_source(source_id) is None:
            store.upsert_source(
                ResearchSource(
                    source_id=source_id,
                    project_id=project_id,
                    source_type=SourceType.SEED,
                    original_uri=str(item.get("uri") or f"commit://{source_id}"),
                    canonical_uri=str(item.get("uri") or f"commit://{source_id}"),
                    title=str(item.get("source_title") or "prepared"),
                    created_at=now,
                    parse_status=ParseStatus.OK,
                    brain_status=BrainStatus.NOT_APPLICABLE,
                    metadata={"via": "db_commit"},
                )
            )
        ev = ResearchEvidence(
            evidence_id=evidence_id,
            project_id=project_id,
            source_id=source_id,
            span_text=str(item.get("span_text") or item.get("text") or ""),
            created_at=str(item.get("created_at") or now),
            chunk_id=item.get("chunk_id"),
            location=dict(item.get("location") or {}),
            retrieval_method=item.get("retrieval_method"),
            associated_claim_ids=list(item.get("associated_claim_ids") or []),
            metadata=dict(item.get("metadata") or {"via": "db_commit"}),
        )
        store.add_evidence(ev)
        applied += 1
    return _receipt(intent, project_id, applied, {"project_id": project_id, "evidence": applied})


def _commit_claims(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    from Data.modules.research.types import ClaimStatus, ResearchClaim

    store = _store(db_path)
    project_id = str(payload["project_id"])
    if store.get_project(project_id) is None:
        store.create_project(
            title=str(payload.get("title") or intent.safe_human_title or project_id),
            topic=str(payload.get("topic") or intent.safe_human_title or project_id),
            project_id=project_id,
        )
    claims = list(payload.get("claims") or [])
    applied = 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for claim in claims:
        claim_id = str(claim.get("claim_id") or claim.get("id") or uuid.uuid4())
        status_raw = str(claim.get("status") or "OPEN")
        try:
            status = ClaimStatus(status_raw)
        except Exception:  # noqa: BLE001
            status = ClaimStatus.UNRESOLVED
        rc = ResearchClaim(
            claim_id=claim_id,
            project_id=project_id,
            proposition=str(claim.get("proposition") or claim.get("text") or ""),
            status=status,
            created_at=str(claim.get("created_at") or now),
            updated_at=str(claim.get("updated_at") or now),
            raw_wording=claim.get("raw_wording"),
            supporting_evidence_ids=list(claim.get("supporting_evidence_ids") or []),
            contradicting_evidence_ids=list(claim.get("contradicting_evidence_ids") or []),
            source_diversity=int(claim.get("source_diversity") or 0),
            metadata=dict(claim.get("metadata") or {"via": "db_commit"}),
        )
        store.upsert_claim(rc)
        applied += 1
    return _receipt(intent, project_id, applied, {"project_id": project_id, "claims": applied})


def _commit_report(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    from Data.modules.research.types import ResearchReport

    store = _store(db_path)
    project_id = str(payload["project_id"])
    if store.get_project(project_id) is None:
        store.create_project(
            title=str(payload.get("title") or intent.safe_human_title or project_id),
            topic=str(payload.get("topic") or intent.safe_human_title or project_id),
            project_id=project_id,
        )
    report = dict(payload.get("report") or {})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rr = ResearchReport(
        report_id=str(report.get("report_id") or uuid.uuid4()),
        project_id=project_id,
        version=int(report.get("version") or 1),
        title=str(report.get("title") or intent.safe_human_title or "report"),
        body_markdown=str(report.get("body_markdown") or report.get("body") or ""),
        created_at=str(report.get("created_at") or now),
        body_html=report.get("body_html"),
        evidence_ids=list(report.get("evidence_ids") or []),
        source_ids=list(report.get("source_ids") or []),
        model_profile=dict(report.get("model_profile") or {}),
        generation_trace=dict(report.get("generation_trace") or {"via": "db_commit"}),
    )
    # ResearchReport fields may vary — fall back to add_report kwargs via public_dict.
    if hasattr(store, "add_report"):
        try:
            store.add_report(rr)
        except TypeError:
            # Older/newer shape: persist via event.
            store.add_event(project_id, "report", rr.public_dict() if hasattr(rr, "public_dict") else report)
    return _receipt(intent, project_id, 1, {"project_id": project_id, "report": True})


def _receipt(
    intent: CommitIntent,
    entity_id: str,
    record_count: int,
    result: dict[str, Any],
) -> CommitReceipt:
    return CommitReceipt(
        commit_id=intent.commit_id,
        idempotency_key=intent.idempotency_key,
        domain="research",
        operation=intent.operation,
        status=CommitReceiptStatus.APPLIED.value,
        entity_type=intent.entity_type or "research_project",
        entity_id=entity_id,
        payload_hash=intent.payload_hash,
        applied_at=utc_now(),
        record_count=record_count,
        producer_job_id=intent.source_job_id,
        trace_id=intent.trace_id,
        batch_index=intent.batch_index,
        batch_count=intent.batch_count,
        result=result,
    )
