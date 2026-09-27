"""Dataset domain commit handlers."""

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
            operation="dataset.commit_index_batch",
            fn=_commit_index_batch,
            required_payload_keys=("dataset_id", "rows"),
        ),
        FunctionHandler(
            operation="dataset.commit_metadata_batch",
            fn=_commit_metadata_batch,
            required_payload_keys=("dataset_id",),
        ),
    ]


def _commit_index_batch(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    """Persist prepared index rows via canonical DatasetStore metadata + idempotent row table.

    Heavy parse/transform already happened outside the writer. This mutation is bounded.
    """
    from Data.modules.datasets.store import DatasetStore

    store = DatasetStore(db_path)
    store.initialize()
    dataset_id = str(payload["dataset_id"])
    rows = list(payload.get("rows") or [])
    max_rows = int(getattr(settings, "max_batch_rows", 1000) or 1000)
    if intent.batch_count > 1:
        start = int(intent.batch_index) * max_rows
        end = start + max_rows
        rows = rows[start:end]

    conn = open_sqlite_connection(db_path)
    try:
        with write_transaction(
            conn,
            immediate=True,
            store="dataset",
            operation="commit_index_batch",
            rows=len(rows),
        ):
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dataset_commit_index_rows (
                    dataset_id TEXT NOT NULL,
                    row_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    commit_id TEXT NOT NULL,
                    applied_at TEXT NOT NULL,
                    PRIMARY KEY (dataset_id, row_id)
                )
                """
            )
            for row in rows:
                row_id = str(row.get("row_id") or row.get("id") or "")
                if not row_id:
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO dataset_commit_index_rows(
                        dataset_id, row_id, payload_json, commit_id, applied_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        dataset_id,
                        row_id,
                        json.dumps(row, ensure_ascii=False),
                        intent.commit_id,
                        utc_now(),
                    ),
                )
    finally:
        conn.close()

    # Auxiliary dataset metadata touch — same authoritative contract for index commits.
    # TRUTH-002: do not claim APPLIED if this fails when the dataset record exists.
    auxiliary_ok = True
    auxiliary_error: str | None = None
    try:
        if store.get_dataset(dataset_id) is not None:
            store.update_dataset(
                dataset_id,
                metadata={"last_commit_id": intent.commit_id, "last_index_rows": len(rows)},
            )
    except Exception as exc:  # noqa: BLE001
        auxiliary_ok = False
        auxiliary_error = str(exc)[:400]

    if not auxiliary_ok:
        return CommitReceipt(
            commit_id=intent.commit_id,
            idempotency_key=intent.idempotency_key,
            domain="dataset",
            operation=intent.operation,
            status=CommitReceiptStatus.REJECTED.value,
            entity_type="dataset",
            entity_id=dataset_id,
            payload_hash=intent.payload_hash,
            applied_at=utc_now(),
            record_count=len(rows),
            producer_job_id=intent.source_job_id,
            trace_id=intent.trace_id,
            batch_index=intent.batch_index,
            batch_count=intent.batch_count,
            result={
                "dataset_id": dataset_id,
                "rows": len(rows),
                "index_rows_written": True,
                "auxiliary_metadata_ok": False,
                "auxiliary_error": auxiliary_error,
                "truth": {"false_applied_after_auxiliary_failure": False},
            },
        )

    return CommitReceipt(
        commit_id=intent.commit_id,
        idempotency_key=intent.idempotency_key,
        domain="dataset",
        operation=intent.operation,
        status=CommitReceiptStatus.APPLIED.value,
        entity_type="dataset",
        entity_id=dataset_id,
        payload_hash=intent.payload_hash,
        applied_at=utc_now(),
        record_count=len(rows),
        producer_job_id=intent.source_job_id,
        trace_id=intent.trace_id,
        batch_index=intent.batch_index,
        batch_count=intent.batch_count,
        result={
            "dataset_id": dataset_id,
            "rows": len(rows),
            "auxiliary_metadata_ok": True,
        },
    )


def _commit_metadata_batch(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    from Data.modules.datasets.store import DatasetStore

    store = DatasetStore(db_path)
    store.initialize()
    dataset_id = str(payload["dataset_id"])
    meta = dict(payload.get("metadata") or {})
    meta["last_commit_id"] = intent.commit_id
    if store.get_dataset(dataset_id) is not None:
        store.update_dataset(dataset_id, metadata=meta)
    return CommitReceipt(
        commit_id=intent.commit_id,
        idempotency_key=intent.idempotency_key,
        domain="dataset",
        operation=intent.operation,
        status=CommitReceiptStatus.APPLIED.value,
        entity_type="dataset",
        entity_id=dataset_id,
        payload_hash=intent.payload_hash,
        applied_at=utc_now(),
        record_count=1,
        producer_job_id=intent.source_job_id,
        trace_id=intent.trace_id,
        result={"dataset_id": dataset_id},
    )
