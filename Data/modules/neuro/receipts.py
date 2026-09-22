from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .residual import ResidualInjectReceipt


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ResidualReceiptStore:
    """Persist residual inject/forward receipts in the central LEVIATHAN database."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS residual_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    applied INTEGER NOT NULL,
                    implemented INTEGER NOT NULL,
                    degraded_to_chat_completions INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    hook_json TEXT NOT NULL DEFAULT '{}',
                    detail TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )

    def record(self, receipt: ResidualInjectReceipt, *, metadata: dict[str, Any] | None = None) -> str:
        receipt_id = str(uuid.uuid4())
        self.initialize()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO residual_receipts(
                    receipt_id, created_at, mode, applied, implemented,
                    degraded_to_chat_completions, reason, hook_json, detail, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    utc_now(),
                    receipt.mode,
                    1 if receipt.applied else 0,
                    1 if receipt.implemented else 0,
                    1 if receipt.degraded_to_chat_completions else 0,
                    receipt.reason or receipt.detail,
                    json.dumps(receipt.hook.public_dict()),
                    receipt.detail,
                    json.dumps(metadata or {}),
                ),
            )
        return receipt_id

    def recent(self, *, limit: int = 20) -> list[dict[str, Any]]:
        self.initialize()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM residual_receipts
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [
            {
                "receipt_id": row["receipt_id"],
                "created_at": row["created_at"],
                "mode": row["mode"],
                "applied": bool(row["applied"]),
                "implemented": bool(row["implemented"]),
                "degraded_to_chat_completions": bool(row["degraded_to_chat_completions"]),
                "reason": row["reason"],
                "hook": json.loads(row["hook_json"] or "{}"),
                "detail": row["detail"],
                "metadata": json.loads(row["metadata_json"] or "{}"),
                "truth": {"unapplied_is_not_success": True},
            }
            for row in rows
        ]
