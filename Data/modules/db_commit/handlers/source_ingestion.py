"""Source ingestion domain commit handlers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from Data.modules.common.sqlite_policy import open_sqlite_connection, write_transaction
from Data.modules.db_commit.handlers.registry import FunctionHandler
from Data.modules.db_commit.types import CommitIntent, CommitReceipt, CommitReceiptStatus, utc_now


def handlers() -> list[FunctionHandler]:
    return [
        FunctionHandler(
            operation="source_ingestion.commit_batch",
            fn=_commit_batch,
            required_payload_keys=("source_id", "records"),
        ),
        FunctionHandler(
            operation="source_ingestion.commit_brain_sync",
            fn=_commit_brain_sync,
            required_payload_keys=("source_id",),
        ),
    ]


def _commit_batch(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    """Persist prepared member/record metadata. PDF/archive parse stays outside."""
    from Data.modules.source_ingestion.store import IngestionStore

    store = IngestionStore(db_path)
    store.initialize()
    source_id = str(payload["source_id"])
    records = list(payload.get("records") or [])

    conn = open_sqlite_connection(db_path)
    try:
        with write_transaction(
            conn,
            immediate=True,
            store="source_ingestion",
            operation="commit_batch",
            rows=len(records),
        ):
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_ingestion_commit_records (
                    source_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    commit_id TEXT NOT NULL,
                    applied_at TEXT NOT NULL,
                    PRIMARY KEY (source_id, record_id)
                )
                """
            )
            for rec in records:
                record_id = str(rec.get("id") or rec.get("record_id") or rec.get("path") or "")
                if not record_id:
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO source_ingestion_commit_records(
                        source_id, record_id, payload_json, commit_id, applied_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        record_id,
                        json.dumps(rec, ensure_ascii=False),
                        intent.commit_id,
                        utc_now(),
                    ),
                )
    finally:
        conn.close()

    return CommitReceipt(
        commit_id=intent.commit_id,
        idempotency_key=intent.idempotency_key,
        domain="source_ingestion",
        operation=intent.operation,
        status=CommitReceiptStatus.APPLIED.value,
        entity_type="source",
        entity_id=source_id,
        payload_hash=intent.payload_hash,
        applied_at=utc_now(),
        record_count=len(records),
        producer_job_id=intent.source_job_id,
        trace_id=intent.trace_id,
        result={"source_id": source_id, "records": len(records)},
    )


def _commit_brain_sync(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    from Data.modules.source_ingestion.store import IngestionStore

    store = IngestionStore(db_path)
    store.initialize()
    source_id = str(payload["source_id"])
    sync = dict(payload.get("sync") or {})
    container = store.get_container(source_id) if hasattr(store, "get_container") else None
    auxiliary_ok = True
    auxiliary_error: str | None = None
    if container is None:
        # No container to update — brain sync metadata is the authoritative contract.
        auxiliary_ok = False
        auxiliary_error = "container_missing"
    elif hasattr(store, "upsert_container"):
        meta = dict(container.get("metadata") or {})
        meta.update(sync)
        meta["last_brain_sync_commit"] = intent.commit_id
        try:
            store.upsert_container(source_id, metadata=meta)
        except TypeError as exc:
            # Signature mismatch still means auxiliary persistence did not apply.
            auxiliary_ok = False
            auxiliary_error = f"upsert_signature_mismatch:{exc}"[:400]
        except Exception as exc:  # noqa: BLE001
            auxiliary_ok = False
            auxiliary_error = str(exc)[:400]
    else:
        auxiliary_ok = False
        auxiliary_error = "upsert_container_unavailable"

    if not auxiliary_ok:
        return CommitReceipt(
            commit_id=intent.commit_id,
            idempotency_key=intent.idempotency_key,
            domain="source_ingestion",
            operation=intent.operation,
            status=CommitReceiptStatus.REJECTED.value,
            entity_type="source",
            entity_id=source_id,
            payload_hash=intent.payload_hash,
            applied_at=utc_now(),
            record_count=0,
            producer_job_id=intent.source_job_id,
            trace_id=intent.trace_id,
            error_code="AUXILIARY_PERSISTENCE_FAILED",
            error_message=auxiliary_error or "brain sync metadata not persisted",
            result={
                "source_id": source_id,
                "brain_sync": False,
                "auxiliary_ok": False,
                "truth": {"false_applied_after_auxiliary_failure": False},
            },
        )

    return CommitReceipt(
        commit_id=intent.commit_id,
        idempotency_key=intent.idempotency_key,
        domain="source_ingestion",
        operation=intent.operation,
        status=CommitReceiptStatus.APPLIED.value,
        entity_type="source",
        entity_id=source_id,
        payload_hash=intent.payload_hash,
        applied_at=utc_now(),
        record_count=1,
        producer_job_id=intent.source_job_id,
        trace_id=intent.trace_id,
        result={"source_id": source_id, "brain_sync": True, "auxiliary_ok": True},
    )
