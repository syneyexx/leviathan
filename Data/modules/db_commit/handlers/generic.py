"""Generic / maintenance / test commit handlers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from Data.modules.common.sqlite_policy import open_sqlite_connection, write_transaction
from Data.modules.db_commit.handlers.registry import FunctionHandler
from Data.modules.db_commit.types import CommitIntent, CommitReceipt, CommitReceiptStatus, utc_now


def handlers() -> list[FunctionHandler]:
    return [
        FunctionHandler(
            operation="maintenance.commit_backfill",
            fn=_commit_backfill,
            required_payload_keys=("rows",),
        ),
        FunctionHandler(
            operation="system.noop",
            fn=_noop,
        ),
        FunctionHandler(
            operation="system.echo_records",
            fn=_echo_records,
            required_payload_keys=("records",),
        ),
    ]


def _commit_backfill(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    rows = list(payload.get("rows") or [])
    table = str(payload.get("table") or "db_commit_backfill_scratch")
    # Only allow a scratch table name for maintenance test/backfill — no arbitrary SQL.
    if not table.replace("_", "").isalnum() or not table.startswith("db_commit_"):
        raise ValueError("maintenance backfill table must be db_commit_* alphanumeric")
    conn = open_sqlite_connection(db_path)
    try:
        with write_transaction(
            conn,
            immediate=True,
            store="maintenance",
            operation="commit_backfill",
            rows=len(rows),
        ):
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL DEFAULT '',
                    applied_at TEXT NOT NULL
                )
                """
            )
            for row in rows:
                row_id = str(row.get("id") or row.get("key") or "")
                if not row_id:
                    continue
                conn.execute(
                    f"INSERT OR REPLACE INTO {table}(id, payload, applied_at) VALUES (?, ?, ?)",
                    (row_id, str(row.get("payload") or ""), utc_now()),
                )
    finally:
        conn.close()
    return CommitReceipt(
        commit_id=intent.commit_id,
        idempotency_key=intent.idempotency_key,
        domain="maintenance",
        operation=intent.operation,
        status=CommitReceiptStatus.APPLIED.value,
        entity_type="backfill",
        entity_id=intent.entity_id or table,
        payload_hash=intent.payload_hash,
        applied_at=utc_now(),
        record_count=len(rows),
        producer_job_id=intent.source_job_id,
        trace_id=intent.trace_id,
        result={"table": table, "rows": len(rows)},
    )


def _noop(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    return CommitReceipt(
        commit_id=intent.commit_id,
        idempotency_key=intent.idempotency_key,
        domain=intent.domain or "system",
        operation=intent.operation,
        status=CommitReceiptStatus.APPLIED.value,
        entity_type=intent.entity_type,
        entity_id=intent.entity_id,
        payload_hash=intent.payload_hash,
        applied_at=utc_now(),
        record_count=0,
        producer_job_id=intent.source_job_id,
        trace_id=intent.trace_id,
        result={"noop": True},
    )


def _echo_records(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    """Test/stress helper: persist idempotent rows into a scratch table."""
    records = list(payload.get("records") or [])
    return _commit_backfill(
        intent,
        {"rows": records, "table": "db_commit_echo_records"},
        db_path,
        settings,
    )
