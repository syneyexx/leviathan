"""Domain-facing helpers that submit CommitIntents (never arbitrary SQL)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from Data.modules.db_commit.producer import CommitProducer, SubmitResult
from Data.modules.db_commit.settings import DbCommitSettings, load_db_commit_settings
from Data.modules.db_commit.types import CommitPriority


def producer_for(db_path: Path | str, *, settings: DbCommitSettings | None = None) -> CommitProducer:
    return CommitProducer(db_path, settings=settings or load_db_commit_settings())


def submit_research_evidence(
    db_path: Path | str,
    *,
    project_id: str,
    evidence: list[dict[str, Any]],
    title: str = "",
    source_job_id: str = "",
    idempotency_key: str | None = None,
) -> SubmitResult:
    return producer_for(db_path).submit(
        operation="research.commit_evidence",
        domain="research",
        payload={"project_id": project_id, "evidence": evidence},
        idempotency_key=idempotency_key,
        priority=CommitPriority.P2_DOMAIN,
        entity_type="research_project",
        entity_id=project_id,
        safe_human_title=title or project_id,
        source_job_id=source_job_id,
        record_count_hint=len(evidence),
    )


def submit_research_report(
    db_path: Path | str,
    *,
    project_id: str,
    report: dict[str, Any],
    title: str = "",
    source_job_id: str = "",
    idempotency_key: str | None = None,
) -> SubmitResult:
    return producer_for(db_path).submit(
        operation="research.commit_report",
        domain="research",
        payload={"project_id": project_id, "report": report},
        idempotency_key=idempotency_key,
        priority=CommitPriority.P2_DOMAIN,
        entity_type="research_project",
        entity_id=project_id,
        safe_human_title=title or project_id,
        source_job_id=source_job_id,
        record_count_hint=1,
    )


def submit_dataset_index_batch(
    db_path: Path | str,
    *,
    dataset_id: str,
    rows: list[dict[str, Any]],
    title: str = "",
    source_job_id: str = "",
    idempotency_key: str | None = None,
    batch_index: int = 0,
    batch_count: int = 1,
) -> SubmitResult:
    return producer_for(db_path).submit(
        operation="dataset.commit_index_batch",
        domain="dataset",
        payload={"dataset_id": dataset_id, "rows": rows},
        idempotency_key=idempotency_key,
        priority=CommitPriority.P3_BULK,
        entity_type="dataset",
        entity_id=dataset_id,
        safe_human_title=title or dataset_id,
        source_job_id=source_job_id,
        record_count_hint=len(rows),
        batch_index=batch_index,
        batch_count=batch_count,
    )


def submit_source_ingestion_batch(
    db_path: Path | str,
    *,
    source_id: str,
    records: list[dict[str, Any]],
    title: str = "",
    source_job_id: str = "",
    idempotency_key: str | None = None,
) -> SubmitResult:
    return producer_for(db_path).submit(
        operation="source_ingestion.commit_batch",
        domain="source_ingestion",
        payload={"source_id": source_id, "records": records},
        idempotency_key=idempotency_key,
        priority=CommitPriority.P3_BULK,
        entity_type="source",
        entity_id=source_id,
        safe_human_title=title or source_id,
        source_job_id=source_job_id,
        record_count_hint=len(records),
    )


def submit_market_sim_events(
    db_path: Path | str,
    *,
    run_id: str,
    events: list[dict[str, Any]],
    fills: list[dict[str, Any]] | None = None,
    equity: list[dict[str, Any]] | None = None,
    source_job_id: str = "",
    idempotency_key: str | None = None,
    sequence_number: int = 0,
) -> SubmitResult:
    return producer_for(db_path).submit(
        operation="market_sim.commit_events",
        domain="market_sim",
        payload={
            "run_id": run_id,
            "events": events,
            "fills": fills or [],
            "equity": equity or [],
        },
        idempotency_key=idempotency_key,
        priority=CommitPriority.P2_DOMAIN,
        entity_type="market_sim_run",
        entity_id=run_id,
        safe_human_title=run_id,
        source_job_id=source_job_id,
        record_count_hint=len(events) + len(fills or []) + len(equity or []),
        sequence_key=f"market_sim:{run_id}",
        sequence_number=sequence_number,
    )


def submit_evaluation_results(
    db_path: Path | str,
    *,
    evaluation_id: str,
    results: list[dict[str, Any]],
    report: dict[str, Any] | None = None,
    title: str = "",
    source_job_id: str = "",
    idempotency_key: str | None = None,
) -> SubmitResult:
    return producer_for(db_path).submit(
        operation="evaluation.commit_results",
        domain="evaluation",
        payload={
            "evaluation_id": evaluation_id,
            "results": results,
            "report": report or {},
        },
        idempotency_key=idempotency_key,
        priority=CommitPriority.P2_DOMAIN,
        entity_type="evaluation",
        entity_id=evaluation_id,
        safe_human_title=title or evaluation_id,
        source_job_id=source_job_id,
        record_count_hint=len(results),
    )


def submit_training_lineage(
    db_path: Path | str,
    *,
    training_job_id: str,
    lineage: dict[str, Any],
    artifacts: list[dict[str, Any]] | None = None,
    source_job_id: str = "",
    idempotency_key: str | None = None,
) -> SubmitResult:
    return producer_for(db_path).submit(
        operation="training.commit_lineage",
        domain="training",
        payload={
            "training_job_id": training_job_id,
            "lineage": lineage,
            "artifacts": artifacts or [],
        },
        idempotency_key=idempotency_key,
        priority=CommitPriority.P2_DOMAIN,
        entity_type="training_job",
        entity_id=training_job_id,
        safe_human_title=training_job_id,
        source_job_id=source_job_id,
        record_count_hint=1 + len(artifacts or []),
    )


def submit_knowledge_prepared(
    db_path: Path | str,
    *,
    artifact: dict[str, Any],
    title: str = "",
    source_job_id: str = "",
    idempotency_key: str | None = None,
) -> SubmitResult:
    return producer_for(db_path).submit(
        operation="knowledge.commit_prepared",
        domain="knowledge",
        payload={"artifact": artifact},
        idempotency_key=idempotency_key,
        priority=CommitPriority.P2_DOMAIN,
        entity_type="knowledge_artifact",
        entity_id=str(artifact.get("artifact_id") or ""),
        safe_human_title=title or str(artifact.get("title") or ""),
        source_job_id=source_job_id,
        record_count_hint=1,
    )
