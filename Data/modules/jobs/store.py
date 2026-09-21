from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .states import InvalidJobTransition, JobState, validate_job_transition
from .types import JobRecord


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobStore:
    """SQLite-backed job persistence with validated state transitions."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            self._ensure_schema(conn)

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                capability_id TEXT NOT NULL,
                arguments_json TEXT NOT NULL,
                state TEXT NOT NULL,
                run_id TEXT,
                approval_id TEXT,
                requested_by TEXT NOT NULL,
                result_json TEXT,
                error TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state, created_at)")

    def create(
        self,
        *,
        capability_id: str,
        arguments: dict[str, Any] | None = None,
        run_id: str | None = None,
        approval_id: str | None = None,
        requested_by: str = "api",
        metadata: dict[str, Any] | None = None,
        job_id: str | None = None,
    ) -> JobRecord:
        now = utc_now()
        record = JobRecord(
            job_id=job_id or str(uuid.uuid4()),
            capability_id=capability_id,
            arguments=dict(arguments or {}),
            state=JobState.CREATED,
            created_at=now,
            updated_at=now,
            run_id=run_id,
            approval_id=approval_id,
            requested_by=requested_by,
            metadata=metadata or {},
        )
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO jobs(
                    job_id, capability_id, arguments_json, state, run_id, approval_id,
                    requested_by, result_json, error, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)
                """,
                (
                    record.job_id,
                    record.capability_id,
                    json.dumps(record.arguments),
                    record.state.value,
                    record.run_id,
                    record.approval_id,
                    record.requested_by,
                    json.dumps(record.metadata),
                    record.created_at,
                    record.updated_at,
                ),
            )
        return record

    def get(self, job_id: str) -> JobRecord | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._from_row(row) if row else None

    def list(
        self,
        *,
        state: JobState | None = None,
        limit: int = 100,
    ) -> list[JobRecord]:
        params: list[Any] = []
        where = ""
        if state is not None:
            where = "WHERE state = ?"
            params.append(state.value)
        params.append(max(1, min(limit, 500)))
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def transition(
        self,
        job_id: str,
        new_state: JobState,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        metadata_update: dict[str, Any] | None = None,
    ) -> JobRecord:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown job: {job_id}")
            current = JobState(row["state"])
            validate_job_transition(current, new_state)
            metadata = json.loads(row["metadata_json"] or "{}")
            if metadata_update:
                metadata.update(metadata_update)
            now = utc_now()
            result_json = json.dumps(result) if result is not None else row["result_json"]
            error_value = error if error is not None else row["error"]
            conn.execute(
                """
                UPDATE jobs
                SET state = ?, result_json = ?, error = ?, metadata_json = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (new_state.value, result_json, error_value, json.dumps(metadata), now, job_id),
            )
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        assert row is not None
        return self._from_row(row)

    def claim_next_queued(self) -> JobRecord | None:
        """Atomically move the oldest QUEUED job to RUNNING."""
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                """
                SELECT * FROM jobs
                WHERE state = ?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (JobState.QUEUED.value,),
            ).fetchone()
            if row is None:
                return None
            validate_job_transition(JobState.QUEUED, JobState.RUNNING)
            now = utc_now()
            conn.execute(
                "UPDATE jobs SET state = ?, updated_at = ? WHERE job_id = ? AND state = ?",
                (JobState.RUNNING.value, now, row["job_id"], JobState.QUEUED.value),
            )
            changed = conn.execute("SELECT changes()").fetchone()[0]
            if not changed:
                return None
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (row["job_id"],),
            ).fetchone()
        return self._from_row(row) if row else None

    @staticmethod
    def _from_row(row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            job_id=row["job_id"],
            capability_id=row["capability_id"],
            arguments=json.loads(row["arguments_json"] or "{}"),
            state=JobState(row["state"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            run_id=row["run_id"],
            approval_id=row["approval_id"],
            requested_by=row["requested_by"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=row["error"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )


# Re-export for callers that need the exception from store imports.
__all__ = ["InvalidJobTransition", "JobStore", "utc_now"]
