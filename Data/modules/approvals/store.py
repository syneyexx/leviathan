from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .types import ApprovalRecord, ApprovalStatus


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ApprovalStore:
    """Durable approval records in SQLite."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        from Data.modules.common.sqlite_policy import open_sqlite_connection

        conn = open_sqlite_connection(self.db_path, set_wal=False)
        try:
            yield conn
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            conn.close()


    def initialize(self) -> None:
        from Data.modules.common.sqlite_policy import ensure_wal

        with self.connect() as conn:
            ensure_wal(conn)
            self._ensure_schema(conn)

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS approvals (
                approval_id TEXT PRIMARY KEY,
                capability_id TEXT NOT NULL,
                side_effects_json TEXT NOT NULL,
                status TEXT NOT NULL,
                requested_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                reason TEXT,
                run_id TEXT,
                decided_by TEXT,
                decided_at TEXT,
                expires_at TEXT,
                single_use INTEGER NOT NULL DEFAULT 1,
                arguments_digest TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_approvals_capability_status "
            "ON approvals(capability_id, status)"
        )

    def create(
        self,
        *,
        capability_id: str,
        side_effects: tuple[str, ...] | list[str],
        requested_by: str = "api",
        reason: str | None = None,
        run_id: str | None = None,
        expires_at: str | None = None,
        single_use: bool = True,
        arguments_digest: str | None = None,
        metadata: dict[str, Any] | None = None,
        approval_id: str | None = None,
    ) -> ApprovalRecord:
        record = ApprovalRecord(
            approval_id=approval_id or str(uuid.uuid4()),
            capability_id=capability_id,
            side_effects=tuple(side_effects),
            status=ApprovalStatus.PENDING,
            requested_by=requested_by,
            created_at=utc_now(),
            reason=reason,
            run_id=run_id,
            expires_at=expires_at,
            single_use=single_use,
            arguments_digest=arguments_digest,
            metadata=metadata or {},
        )
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO approvals(
                    approval_id, capability_id, side_effects_json, status, requested_by,
                    created_at, reason, run_id, decided_by, decided_at, expires_at,
                    single_use, arguments_digest, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?)
                """,
                (
                    record.approval_id,
                    record.capability_id,
                    json.dumps(list(record.side_effects)),
                    record.status.value,
                    record.requested_by,
                    record.created_at,
                    record.reason,
                    record.run_id,
                    record.expires_at,
                    1 if record.single_use else 0,
                    record.arguments_digest,
                    json.dumps(record.metadata),
                ),
            )
        return record

    def get(self, approval_id: str) -> ApprovalRecord | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def list(
        self,
        *,
        status: ApprovalStatus | None = None,
        capability_id: str | None = None,
        limit: int = 100,
    ) -> list[ApprovalRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if capability_id is not None:
            clauses.append("capability_id = ?")
            params.append(capability_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 500)))
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                f"SELECT * FROM approvals {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def set_status(
        self,
        approval_id: str,
        status: ApprovalStatus,
        *,
        decided_by: str | None = None,
        reason: str | None = None,
    ) -> ApprovalRecord | None:
        now = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if row is None:
                return None
            current = ApprovalStatus(row["status"])
            if current in {ApprovalStatus.CONSUMED, ApprovalStatus.EXPIRED}:
                raise ValueError(f"Cannot change status of {current.value} approval")
            allowed: dict[ApprovalStatus, set[ApprovalStatus]] = {
                ApprovalStatus.PENDING: {
                    ApprovalStatus.APPROVED,
                    ApprovalStatus.DENIED,
                    ApprovalStatus.EXPIRED,
                },
                ApprovalStatus.APPROVED: {
                    ApprovalStatus.DENIED,
                    ApprovalStatus.EXPIRED,
                    ApprovalStatus.CONSUMED,
                },
                ApprovalStatus.DENIED: {ApprovalStatus.APPROVED, ApprovalStatus.EXPIRED},
            }
            if status not in allowed.get(current, set()):
                raise ValueError(f"Cannot transition approval {current.value} → {status.value}")
            conn.execute(
                """
                UPDATE approvals
                SET status = ?, decided_by = COALESCE(?, decided_by),
                    decided_at = ?, reason = COALESCE(?, reason)
                WHERE approval_id = ?
                """,
                (status.value, decided_by, now, reason, approval_id),
            )
            row = conn.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def consume(self, approval_id: str) -> ApprovalRecord | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if row is None:
                return None
            if row["status"] != ApprovalStatus.APPROVED.value:
                raise ValueError("Only APPROVED approvals can be consumed")
            if not row["single_use"]:
                return self._from_row(row)
            now = utc_now()
            conn.execute(
                """
                UPDATE approvals
                SET status = ?, decided_at = COALESCE(decided_at, ?)
                WHERE approval_id = ?
                """,
                (ApprovalStatus.CONSUMED.value, now, approval_id),
            )
            row = conn.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ApprovalRecord:
        return ApprovalRecord(
            approval_id=row["approval_id"],
            capability_id=row["capability_id"],
            side_effects=tuple(json.loads(row["side_effects_json"])),
            status=ApprovalStatus(row["status"]),
            requested_by=row["requested_by"],
            created_at=row["created_at"],
            reason=row["reason"],
            run_id=row["run_id"],
            decided_by=row["decided_by"],
            decided_at=row["decided_at"],
            expires_at=row["expires_at"],
            single_use=bool(row["single_use"]),
            arguments_digest=row["arguments_digest"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )
