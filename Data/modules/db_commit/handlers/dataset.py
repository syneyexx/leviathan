"""Dataset domain commit handlers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from Data.backend.db_upgrade import apply_wave3_canonical_ddl
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


def _datasets_table_exists(conn: Any) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='datasets' LIMIT 1"
    ).fetchone()
    return row is not None


def _merge_dataset_metadata_on_conn(
    conn: Any,
    dataset_id: str,
    *,
    commit_id: str,
    row_count: int,
) -> bool:
    """Update datasets.metadata_json on the open connection. Returns True if row touched."""
    if not _datasets_table_exists(conn):
        return False
    row = conn.execute(
        "SELECT metadata_json FROM datasets WHERE dataset_id = ?",
        (dataset_id,),
    ).fetchone()
    if row is None:
        return False
    raw = row[0] if not hasattr(row, "keys") else row["metadata_json"]
    try:
        meta = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    meta["last_commit_id"] = commit_id
    meta["last_index_rows"] = row_count
    conn.execute(
        "UPDATE datasets SET metadata_json = ?, updated_at = ? WHERE dataset_id = ?",
        (json.dumps(meta, ensure_ascii=False), utc_now(), dataset_id),
    )
    return True


def _commit_index_batch(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    """Persist prepared index rows via canonical DatasetStore metadata + idempotent row table.

    Heavy parse/transform already happened outside the writer. This mutation is bounded.

    WAVE 25 — receipt truth:
    - Same-DB primary + auxiliary metadata share one transaction when possible.
    - Never return REJECTED after a durable primary write; use PARTIAL /
      FAILED_AFTER_PARTIAL_COMMIT (or roll back so nothing is durable).
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

    # Failure-injection hooks (tests only).
    force_aux_fail_in_txn = bool(payload.get("_fail_aux_in_transaction"))
    force_aux_fail_after_primary = bool(payload.get("_fail_aux_after_primary_commit"))

    written_rows = 0
    auxiliary_ok = True
    auxiliary_error: str | None = None
    primary_durable = False
    aux_applied_in_txn = False

    conn = open_sqlite_connection(db_path)
    try:
        with write_transaction(
            conn,
            immediate=True,
            store="dataset",
            operation="commit_index_batch",
            rows=len(rows),
        ):
            apply_wave3_canonical_ddl(conn, "dataset_commit_index_rows")
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
                written_rows += 1
            # Same-DB auxiliary metadata in the same transaction.
            try:
                if force_aux_fail_in_txn:
                    raise RuntimeError("injected_aux_failure_in_transaction")
                aux_applied_in_txn = _merge_dataset_metadata_on_conn(
                    conn,
                    dataset_id,
                    commit_id=intent.commit_id,
                    row_count=written_rows,
                )
            except Exception as exc:  # noqa: BLE001
                # Roll back with the transaction — nothing durable yet.
                raise RuntimeError(f"auxiliary_metadata_failed:{exc}") from exc
        primary_durable = True
    except Exception as exc:  # noqa: BLE001
        # Transaction rolled back — honest REJECTED (no durable primary).
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
            record_count=0,
            producer_job_id=intent.source_job_id,
            trace_id=intent.trace_id,
            batch_index=intent.batch_index,
            batch_count=intent.batch_count,
            error_code="COMMIT_TRANSACTION_FAILED",
            error_message=str(exc)[:400],
            result={
                "dataset_id": dataset_id,
                "index_rows_written": False,
                "rolled_back": True,
                "truth": {"false_applied_after_auxiliary_failure": False},
            },
        )
    finally:
        conn.close()

    # Post-commit aux only when same-txn could not touch datasets (or injection).
    if force_aux_fail_after_primary:
        auxiliary_ok = False
        auxiliary_error = "injected_aux_failure_after_primary_commit"
    elif not aux_applied_in_txn:
        try:
            if store.get_dataset(dataset_id) is not None:
                existing = store.get_dataset(dataset_id)
                meta = dict(getattr(existing, "metadata", None) or {})
                meta["last_commit_id"] = intent.commit_id
                meta["last_index_rows"] = written_rows
                store.update_dataset(dataset_id, metadata=meta)
        except Exception as exc:  # noqa: BLE001
            auxiliary_ok = False
            auxiliary_error = str(exc)[:400]

    if not auxiliary_ok:
        # Primary index rows are already durable — never REJECTED.
        assert primary_durable
        return CommitReceipt(
            commit_id=intent.commit_id,
            idempotency_key=intent.idempotency_key,
            domain="dataset",
            operation=intent.operation,
            status=CommitReceiptStatus.FAILED_AFTER_PARTIAL_COMMIT.value,
            entity_type="dataset",
            entity_id=dataset_id,
            payload_hash=intent.payload_hash,
            applied_at=utc_now(),
            record_count=written_rows,
            producer_job_id=intent.source_job_id,
            trace_id=intent.trace_id,
            batch_index=intent.batch_index,
            batch_count=intent.batch_count,
            error_code="FAILED_AFTER_PARTIAL_COMMIT",
            error_message=auxiliary_error or "auxiliary metadata failed after primary",
            result={
                "dataset_id": dataset_id,
                "rows": written_rows,
                "index_rows_written": True,
                "auxiliary_metadata_ok": False,
                "auxiliary_error": auxiliary_error,
                "partial_status": CommitReceiptStatus.PARTIAL.value,
                "truth": {
                    "false_applied_after_auxiliary_failure": False,
                    "rejected_after_durable_primary": False,
                },
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
        record_count=written_rows,
        producer_job_id=intent.source_job_id,
        trace_id=intent.trace_id,
        batch_index=intent.batch_index,
        batch_count=intent.batch_count,
        result={
            "dataset_id": dataset_id,
            "rows": written_rows,
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
