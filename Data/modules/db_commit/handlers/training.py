"""Training domain commit handlers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from Data.modules.db_commit.handlers.registry import FunctionHandler
from Data.modules.db_commit.types import CommitIntent, CommitReceipt, CommitReceiptStatus, utc_now


def handlers() -> list[FunctionHandler]:
    return [
        FunctionHandler(
            operation="training.commit_lineage",
            fn=_commit_lineage,
            required_payload_keys=("training_job_id",),
        ),
        FunctionHandler(
            operation="training.commit_metrics_batch",
            fn=_commit_metrics_batch,
            required_payload_keys=("training_job_id", "metrics"),
        ),
    ]


def _store(db_path: Path) -> Any:
    from Data.modules.training.store import TrainingStore

    store = TrainingStore(db_path)
    if hasattr(store, "initialize"):
        store.initialize()
    return store


def _commit_lineage(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    store = _store(db_path)
    job_id = str(payload["training_job_id"])
    lineage = dict(payload.get("lineage") or {})
    artifacts = list(payload.get("artifacts") or [])
    if hasattr(store, "commit_lineage"):
        store.commit_lineage(job_id, lineage)
    elif hasattr(store, "save_lineage"):
        store.save_lineage(job_id, lineage)
    for art in artifacts:
        if hasattr(store, "register_artifact"):
            store.register_artifact(job_id, art)
    return CommitReceipt(
        commit_id=intent.commit_id,
        idempotency_key=intent.idempotency_key,
        domain="training",
        operation=intent.operation,
        status=CommitReceiptStatus.APPLIED.value,
        entity_type="training_job",
        entity_id=job_id,
        payload_hash=intent.payload_hash,
        applied_at=utc_now(),
        record_count=1 + len(artifacts),
        producer_job_id=intent.source_job_id,
        trace_id=intent.trace_id,
        result={"training_job_id": job_id, "artifacts": len(artifacts)},
    )


def _commit_metrics_batch(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    store = _store(db_path)
    job_id = str(payload["training_job_id"])
    metrics = list(payload.get("metrics") or [])
    applied = 0
    if hasattr(store, "append_metrics_batch"):
        applied = int(store.append_metrics_batch(job_id, metrics) or len(metrics))
    else:
        for row in metrics:
            if hasattr(store, "append_metric"):
                store.append_metric(job_id, row)
                applied += 1
            elif hasattr(store, "record_metric"):
                store.record_metric(job_id, row)
                applied += 1
            else:
                break
    return CommitReceipt(
        commit_id=intent.commit_id,
        idempotency_key=intent.idempotency_key,
        domain="training",
        operation=intent.operation,
        status=CommitReceiptStatus.APPLIED.value,
        entity_type="training_job",
        entity_id=job_id,
        payload_hash=intent.payload_hash,
        applied_at=utc_now(),
        record_count=applied,
        producer_job_id=intent.source_job_id,
        trace_id=intent.trace_id,
        result={"training_job_id": job_id, "metrics": applied},
    )
