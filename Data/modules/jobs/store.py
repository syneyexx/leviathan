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
from .priority import PRIORITY_DEFAULT, priority_for_latency_class
from .states import TERMINAL_JOB_STATES, InvalidJobTransition, JobState, validate_job_transition
from .types import JobRecord


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _row_get(row: sqlite3.Row, key: str, default: Any = None) -> Any:
    keys = set(row.keys())
    if key not in keys:
        return default
    value = row[key]
    return default if value is None and default is not None else value


_FABRIC_COLUMNS: dict[str, str] = {
    "domain": "ALTER TABLE jobs ADD COLUMN domain TEXT",
    "consumer": "ALTER TABLE jobs ADD COLUMN consumer TEXT",
    "correlation_id": "ALTER TABLE jobs ADD COLUMN correlation_id TEXT",
    "root_job_id": "ALTER TABLE jobs ADD COLUMN root_job_id TEXT",
    "parent_job_id": "ALTER TABLE jobs ADD COLUMN parent_job_id TEXT",
    "domain_entity_type": "ALTER TABLE jobs ADD COLUMN domain_entity_type TEXT",
    "domain_entity_id": "ALTER TABLE jobs ADD COLUMN domain_entity_id TEXT",
    "worker_pool": "ALTER TABLE jobs ADD COLUMN worker_pool TEXT",
    "resource_class": "ALTER TABLE jobs ADD COLUMN resource_class TEXT",
    "priority": "ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 100",
    "queued_at": "ALTER TABLE jobs ADD COLUMN queued_at TEXT",
    "claimed_at": "ALTER TABLE jobs ADD COLUMN claimed_at TEXT",
    "started_at": "ALTER TABLE jobs ADD COLUMN started_at TEXT",
    "finished_at": "ALTER TABLE jobs ADD COLUMN finished_at TEXT",
    "max_attempts": "ALTER TABLE jobs ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 3",
    "next_attempt_at": "ALTER TABLE jobs ADD COLUMN next_attempt_at TEXT",
    "timeout_seconds": "ALTER TABLE jobs ADD COLUMN timeout_seconds REAL",
    "deadline_at": "ALTER TABLE jobs ADD COLUMN deadline_at TEXT",
    "cancel_requested_at": "ALTER TABLE jobs ADD COLUMN cancel_requested_at TEXT",
    "cancel_reason": "ALTER TABLE jobs ADD COLUMN cancel_reason TEXT",
    "progress": "ALTER TABLE jobs ADD COLUMN progress REAL",
    "phase": "ALTER TABLE jobs ADD COLUMN phase TEXT",
    "message": "ALTER TABLE jobs ADD COLUMN message TEXT",
    "resource_request_json": (
        "ALTER TABLE jobs ADD COLUMN resource_request_json TEXT NOT NULL DEFAULT '{}'"
    ),
    "result_summary_json": "ALTER TABLE jobs ADD COLUMN result_summary_json TEXT",
    "artifact_refs_json": (
        "ALTER TABLE jobs ADD COLUMN artifact_refs_json TEXT NOT NULL DEFAULT '[]'"
    ),
    "error_code": "ALTER TABLE jobs ADD COLUMN error_code TEXT",
    "retryable": "ALTER TABLE jobs ADD COLUMN retryable INTEGER",
}


