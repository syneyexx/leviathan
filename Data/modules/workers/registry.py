"""Durable worker instance registry — process identity, not PID alone."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from Data.modules.common.process import pid_is_alive

from .protocol import WorkerInstanceState, WorkerRegistration


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class WorkerRegistry:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS worker_instances (
                    worker_id TEXT PRIMARY KEY,
                    pool_id TEXT NOT NULL,
                    slot INTEGER NOT NULL DEFAULT 0,
                    pid INTEGER,
                    process_start_identity TEXT,
                    protocol_version INTEGER NOT NULL DEFAULT 1,
                    implementation_version TEXT NOT NULL DEFAULT '1',
                    supported_job_kinds_json TEXT NOT NULL DEFAULT '[]',
                    host TEXT NOT NULL DEFAULT 'localhost',
                    started_at TEXT,
                    last_heartbeat_at TEXT,
                    state TEXT NOT NULL,
                    current_job_id TEXT,
                    supervisor_generation TEXT,
                    restart_count INTEGER NOT NULL DEFAULT 0,
                    degraded_reason TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_worker_instances_pool "
                "ON worker_instances(pool_id, state)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS supervisor_leases (
                    lease_id TEXT PRIMARY KEY,
                    holder_id TEXT NOT NULL,
                    holder_pid INTEGER,
                    process_start_identity TEXT,
                    acquired_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_heartbeat_at TEXT NOT NULL
                )
                """
            )

    def upsert(self, reg: WorkerRegistration) -> WorkerRegistration:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO worker_instances(
                    worker_id, pool_id, slot, pid, process_start_identity,
                    protocol_version, implementation_version, supported_job_kinds_json,
                    host, started_at, last_heartbeat_at, state, current_job_id,
                    supervisor_generation, restart_count, degraded_reason, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    pool_id=excluded.pool_id,
                    slot=excluded.slot,
                    pid=excluded.pid,
                    process_start_identity=excluded.process_start_identity,
                    protocol_version=excluded.protocol_version,
                    implementation_version=excluded.implementation_version,
                    supported_job_kinds_json=excluded.supported_job_kinds_json,
                    host=excluded.host,
                    started_at=excluded.started_at,
                    last_heartbeat_at=excluded.last_heartbeat_at,
                    state=excluded.state,
                    current_job_id=excluded.current_job_id,
                    supervisor_generation=excluded.supervisor_generation,
                    restart_count=excluded.restart_count,
                    degraded_reason=excluded.degraded_reason,
                    metadata_json=excluded.metadata_json
                """,
                (
                    reg.worker_id,
                    reg.pool_id,
                    reg.slot,
                    reg.pid,
                    reg.process_start_identity,
                    reg.protocol_version,
                    reg.implementation_version,
                    json.dumps(list(reg.supported_job_kinds)),
                    reg.host,
                    reg.started_at,
                    reg.last_heartbeat_at,
                    reg.state.value,
                    reg.current_job_id,
                    reg.supervisor_generation,
                    reg.restart_count,
                    reg.degraded_reason,
                    json.dumps(reg.metadata),
                ),
            )
        return reg

    def get(self, worker_id: str) -> WorkerRegistration | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM worker_instances WHERE worker_id = ?",
                (worker_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def list(
        self,
        *,
        pool_id: str | None = None,
        state: WorkerInstanceState | None = None,
    ) -> list[WorkerRegistration]:
        clauses: list[str] = []
        params: list[Any] = []
        if pool_id:
            clauses.append("pool_id = ?")
            params.append(pool_id)
        if state:
            clauses.append("state = ?")
            params.append(state.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM worker_instances {where} ORDER BY pool_id, slot",
                params,
            ).fetchall()
        return [self._from_row(r) for r in rows]

    def heartbeat(
        self,
        worker_id: str,
        *,
        state: WorkerInstanceState | None = None,
        current_job_id: str | None = None,
        clear_job: bool = False,
    ) -> WorkerRegistration | None:
        now = utc_now()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM worker_instances WHERE worker_id = ?",
                (worker_id,),
            ).fetchone()
            if row is None:
                return None
            new_state = state.value if state is not None else row["state"]
            job = row["current_job_id"]
            if clear_job:
                job = None
            elif current_job_id is not None:
                job = current_job_id
            conn.execute(
                """
                UPDATE worker_instances
                SET last_heartbeat_at = ?, state = ?, current_job_id = ?
                WHERE worker_id = ?
                """,
                (now, new_state, job, worker_id),
            )
            row = conn.execute(
                "SELECT * FROM worker_instances WHERE worker_id = ?",
                (worker_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def mark_state(
        self,
        worker_id: str,
        state: WorkerInstanceState,
        *,
        degraded_reason: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE worker_instances
                SET state = ?, degraded_reason = ?, last_heartbeat_at = ?
                WHERE worker_id = ?
                """,
                (state.value, degraded_reason, utc_now(), worker_id),
            )

    def delete(self, worker_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM worker_instances WHERE worker_id = ?", (worker_id,))

    def reconcile_stale(
        self,
        *,
        heartbeat_ttl_seconds: float = 30.0,
        supervisor_generation: str | None = None,
    ) -> list[str]:
        """Mark rows stale when PID dead or heartbeat expired. Never kill by PID alone."""
        now = datetime.now(timezone.utc)
        marked: list[str] = []
        for reg in self.list():
            if reg.state in {
                WorkerInstanceState.STOPPED,
                WorkerInstanceState.STALE,
                WorkerInstanceState.CRASHED,
            }:
                continue
            alive = reg.pid is not None and pid_is_alive(int(reg.pid))
            hb_stale = False
            if reg.last_heartbeat_at:
                try:
                    hb = datetime.fromisoformat(reg.last_heartbeat_at.replace("Z", "+00:00"))
                    if hb.tzinfo is None:
                        hb = hb.replace(tzinfo=timezone.utc)
                    hb_stale = (now - hb).total_seconds() > float(heartbeat_ttl_seconds)
                except ValueError:
                    hb_stale = True
            gen_mismatch = (
                supervisor_generation is not None
                and reg.supervisor_generation
                and reg.supervisor_generation != supervisor_generation
            )
            if (not alive) or hb_stale or gen_mismatch:
                reason = "pid_dead" if not alive else ("heartbeat_stale" if hb_stale else "generation_mismatch")
                self.mark_state(
                    reg.worker_id,
                    WorkerInstanceState.STALE,
                    degraded_reason=reason,
                )
                marked.append(reg.worker_id)
        return marked

    # --- supervisor singleton lease ---

    def try_acquire_supervisor_lease(
        self,
        *,
        holder_id: str,
        holder_pid: int,
        process_start_identity: str,
        ttl_seconds: float = 20.0,
        lease_id: str = "generic-worker-supervisor",
    ) -> bool:
        now = datetime.now(timezone.utc)
        expires = now.timestamp() + max(5.0, float(ttl_seconds))
        expires_s = datetime.fromtimestamp(expires, tz=timezone.utc).isoformat(timespec="seconds")
        now_s = now.isoformat(timespec="seconds")
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM supervisor_leases WHERE lease_id = ?",
                (lease_id,),
            ).fetchone()
            if row is not None:
                try:
                    exp = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    exp = now
                holder_alive = bool(row["holder_pid"]) and pid_is_alive(int(row["holder_pid"]))
                same_holder = row["holder_id"] == holder_id
                if now < exp and holder_alive and not same_holder:
                    return False
            conn.execute(
                """
                INSERT INTO supervisor_leases(
                    lease_id, holder_id, holder_pid, process_start_identity,
                    acquired_at, expires_at, last_heartbeat_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lease_id) DO UPDATE SET
                    holder_id=excluded.holder_id,
                    holder_pid=excluded.holder_pid,
                    process_start_identity=excluded.process_start_identity,
                    acquired_at=excluded.acquired_at,
                    expires_at=excluded.expires_at,
                    last_heartbeat_at=excluded.last_heartbeat_at
                """,
                (lease_id, holder_id, holder_pid, process_start_identity, now_s, expires_s, now_s),
            )
        return True

    def heartbeat_supervisor_lease(
        self,
        *,
        holder_id: str,
        ttl_seconds: float = 20.0,
        lease_id: str = "generic-worker-supervisor",
    ) -> bool:
        now = datetime.now(timezone.utc)
        expires_s = datetime.fromtimestamp(
            now.timestamp() + max(5.0, float(ttl_seconds)),
            tz=timezone.utc,
        ).isoformat(timespec="seconds")
        now_s = now.isoformat(timespec="seconds")
        with self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE supervisor_leases
                SET expires_at = ?, last_heartbeat_at = ?
                WHERE lease_id = ? AND holder_id = ?
                """,
                (expires_s, now_s, lease_id, holder_id),
            )
            return int(cur.rowcount or 0) > 0

    def release_supervisor_lease(
        self,
        *,
        holder_id: str,
        lease_id: str = "generic-worker-supervisor",
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM supervisor_leases WHERE lease_id = ? AND holder_id = ?",
                (lease_id, holder_id),
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> WorkerRegistration:
        kinds = json.loads(row["supported_job_kinds_json"] or "[]")
        return WorkerRegistration(
            worker_id=row["worker_id"],
            pool_id=row["pool_id"],
            slot=int(row["slot"] or 0),
            pid=int(row["pid"] or 0),
            process_start_identity=row["process_start_identity"] or "",
            protocol_version=int(row["protocol_version"] or 1),
            implementation_version=row["implementation_version"] or "1",
            supported_job_kinds=tuple(kinds),
            host=row["host"] or "localhost",
            started_at=row["started_at"],
            last_heartbeat_at=row["last_heartbeat_at"],
            state=WorkerInstanceState(row["state"]),
            current_job_id=row["current_job_id"],
            supervisor_generation=row["supervisor_generation"],
            restart_count=int(row["restart_count"] or 0),
            degraded_reason=row["degraded_reason"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )
