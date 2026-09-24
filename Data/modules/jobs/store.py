from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .budgets import ResourceBudgetEnvelope
from .leases import LeaseState, WorkerLease, WorkerProtocolInfo
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
        cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        alters = {
            "trace_id": "ALTER TABLE jobs ADD COLUMN trace_id TEXT",
            "idempotency_key": "ALTER TABLE jobs ADD COLUMN idempotency_key TEXT",
            "lease_owner": "ALTER TABLE jobs ADD COLUMN lease_owner TEXT",
            "lease_expires_at": "ALTER TABLE jobs ADD COLUMN lease_expires_at TEXT",
            "last_heartbeat_at": "ALTER TABLE jobs ADD COLUMN last_heartbeat_at TEXT",
            "attempt_number": "ALTER TABLE jobs ADD COLUMN attempt_number INTEGER NOT NULL DEFAULT 1",
            "budget_json": "ALTER TABLE jobs ADD COLUMN budget_json TEXT NOT NULL DEFAULT '{}'",
            "latency_class": (
                "ALTER TABLE jobs ADD COLUMN latency_class TEXT NOT NULL DEFAULT 'background'"
            ),
        }
        for name, sql in alters.items():
            if name not in cols:
                conn.execute(sql)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idempotency "
            "ON jobs(idempotency_key) WHERE idempotency_key IS NOT NULL"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_lease_expires ON jobs(lease_expires_at, state)"
        )

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
        trace_id: str | None = None,
        idempotency_key: str | None = None,
        budget: dict[str, Any] | ResourceBudgetEnvelope | None = None,
        latency_class: str = "background",
        attempt_number: int = 1,
    ) -> JobRecord:
        if idempotency_key:
            existing = self.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing

        now = utc_now()
        budget_dict: dict[str, Any]
        if isinstance(budget, ResourceBudgetEnvelope):
            budget_dict = budget.public_dict()
        else:
            budget_dict = dict(budget or {})
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
            trace_id=trace_id,
            idempotency_key=idempotency_key,
            attempt_number=max(1, int(attempt_number)),
            budget=budget_dict,
            latency_class=latency_class or "background",
        )
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO jobs(
                    job_id, capability_id, arguments_json, state, run_id, approval_id,
                    requested_by, result_json, error, metadata_json, created_at, updated_at,
                    trace_id, idempotency_key, lease_owner, lease_expires_at, last_heartbeat_at,
                    attempt_number, budget_json, latency_class
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?)
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
                    record.trace_id,
                    record.idempotency_key,
                    record.attempt_number,
                    json.dumps(record.budget),
                    record.latency_class,
                ),
            )
        return record

    def get(self, job_id: str) -> JobRecord | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._from_row(row) if row else None

    def get_by_idempotency_key(self, idempotency_key: str) -> JobRecord | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM jobs WHERE idempotency_key = ? LIMIT 1",
                (idempotency_key,),
            ).fetchone()
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

    def claim_next_queued(
        self,
        *,
        capability_ids: set[str] | frozenset[str] | None = None,
        exclude_capability_ids: set[str] | frozenset[str] | None = None,
    ) -> JobRecord | None:
        """Atomically move the oldest matching QUEUED job to RUNNING.

        ``capability_ids`` — only claim these capabilities (external workers).
        ``exclude_capability_ids`` — skip these (API JobRuntime vs domain workers).
        """
        with self.connect() as conn:
            self._ensure_schema(conn)
            sql = "SELECT * FROM jobs WHERE state = ?"
            params: list[Any] = [JobState.QUEUED.value]
            if capability_ids:
                placeholders = ",".join("?" for _ in capability_ids)
                sql += f" AND capability_id IN ({placeholders})"
                params.extend(sorted(capability_ids))
            if exclude_capability_ids:
                placeholders = ",".join("?" for _ in exclude_capability_ids)
                sql += f" AND capability_id NOT IN ({placeholders})"
                params.extend(sorted(exclude_capability_ids))
            sql += " ORDER BY created_at ASC LIMIT 1"
            row = conn.execute(sql, params).fetchone()
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

    def acquire_lease(
        self,
        job_id: str,
        *,
        worker_id: str,
        ttl_seconds: float = 30.0,
        protocol: WorkerProtocolInfo | None = None,
    ) -> WorkerLease:
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=max(1.0, float(ttl_seconds)))
        now_s = now.isoformat(timespec="seconds")
        expires_s = expires.isoformat(timespec="seconds")
        proto = protocol or WorkerProtocolInfo()
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown job: {job_id}")
            owner = row["lease_owner"] if "lease_owner" in row.keys() else None
            expires_at = row["lease_expires_at"] if "lease_expires_at" in row.keys() else None
            if owner and owner != worker_id and expires_at:
                try:
                    exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                    if exp_dt.tzinfo is None:
                        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                    if now < exp_dt:
                        raise ValueError(f"Lease held by {owner} until {expires_at}")
                except ValueError as exc:
                    if "Lease held" in str(exc):
                        raise
            conn.execute(
                """
                UPDATE jobs
                SET lease_owner = ?, lease_expires_at = ?, last_heartbeat_at = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (worker_id, expires_s, now_s, now_s, job_id),
            )
        return WorkerLease(
            job_id=job_id,
            worker_id=worker_id,
            state=LeaseState.HELD,
            leased_at=now_s,
            expires_at=expires_s,
            last_heartbeat_at=now_s,
            protocol=proto,
        )

    def heartbeat_lease(
        self,
        job_id: str,
        *,
        worker_id: str,
        ttl_seconds: float = 30.0,
    ) -> WorkerLease:
        job = self.get(job_id)
        if job is None:
            raise KeyError(f"Unknown job: {job_id}")
        if job.lease_owner and job.lease_owner != worker_id:
            raise ValueError(f"Lease owned by {job.lease_owner}, not {worker_id}")
        return self.acquire_lease(job_id, worker_id=worker_id, ttl_seconds=ttl_seconds)

    def release_lease(self, job_id: str, *, worker_id: str | None = None) -> None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            if worker_id:
                conn.execute(
                    """
                    UPDATE jobs
                    SET lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
                    WHERE job_id = ? AND lease_owner = ?
                    """,
                    (utc_now(), job_id, worker_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE jobs
                    SET lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
                    WHERE job_id = ?
                    """,
                    (utc_now(), job_id),
                )

    def list_expired_leases(self, *, now: datetime | None = None) -> list[JobRecord]:
        current = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT * FROM jobs
                WHERE state = ?
                  AND lease_owner IS NOT NULL
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= ?
                ORDER BY lease_expires_at ASC
                """,
                (JobState.RUNNING.value, current),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> JobRecord:
        keys = set(row.keys())
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
            trace_id=row["trace_id"] if "trace_id" in keys else None,
            idempotency_key=row["idempotency_key"] if "idempotency_key" in keys else None,
            lease_owner=row["lease_owner"] if "lease_owner" in keys else None,
            lease_expires_at=row["lease_expires_at"] if "lease_expires_at" in keys else None,
            last_heartbeat_at=row["last_heartbeat_at"] if "last_heartbeat_at" in keys else None,
            attempt_number=int(row["attempt_number"])
            if "attempt_number" in keys and row["attempt_number"] is not None
            else 1,
            budget=json.loads(row["budget_json"] or "{}") if "budget_json" in keys else {},
            latency_class=row["latency_class"]
            if "latency_class" in keys and row["latency_class"]
            else "background",
        )


# Re-export for callers that need the exception from store imports.
__all__ = ["InvalidJobTransition", "JobStore", "utc_now"]