class JobStore:
    """SQLite-backed job persistence with validated state transitions."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        from Data.modules.common.sqlite_policy import open_sqlite_connection

        # Hot path: busy_timeout yes; journal_mode is set during initialize/migration.
        conn = open_sqlite_connection(self.path, set_wal=False)
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
            **_FABRIC_COLUMNS,
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
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_runnable "
            "ON jobs(state, priority, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_next_attempt ON jobs(next_attempt_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_parent ON jobs(parent_job_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_worker_pool ON jobs(worker_pool, state)"
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
        domain: str | None = None,
        consumer: str | None = None,
        correlation_id: str | None = None,
        root_job_id: str | None = None,
        parent_job_id: str | None = None,
        domain_entity_type: str | None = None,
        domain_entity_id: str | None = None,
        worker_pool: str | None = None,
        resource_class: str | None = None,
        priority: int | None = None,
        max_attempts: int = 3,
        timeout_seconds: float | None = None,
        deadline_at: str | None = None,
        resource_request: dict[str, Any] | None = None,
        phase: str | None = None,
        message: str | None = None,
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
        resolved_priority = (
            int(priority)
            if priority is not None
            else priority_for_latency_class(latency_class)
        )
        jid = job_id or str(uuid.uuid4())
        record = JobRecord(
            job_id=jid,
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
            domain=domain,
            consumer=consumer,
            correlation_id=correlation_id,
            root_job_id=root_job_id or jid,
            parent_job_id=parent_job_id,
            domain_entity_type=domain_entity_type,
            domain_entity_id=domain_entity_id,
            worker_pool=worker_pool,
            resource_class=resource_class,
            priority=resolved_priority if resolved_priority else PRIORITY_DEFAULT,
            max_attempts=max(1, int(max_attempts)),
            timeout_seconds=timeout_seconds,
            deadline_at=deadline_at,
            resource_request=dict(resource_request or {}),
            phase=phase,
            message=message,
        )
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO jobs(
                    job_id, capability_id, arguments_json, state, run_id, approval_id,
                    requested_by, result_json, error, metadata_json, created_at, updated_at,
                    trace_id, idempotency_key, lease_owner, lease_expires_at, last_heartbeat_at,
                    attempt_number, budget_json, latency_class,
                    domain, consumer, correlation_id, root_job_id, parent_job_id,
                    domain_entity_type, domain_entity_id, worker_pool, resource_class,
                    priority, queued_at, claimed_at, started_at, finished_at,
                    max_attempts, next_attempt_at, timeout_seconds, deadline_at,
                    cancel_requested_at, cancel_reason, progress, phase, message,
                    resource_request_json, result_summary_json, artifact_refs_json,
                    error_code, retryable
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?,
                    ?, ?, NULL, NULL, NULL,
                    ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, NULL, NULL, NULL, NULL,
                    ?, NULL, ?, ?,
                    NULL, NULL, NULL, ?, ?,
                    ?, NULL, ?,
                    NULL, NULL
                )
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
                    record.domain,
                    record.consumer,
                    record.correlation_id,
                    record.root_job_id,
                    record.parent_job_id,
                    record.domain_entity_type,
                    record.domain_entity_id,
                    record.worker_pool,
                    record.resource_class,
                    record.priority,
                    record.max_attempts,
                    record.timeout_seconds,
                    record.deadline_at,
                    record.phase,
                    record.message,
                    json.dumps(record.resource_request),
                    json.dumps(record.artifact_refs),
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

    def list_children(self, parent_job_id: str, *, limit: int = 100) -> list[JobRecord]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT * FROM jobs
                WHERE parent_job_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (parent_job_id, max(1, min(limit, 500))),
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
        error_code: str | None = None,
        retryable: bool | None = None,
        result_summary: dict[str, Any] | None = None,
        expected_lease_owner: str | None = None,
    ) -> JobRecord:
        """Transition job state.

        When ``expected_lease_owner`` is set, the UPDATE is fenced: it only
        succeeds if the row is still in ``current`` state **and** ``lease_owner``
        matches. A stale worker that lost its lease cannot complete or fail the job.
        """
        from .states import StaleLeaseError

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
            queued_at = _row_get(row, "queued_at")
            finished_at = _row_get(row, "finished_at")
            if new_state == JobState.QUEUED and not queued_at:
                queued_at = now
            if new_state in TERMINAL_JOB_STATES:
                finished_at = now
            next_error_code = (
                error_code if error_code is not None else _row_get(row, "error_code")
            )
            if retryable is None:
                retryable_sql = _row_get(row, "retryable")
            else:
                retryable_sql = int(bool(retryable))
            summary_json = (
                json.dumps(result_summary)
                if result_summary is not None
                else _row_get(row, "result_summary_json")
            )
            params: list[Any] = [
                new_state.value,
                result_json,
                error_value,
                json.dumps(metadata),
                now,
                queued_at,
                finished_at,
                next_error_code,
                retryable_sql,
                summary_json,
                job_id,
                current.value,
            ]
            where = "job_id = ? AND state = ?"
            if expected_lease_owner is not None:
                where += " AND lease_owner = ?"
                params.append(expected_lease_owner)
            cursor = conn.execute(
                f"""
                UPDATE jobs
                SET state = ?, result_json = ?, error = ?, metadata_json = ?, updated_at = ?,
                    queued_at = ?, finished_at = ?, error_code = ?, retryable = ?,
                    result_summary_json = ?
                WHERE {where}
                """,
                params,
            )
            if cursor.rowcount == 0:
                if expected_lease_owner is not None:
                    raise StaleLeaseError(
                        f"Stale lease fence: job {job_id} not owned by {expected_lease_owner!r} "
                        f"in state {current.value}",
                        job_id=job_id,
                        worker_id=expected_lease_owner,
                    )
                raise InvalidJobTransition(
                    f"Job {job_id} state changed concurrently (expected {current.value})"
                )
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        assert row is not None
        return self._from_row(row)

    def claim_next_queued(
        self,
        *,
        worker_id: str = "job-runtime-local",
        lease_ttl_seconds: float = 30.0,
        capability_ids: set[str] | frozenset[str] | None = None,
        exclude_capability_ids: set[str] | frozenset[str] | None = None,
        worker_pool: str | None = None,
        reclaim_expired: bool = False,
    ) -> JobRecord | None:
        """Atomically claim the next runnable job and attach a worker lease.

        Eligible: QUEUED, RETRY_WAIT with ``next_attempt_at <= now``, and optionally
        RUNNING jobs whose lease has expired (takeover). Expired ``deadline_at`` jobs
        are failed instead of claimed.
        """
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat(timespec="milliseconds")
        ttl = max(1.0, float(lease_ttl_seconds))
        expires = (now_dt + timedelta(seconds=ttl)).isoformat(timespec="milliseconds")

        with self.connect() as conn:
            self._ensure_schema(conn)
            # Fail past-deadline runnable jobs first.
            self._fail_expired_deadlines(conn, now=now)

            filters: list[str] = []
            params: list[Any] = []
            state_clauses = [
                "state = ?",
                "(state = ? AND (next_attempt_at IS NULL OR next_attempt_at <= ?))",
            ]
            params.extend([JobState.QUEUED.value, JobState.RETRY_WAIT.value, now])
            if reclaim_expired:
                state_clauses.append(
                    "(state = ? AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?)"
                )
                params.extend([JobState.RUNNING.value, now])
            filters.append("(" + " OR ".join(state_clauses) + ")")

            if capability_ids:
                placeholders = ",".join("?" for _ in capability_ids)
                filters.append(f"capability_id IN ({placeholders})")
                params.extend(sorted(capability_ids))
            if exclude_capability_ids:
                placeholders = ",".join("?" for _ in exclude_capability_ids)
                filters.append(f"capability_id NOT IN ({placeholders})")
                params.extend(sorted(exclude_capability_ids))
            if worker_pool is not None:
                filters.append("(worker_pool IS NULL OR worker_pool = ?)")
                params.append(worker_pool)

            where = " AND ".join(filters)
            # Prefer higher priority (lower number), then aging (created_at ASC).
            sql = (
                f"SELECT * FROM jobs WHERE {where} "
                "ORDER BY priority ASC, created_at ASC LIMIT 8"
            )
            candidates = conn.execute(sql, params).fetchall()
            claimed: sqlite3.Row | None = None
            for row in candidates:
                job_id = row["job_id"]
                current = JobState(row["state"])
                from_retry = current == JobState.RETRY_WAIT
                attempt = int(_row_get(row, "attempt_number", 1) or 1)
                if from_retry:
                    attempt = attempt + 1
                if current in {JobState.QUEUED, JobState.RETRY_WAIT}:
                    validate_job_transition(current, JobState.RUNNING)
                    cursor = conn.execute(
                        """
                        UPDATE jobs
                        SET state = ?, updated_at = ?, lease_owner = ?, lease_expires_at = ?,
                            last_heartbeat_at = ?, claimed_at = ?, started_at = COALESCE(started_at, ?),
                            attempt_number = ?, next_attempt_at = NULL,
                            queued_at = COALESCE(queued_at, ?)
                        WHERE job_id = ? AND state = ?
                        """,
                        (
                            JobState.RUNNING.value,
                            now,
                            worker_id,
                            expires,
                            now,
                            now,
                            now,
                            attempt,
                            now,
                            job_id,
                            current.value,
                        ),
                    )
                else:
                    # Takeover of expired RUNNING lease — state stays RUNNING.
                    cursor = conn.execute(
                        """
                        UPDATE jobs
                        SET updated_at = ?, lease_owner = ?, lease_expires_at = ?,
                            last_heartbeat_at = ?, claimed_at = ?
                        WHERE job_id = ? AND state = ?
                          AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?
                        """,
                        (
                            now,
                            worker_id,
                            expires,
                            now,
                            now,
                            job_id,
                            JobState.RUNNING.value,
                            now,
                        ),
                    )
                if cursor.rowcount:
                    claimed = conn.execute(
                        "SELECT * FROM jobs WHERE job_id = ?",
                        (job_id,),
                    ).fetchone()
                    break
            if claimed is None:
                return None
            return self._from_row(claimed)

    def claim_next_for_pool(
        self,
        *,
        pool_id: str,
        worker_id: str,
        lease_ttl_seconds: float = 30.0,
        capability_ids: set[str] | frozenset[str] | None = None,
    ) -> JobRecord | None:
        """Claim the next job for a named worker pool (atomic claim+lease)."""
        return self.claim_next_queued(
            worker_id=worker_id,
            lease_ttl_seconds=lease_ttl_seconds,
            capability_ids=capability_ids,
            worker_pool=pool_id,
            reclaim_expired=True,
        )

    def _fail_expired_deadlines(self, conn: sqlite3.Connection, *, now: str) -> None:
        rows = conn.execute(
            """
            SELECT job_id, state FROM jobs
            WHERE deadline_at IS NOT NULL AND deadline_at <= ?
              AND state IN (?, ?, ?)
            """,
            (
                now,
                JobState.QUEUED.value,
                JobState.RETRY_WAIT.value,
                JobState.RUNNING.value,
            ),
        ).fetchall()
        for row in rows:
            current = JobState(row["state"])
            target = JobState.FAILED
            try:
                validate_job_transition(current, target)
            except InvalidJobTransition:
                continue
            conn.execute(
                """
                UPDATE jobs
                SET state = ?, error = ?, error_code = ?, retryable = 0,
                    finished_at = ?, updated_at = ?,
                    lease_owner = NULL, lease_expires_at = NULL
                WHERE job_id = ? AND state = ?
                """,
                (
                    target.value,
                    "Deadline expired before claim",
                    "DEADLINE_EXPIRED",
                    now,
                    now,
                    row["job_id"],
                    current.value,
                ),
            )

    def request_cancel(
        self,
        job_id: str,
        *,
        reason: str | None = None,
    ) -> JobRecord:
        cancel_reason = reason or "Cancelled by request"
        with self.connect() as conn:
            self._ensure_schema(conn)
            for _ in range(5):
                row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
                if row is None:
                    raise KeyError(f"Unknown job: {job_id}")
                current = JobState(row["state"])
                if current in TERMINAL_JOB_STATES:
                    raise ValueError(f"Job already terminal: {current.value}")
                now = utc_now()
                if current == JobState.CANCEL_REQUESTED:
                    return self._from_row(row)
                if current == JobState.RUNNING:
                    validate_job_transition(current, JobState.CANCEL_REQUESTED)
                    cursor = conn.execute(
                        """
                        UPDATE jobs
                        SET state = ?, cancel_requested_at = ?, cancel_reason = ?,
                            updated_at = ?, message = ?
                        WHERE job_id = ? AND state = ?
                        """,
                        (
                            JobState.CANCEL_REQUESTED.value,
                            now,
                            cancel_reason,
                            now,
                            cancel_reason,
                            job_id,
                            current.value,
                        ),
                    )
                else:
                    validate_job_transition(current, JobState.CANCELLED)
                    cursor = conn.execute(
                        """
                        UPDATE jobs
                        SET state = ?, cancel_requested_at = COALESCE(cancel_requested_at, ?),
                            cancel_reason = ?, error = ?, finished_at = ?, updated_at = ?,
                            lease_owner = NULL, lease_expires_at = NULL
                        WHERE job_id = ? AND state = ?
                        """,
                        (
                            JobState.CANCELLED.value,
                            now,
                            cancel_reason,
                            cancel_reason,
                            now,
                            now,
                            job_id,
                            current.value,
                        ),
                    )
                if cursor.rowcount:
                    row = conn.execute(
                        "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
                    ).fetchone()
                    assert row is not None
                    return self._from_row(row)
            raise RuntimeError(f"Failed to request cancel for job {job_id} under contention")

    def ack_cancel(
        self,
        job_id: str,
        *,
        cleanup_failed: bool = False,
        error: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> JobRecord:
        target = JobState.FAILED if cleanup_failed else JobState.CANCELLED
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown job: {job_id}")
            current = JobState(row["state"])
            if current in TERMINAL_JOB_STATES:
                return self._from_row(row)
            if current != JobState.CANCEL_REQUESTED:
                raise InvalidJobTransition(
                    f"ack_cancel requires CANCEL_REQUESTED, got {current.value}"
                )
            validate_job_transition(current, target)
            now = utc_now()
            result_json = json.dumps(result) if result is not None else row["result_json"]
            err = error or (
                "Cancel cleanup failed" if cleanup_failed else (_row_get(row, "cancel_reason") or "Cancelled")
            )
            conn.execute(
                """
                UPDATE jobs
                SET state = ?, result_json = ?, error = ?, finished_at = ?, updated_at = ?,
                    lease_owner = NULL, lease_expires_at = NULL,
                    error_code = COALESCE(error_code, ?)
                WHERE job_id = ? AND state = ?
                """,
                (
                    target.value,
                    result_json,
                    err,
                    now,
                    now,
                    "CANCEL_CLEANUP_FAILED" if cleanup_failed else "CANCELLED",
                    job_id,
                    JobState.CANCEL_REQUESTED.value,
                ),
            )
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        assert row is not None
        return self._from_row(row)

    def schedule_retry(
        self,
        job_id: str,
        *,
        delay_seconds: float,
        error: str | None = None,
        error_code: str | None = None,
        retryable: bool = True,
        expected_lease_owner: str | None = None,
    ) -> JobRecord:
        from .states import StaleLeaseError

        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat(timespec="seconds")
        next_at = (now_dt + timedelta(seconds=max(0.0, float(delay_seconds)))).isoformat(
            timespec="seconds"
        )
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown job: {job_id}")
            current = JobState(row["state"])
            validate_job_transition(current, JobState.RETRY_WAIT)
            params: list[Any] = [
                JobState.RETRY_WAIT.value,
                next_at,
                now,
                error,
                error_code,
                int(bool(retryable)),
                job_id,
                current.value,
            ]
            where = "job_id = ? AND state = ?"
            if expected_lease_owner is not None:
                where += " AND lease_owner = ?"
                params.append(expected_lease_owner)
            cursor = conn.execute(
                f"""
                UPDATE jobs
                SET state = ?, next_attempt_at = ?, updated_at = ?,
                    error = COALESCE(?, error), error_code = COALESCE(?, error_code),
                    retryable = ?, lease_owner = NULL, lease_expires_at = NULL,
                    finished_at = NULL
                WHERE {where}
                """,
                params,
            )
            if cursor.rowcount == 0:
                if expected_lease_owner is not None:
                    raise StaleLeaseError(
                        f"Stale lease fence: cannot schedule_retry job {job_id} "
                        f"for worker {expected_lease_owner!r}",
                        job_id=job_id,
                        worker_id=expected_lease_owner,
                    )
                raise InvalidJobTransition(
                    f"Job {job_id} state changed concurrently (expected {current.value})"
                )
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        assert row is not None
        return self._from_row(row)

    def update_progress(
        self,
        job_id: str,
        *,
        progress: float | None = None,
        phase: str | None = None,
        message: str | None = None,
    ) -> JobRecord:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown job: {job_id}")
            now = utc_now()
            next_progress = (
                float(progress) if progress is not None else _row_get(row, "progress")
            )
            if next_progress is not None:
                next_progress = max(0.0, min(1.0, float(next_progress)))
            next_phase = phase if phase is not None else _row_get(row, "phase")
            next_message = message if message is not None else _row_get(row, "message")
            conn.execute(
                """
                UPDATE jobs
                SET progress = ?, phase = ?, message = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (next_progress, next_phase, next_message, now, job_id),
            )
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        assert row is not None
        return self._from_row(row)

    def recover_expired_leases(
        self,
        *,
        now: datetime | None = None,
        requeue: bool = True,
    ) -> list[JobRecord]:
        """Recover RUNNING jobs whose leases expired.

        When ``requeue`` is True, moves them to RETRY_WAIT with ``next_attempt_at=now``
        so the next claim can pick them up. Cancel-requested jobs are acknowledged.
        """
        current = now or datetime.now(timezone.utc)
        now_s = current.isoformat(timespec="seconds")
        recovered: list[JobRecord] = []
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT * FROM jobs
                WHERE state IN (?, ?)
                  AND lease_owner IS NOT NULL
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= ?
                ORDER BY lease_expires_at ASC
                """,
                (JobState.RUNNING.value, JobState.CANCEL_REQUESTED.value, now_s),
            ).fetchall()
            for row in rows:
                job_id = row["job_id"]
                state = JobState(row["state"])
                if state == JobState.CANCEL_REQUESTED:
                    conn.execute(
                        """
                        UPDATE jobs
                        SET state = ?, error = COALESCE(cancel_reason, error, ?),
                            finished_at = ?, updated_at = ?,
                            lease_owner = NULL, lease_expires_at = NULL,
                            error_code = COALESCE(error_code, 'CANCELLED')
                        WHERE job_id = ? AND state = ?
                        """,
                        (
                            JobState.CANCELLED.value,
                            "Cancelled after lease expiry",
                            now_s,
                            now_s,
                            job_id,
                            JobState.CANCEL_REQUESTED.value,
                        ),
                    )
                elif requeue:
                    validate_job_transition(JobState.RUNNING, JobState.RETRY_WAIT)
                    conn.execute(
                        """
                        UPDATE jobs
                        SET state = ?, next_attempt_at = ?, updated_at = ?,
                            lease_owner = NULL, lease_expires_at = NULL,
                            error_code = COALESCE(error_code, 'LEASE_EXPIRED'),
                            retryable = 1,
                            message = COALESCE(message, 'Recovered after lease expiry')
                        WHERE job_id = ? AND state = ?
                        """,
                        (
                            JobState.RETRY_WAIT.value,
                            now_s,
                            now_s,
                            job_id,
                            JobState.RUNNING.value,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE jobs
                        SET lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
                        WHERE job_id = ?
                        """,
                        (now_s, job_id),
                    )
                refreshed = conn.execute(
                    "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
                ).fetchone()
                if refreshed is not None:
                    recovered.append(self._from_row(refreshed))
        return recovered

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
        now_s = now.isoformat(timespec="milliseconds")
        expires_s = expires.isoformat(timespec="milliseconds")
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
        """Extend lease only if ``worker_id`` still owns a non-expired lease."""
        now = datetime.now(timezone.utc)
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown job: {job_id}")
            owner = _row_get(row, "lease_owner")
            if owner and owner != worker_id:
                raise ValueError(f"Lease owned by {owner}, not {worker_id}")
            if not owner:
                raise ValueError(f"No active lease on job {job_id}")
            expires_at = _row_get(row, "lease_expires_at")
            exp_dt = _parse_ts(expires_at)
            if exp_dt is not None and now >= exp_dt:
                raise ValueError(f"Lease expired at {expires_at}")
            expires = now + timedelta(seconds=max(1.0, float(ttl_seconds)))
            now_s = now.isoformat(timespec="milliseconds")
            expires_s = expires.isoformat(timespec="milliseconds")
            conn.execute(
                """
                UPDATE jobs
                SET lease_expires_at = ?, last_heartbeat_at = ?, updated_at = ?
                WHERE job_id = ? AND lease_owner = ?
                """,
                (expires_s, now_s, now_s, job_id, worker_id),
            )
            changed = conn.execute("SELECT changes()").fetchone()[0]
            if not changed:
                raise ValueError(f"Lease owned by {owner}, not {worker_id}")
        return WorkerLease(
            job_id=job_id,
            worker_id=worker_id,
            state=LeaseState.HELD,
            leased_at=_row_get(row, "claimed_at") or now_s,
            expires_at=expires_s,
            last_heartbeat_at=now_s,
        )

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

        def g(name: str, default: Any = None) -> Any:
            if name not in keys:
                return default
            value = row[name]
            return default if value is None and default is not None else value

        retryable_raw = g("retryable")
        retryable: bool | None
        if retryable_raw is None:
            retryable = None
        else:
            retryable = bool(retryable_raw)

        artifact_raw = g("artifact_refs_json", "[]")
        try:
            artifact_refs = json.loads(artifact_raw or "[]")
        except json.JSONDecodeError:
            artifact_refs = []
        if not isinstance(artifact_refs, list):
            artifact_refs = []

        summary_raw = g("result_summary_json")
        result_summary = json.loads(summary_raw) if summary_raw else None

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
            trace_id=g("trace_id"),
            idempotency_key=g("idempotency_key"),
            lease_owner=g("lease_owner"),
            lease_expires_at=g("lease_expires_at"),
            last_heartbeat_at=g("last_heartbeat_at"),
            attempt_number=int(g("attempt_number", 1) or 1),
            budget=json.loads(g("budget_json") or "{}") if "budget_json" in keys else {},
            latency_class=g("latency_class") or "background",
            domain=g("domain"),
            consumer=g("consumer"),
            correlation_id=g("correlation_id"),
            root_job_id=g("root_job_id"),
            parent_job_id=g("parent_job_id"),
            domain_entity_type=g("domain_entity_type"),
            domain_entity_id=g("domain_entity_id"),
            worker_pool=g("worker_pool"),
            resource_class=g("resource_class"),
            priority=int(g("priority", PRIORITY_DEFAULT) or PRIORITY_DEFAULT),
            queued_at=g("queued_at"),
            claimed_at=g("claimed_at"),
            started_at=g("started_at"),
            finished_at=g("finished_at"),
            max_attempts=int(g("max_attempts", 3) or 3),
            next_attempt_at=g("next_attempt_at"),
            timeout_seconds=g("timeout_seconds"),
            deadline_at=g("deadline_at"),
            cancel_requested_at=g("cancel_requested_at"),
            cancel_reason=g("cancel_reason"),
            progress=g("progress"),
            phase=g("phase"),
            message=g("message"),
            resource_request=json.loads(g("resource_request_json") or "{}")
            if "resource_request_json" in keys
            else {},
            result_summary=result_summary,
            artifact_refs=artifact_refs,
            error_code=g("error_code"),
            retryable=retryable,
        )


# Re-export for callers that need the exception from store imports.
__all__ = ["InvalidJobTransition", "JobStore", "utc_now"]
