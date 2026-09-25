"""Canonical commit_receipts persistence in the main SQLite database."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from Data.modules.common.sqlite_policy import (
    open_sqlite_connection,
    run_with_busy_retry,
    write_transaction,
)

from .types import CommitReceipt, CommitReceiptStatus, utc_now


class CommitReceiptStore:
    """Idempotency + applied receipts — same canonical DB, never a second DB."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        def _once() -> None:
            conn = open_sqlite_connection(self.db_path, set_wal=False)
            try:
                self.ensure_schema(conn)
                conn.commit()
            finally:
                conn.close()

        run_with_busy_retry(_once)

    def ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS commit_receipts (
                commit_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                domain TEXT NOT NULL,
                operation TEXT NOT NULL,
                entity_type TEXT NOT NULL DEFAULT '',
                entity_id TEXT NOT NULL DEFAULT '',
                payload_hash TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                applied_at TEXT NOT NULL,
                record_count INTEGER NOT NULL DEFAULT 0,
                result_ref TEXT NOT NULL DEFAULT '',
                producer_job_id TEXT NOT NULL DEFAULT '',
                trace_id TEXT NOT NULL DEFAULT '',
                batch_index INTEGER NOT NULL DEFAULT 0,
                batch_count INTEGER NOT NULL DEFAULT 1,
                result_json TEXT NOT NULL DEFAULT '{}',
                error_code TEXT NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS commit_batches (
                commit_id TEXT NOT NULL,
                batch_index INTEGER NOT NULL,
                batch_count INTEGER NOT NULL,
                batch_hash TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                applied_at TEXT NOT NULL,
                record_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (commit_id, batch_index)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_commit_receipts_domain "
            "ON commit_receipts(domain, applied_at)"
        )

    def get_by_commit_id(self, commit_id: str) -> CommitReceipt | None:
        conn = open_sqlite_connection(self.db_path)
        try:
            self.ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM commit_receipts WHERE commit_id = ?",
                (commit_id,),
            ).fetchone()
            return self._row_to_receipt(row) if row else None
        finally:
            conn.close()

    def get_by_idempotency_key(self, key: str) -> CommitReceipt | None:
        if not key:
            return None
        conn = open_sqlite_connection(self.db_path)
        try:
            self.ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM commit_receipts WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
            return self._row_to_receipt(row) if row else None
        finally:
            conn.close()

    def persist(self, receipt: CommitReceipt, *, conn: sqlite3.Connection | None = None) -> None:
        owns = conn is None
        if owns:
            conn = open_sqlite_connection(self.db_path)
        assert conn is not None
        try:
            self.ensure_schema(conn)
            if owns:
                with write_transaction(
                    conn,
                    immediate=True,
                    store="db_commit",
                    operation="persist_receipt",
                ):
                    self._insert(conn, receipt)
            else:
                self._insert(conn, receipt)
        finally:
            if owns:
                conn.close()

    def mark_batch_applied(
        self,
        conn: sqlite3.Connection,
        *,
        commit_id: str,
        batch_index: int,
        batch_count: int,
        batch_hash: str = "",
        record_count: int = 0,
    ) -> None:
        self.ensure_schema(conn)
        conn.execute(
            """
            INSERT OR REPLACE INTO commit_batches(
                commit_id, batch_index, batch_count, batch_hash,
                status, applied_at, record_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                commit_id,
                int(batch_index),
                int(batch_count),
                batch_hash or "",
                CommitReceiptStatus.APPLIED.value,
                utc_now(),
                int(record_count),
            ),
        )

    def applied_batch_indexes(self, commit_id: str) -> set[int]:
        conn = open_sqlite_connection(self.db_path)
        try:
            self.ensure_schema(conn)
            rows = conn.execute(
                "SELECT batch_index FROM commit_batches WHERE commit_id = ? AND status = ?",
                (commit_id, CommitReceiptStatus.APPLIED.value),
            ).fetchall()
            return {int(r["batch_index"]) for r in rows}
        finally:
            conn.close()

    def _insert(self, conn: sqlite3.Connection, receipt: CommitReceipt) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO commit_receipts(
                commit_id, idempotency_key, domain, operation,
                entity_type, entity_id, payload_hash, status, applied_at,
                record_count, result_ref, producer_job_id, trace_id,
                batch_index, batch_count, result_json, error_code, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt.commit_id,
                receipt.idempotency_key,
                receipt.domain,
                receipt.operation,
                receipt.entity_type,
                receipt.entity_id,
                receipt.payload_hash,
                receipt.status,
                receipt.applied_at or utc_now(),
                int(receipt.record_count),
                receipt.result_ref,
                receipt.producer_job_id,
                receipt.trace_id,
                int(receipt.batch_index),
                int(receipt.batch_count),
                json.dumps(receipt.result or {}, ensure_ascii=False),
                receipt.error_code,
                receipt.error_message,
            ),
        )

    @staticmethod
    def _row_to_receipt(row: sqlite3.Row) -> CommitReceipt:
        result: dict[str, Any] = {}
        raw = row["result_json"] if "result_json" in row.keys() else "{}"
        try:
            parsed = json.loads(raw or "{}")
            if isinstance(parsed, dict):
                result = parsed
        except json.JSONDecodeError:
            result = {}
        return CommitReceipt(
            commit_id=str(row["commit_id"]),
            idempotency_key=str(row["idempotency_key"]),
            domain=str(row["domain"]),
            operation=str(row["operation"]),
            status=str(row["status"]),
            entity_type=str(row["entity_type"] or ""),
            entity_id=str(row["entity_id"] or ""),
            payload_hash=str(row["payload_hash"] or ""),
            applied_at=str(row["applied_at"] or ""),
            record_count=int(row["record_count"] or 0),
            result_ref=str(row["result_ref"] or ""),
            producer_job_id=str(row["producer_job_id"] or ""),
            trace_id=str(row["trace_id"] or ""),
            batch_index=int(row["batch_index"] or 0),
            batch_count=int(row["batch_count"] or 1),
            result=result,
            error_code=str(row["error_code"] or ""),
            error_message=str(row["error_message"] or ""),
        )
