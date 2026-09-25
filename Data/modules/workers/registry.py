"""Durable worker instance registry — process identity, not PID alone."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from Data.modules.common.process import pid_is_alive

from .protocol import SupervisorHealth, WorkerInstanceState, WorkerRegistration
from .sqlite_support import (
    control_plane_connection,
    ensure_wal,
    run_with_busy_retry,
)

logger = logging.getLogger(__name__)

_HEALTHY_LIVE_STATES = {
    WorkerInstanceState.STARTING,
    WorkerInstanceState.READY,
    WorkerInstanceState.BUSY,
    WorkerInstanceState.DRAINING,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class WorkerRegistry:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._decode_diagnostics: list[dict[str, Any]] = []

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        with control_plane_connection(self.db_path) as conn:
            yield conn

    def initialize(self) -> None:
        def _init() -> None:
            with self.connect() as conn:
                ensure_wal(conn)
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
                        last_heartbeat_at TEXT NOT NULL,
                        health_state TEXT,
                        last_tick_at TEXT,
                        last_successful_tick_at TEXT,
                        consecutive_tick_failures INTEGER NOT NULL DEFAULT 0,
                        last_tick_error TEXT,
                        restart_count INTEGER NOT NULL DEFAULT 0,
                        degraded_reason TEXT
                    )
                    """
                )
                self._ensure_lease_health_columns(conn)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS worker_pool_desired (
                        pool_id TEXT PRIMARY KEY,
                        desired_count INTEGER NOT NULL,
                        updated_at TEXT NOT NULL,
                        updated_by TEXT
                    )
                    """
                )

        run_with_busy_retry(_init)

    @staticmethod
    def _ensure_lease_health_columns(conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(supervisor_leases)").fetchall()}
        for name, ddl in (
            ("health_state", "health_state TEXT"),
            ("last_tick_at", "last_tick_at TEXT"),
            ("last_successful_tick_at", "last_successful_tick_at TEXT"),
            ("consecutive_tick_failures", "consecutive_tick_failures INTEGER NOT NULL DEFAULT 0"),
            ("last_tick_error", "last_tick_error TEXT"),
            ("restart_count", "restart_count INTEGER NOT NULL DEFAULT 0"),
            ("degraded_reason", "degraded_reason TEXT"),
        ):
            if name not in cols:
                conn.execute(f"ALTER TABLE supervisor_leases ADD COLUMN {ddl}")

    def upsert(self, reg: WorkerRegistration) -> WorkerRegistration:
        def _do() -> None:
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

        run_with_busy_retry(_do)
        return reg

    def get(self, worker_id: str) -> WorkerRegistration | None:
        def _do() -> sqlite3.Row | None:
            with self.connect() as conn:
                return conn.execute(
                    "SELECT * FROM worker_instances WHERE worker_id = ?",
                    (worker_id,),
                ).fetchone()

        row = run_with_busy_retry(_do)
        if row is None:
            return None
        reg, quarantine = self._from_row_safe(row)
        if quarantine:
            self._persist_quarantine(reg)
        return reg

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

        def _do() -> list[sqlite3.Row]:
            with self.connect() as conn:
                return list(
                    conn.execute(
                        f"SELECT * FROM worker_instances {where} ORDER BY pool_id, slot",
                        params,
                    ).fetchall()
                )

        rows = run_with_busy_retry(_do)
        out: list[WorkerRegistration] = []
        to_quarantine: list[WorkerRegistration] = []
        for row in rows:
            reg, quarantine = self._from_row_safe(row)
            out.append(reg)
            if quarantine:
                to_quarantine.append(reg)
        for reg in to_quarantine:
            self._persist_quarantine(reg)
        return out

    def pop_decode_diagnostics(self) -> list[dict[str, Any]]:
        items = list(self._decode_diagnostics)
        self._decode_diagnostics.clear()
        return items

    def heartbeat(
        self,
        worker_id: str,
        *,
        state: WorkerInstanceState | None = None,
        current_job_id: str | None = None,
        clear_job: bool = False,
    ) -> WorkerRegistration | None:
        now = utc_now()

        def _do() -> sqlite3.Row | None:
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
                return conn.execute(
                    "SELECT * FROM worker_instances WHERE worker_id = ?",
                    (worker_id,),
                ).fetchone()

        row = run_with_busy_retry(_do)
        if row is None:
            return None
        reg, quarantine = self._from_row_safe(row)
        if quarantine:
            self._persist_quarantine(reg)
        return reg

    def mark_state(
        self,
        worker_id: str,
        state: WorkerInstanceState,
        *,
        degraded_reason: str | None = None,
        metadata_patch: dict[str, Any] | None = None,
    ) -> None:
        def _do() -> None:
            with self.connect() as conn:
                meta_json = None
                if metadata_patch:
                    row = conn.execute(
                        "SELECT metadata_json FROM worker_instances WHERE worker_id = ?",
                        (worker_id,),
                    ).fetchone()
                    meta: dict[str, Any] = {}
                    if row is not None:
                        try:
                            raw = row["metadata_json"] or "{}"
                            parsed = json.loads(raw)
                            if isinstance(parsed, dict):
                                meta = parsed
                        except (TypeError, ValueError, json.JSONDecodeError):
                            meta = {"_raw_metadata_json": row["metadata_json"]}
                    meta.update(metadata_patch)
                    meta_json = json.dumps(meta)
                if meta_json is not None:
                    conn.execute(
                        """
                        UPDATE worker_instances
                        SET state = ?, degraded_reason = ?, last_heartbeat_at = ?,
                            metadata_json = ?
                        WHERE worker_id = ?
                        """,
                        (state.value, degraded_reason, utc_now(), meta_json, worker_id),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE worker_instances
                        SET state = ?, degraded_reason = ?, last_heartbeat_at = ?
                        WHERE worker_id = ?
                        """,
                        (state.value, degraded_reason, utc_now(), worker_id),
                    )

        run_with_busy_retry(_do)

    def delete(self, worker_id: str) -> None:
        def _do() -> None:
            with self.connect() as conn:
                conn.execute("DELETE FROM worker_instances WHERE worker_id = ?", (worker_id,))

        run_with_busy_retry(_do)

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
                WorkerInstanceState.INCOMPATIBLE,
            }:
                continue
            alive = reg.pid is not None and int(reg.pid) > 0 and pid_is_alive(int(reg.pid))
            hb_stale = False
            if reg.last_heartbeat_at:
                try:
                    hb = datetime.fromisoformat(reg.last_heartbeat_at.replace("Z", "+00:00"))
                    if hb.tzinfo is None:
                        hb = hb.replace(tzinfo=timezone.utc)
                    hb_stale = (now - hb).total_seconds() > float(heartbeat_ttl_seconds)
                except ValueError:
                    hb_stale = True
            else:
                hb_stale = True
            gen_mismatch = (
                supervisor_generation is not None
                and reg.supervisor_generation
                and reg.supervisor_generation != supervisor_generation
            )
            if (not alive) or hb_stale or gen_mismatch:
                reason = (
                    "pid_dead"
                    if not alive
                    else ("heartbeat_stale" if hb_stale else "generation_mismatch")
                )
                try:
                    self.mark_state(
                        reg.worker_id,
                        WorkerInstanceState.STALE,
                        degraded_reason=reason,
                    )
                    marked.append(reg.worker_id)
                except Exception as exc:  # noqa: BLE001 — one row must not abort reconcile
                    logger.warning(
                        "reconcile_stale mark failed worker_id=%s: %s",
                        reg.worker_id,
                        exc,
                    )
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
        restart_count: int = 0,
    ) -> bool:
        now = datetime.now(timezone.utc)
        expires = now.timestamp() + max(5.0, float(ttl_seconds))
        expires_s = datetime.fromtimestamp(expires, tz=timezone.utc).isoformat(timespec="seconds")
        now_s = now.isoformat(timespec="seconds")

        def _do() -> bool:
            with self.connect() as conn:
                self._ensure_lease_health_columns(conn)
                row = conn.execute(
                    "SELECT * FROM supervisor_leases WHERE lease_id = ?",
                    (lease_id,),
                ).fetchone()
                if row is not None:
                    try:
                        exp = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
                        if exp.tzinfo is None:
                            exp = exp.replace(tzinfo=timezone.utc)
                    except (TypeError, ValueError, AttributeError):
                        exp = now
                    holder_alive = bool(row["holder_pid"]) and pid_is_alive(int(row["holder_pid"]))
                    same_holder = row["holder_id"] == holder_id
                    if now < exp and holder_alive and not same_holder:
                        return False
                conn.execute(
                    """
                    INSERT INTO supervisor_leases(
                        lease_id, holder_id, holder_pid, process_start_identity,
                        acquired_at, expires_at, last_heartbeat_at,
                        health_state, consecutive_tick_failures, last_tick_error,
                        restart_count, degraded_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, NULL)
                    ON CONFLICT(lease_id) DO UPDATE SET
                        holder_id=excluded.holder_id,
                        holder_pid=excluded.holder_pid,
                        process_start_identity=excluded.process_start_identity,
                        acquired_at=excluded.acquired_at,
                        expires_at=excluded.expires_at,
                        last_heartbeat_at=excluded.last_heartbeat_at,
                        health_state=excluded.health_state,
                        consecutive_tick_failures=0,
                        last_tick_error=NULL,
                        restart_count=excluded.restart_count,
                        degraded_reason=NULL
                    """,
                    (
                        lease_id,
                        holder_id,
                        holder_pid,
                        process_start_identity,
                        now_s,
                        expires_s,
                        now_s,
                        SupervisorHealth.RUNNING.value,
                        int(restart_count),
                    ),
                )
            return True

        return run_with_busy_retry(_do)

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

        def _do() -> bool:
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

        return run_with_busy_retry(_do)

    def release_supervisor_lease(
        self,
        *,
        holder_id: str,
        lease_id: str = "generic-worker-supervisor",
    ) -> None:
        def _do() -> None:
            with self.connect() as conn:
                conn.execute(
                    "DELETE FROM supervisor_leases WHERE lease_id = ? AND holder_id = ?",
                    (lease_id, holder_id),
                )

        run_with_busy_retry(_do)

    def update_supervisor_health(
        self,
        *,
        holder_id: str,
        health: SupervisorHealth | str,
        last_tick_at: str | None = None,
        last_successful_tick_at: str | None = None,
        consecutive_tick_failures: int | None = None,
        last_tick_error: str | None = None,
        restart_count: int | None = None,
        degraded_reason: str | None = None,
        clear_error: bool = False,
        lease_id: str = "generic-worker-supervisor",
    ) -> None:
        health_s = health.value if isinstance(health, SupervisorHealth) else str(health)

        def _do() -> None:
            with self.connect() as conn:
                self._ensure_lease_health_columns(conn)
                row = conn.execute(
                    "SELECT * FROM supervisor_leases WHERE lease_id = ? AND holder_id = ?",
                    (lease_id, holder_id),
                ).fetchone()
                if row is None:
                    return
                sets = ["health_state = ?"]
                params: list[Any] = [health_s]
                if last_tick_at is not None:
                    sets.append("last_tick_at = ?")
                    params.append(last_tick_at)
                if last_successful_tick_at is not None:
                    sets.append("last_successful_tick_at = ?")
                    params.append(last_successful_tick_at)
                if consecutive_tick_failures is not None:
                    sets.append("consecutive_tick_failures = ?")
                    params.append(int(consecutive_tick_failures))
                if clear_error:
                    sets.append("last_tick_error = NULL")
                elif last_tick_error is not None:
                    sets.append("last_tick_error = ?")
                    params.append(last_tick_error[:2000])
                if restart_count is not None:
                    sets.append("restart_count = ?")
                    params.append(int(restart_count))
                if degraded_reason is not None:
                    sets.append("degraded_reason = ?")
                    params.append(degraded_reason[:2000])
                params.extend([lease_id, holder_id])
                conn.execute(
                    f"UPDATE supervisor_leases SET {', '.join(sets)} "
                    "WHERE lease_id = ? AND holder_id = ?",
                    params,
                )

        try:
            run_with_busy_retry(_do)
        except Exception as exc:  # noqa: BLE001 — health write must not kill tick
            logger.warning("update_supervisor_health failed: %s", exc)

    def get_supervisor_lease(
        self,
        *,
        lease_id: str = "generic-worker-supervisor",
    ) -> dict[str, Any] | None:
        def _do() -> dict[str, Any] | None:
            with self.connect() as conn:
                self._ensure_lease_health_columns(conn)
                row = conn.execute(
                    "SELECT * FROM supervisor_leases WHERE lease_id = ?",
                    (lease_id,),
                ).fetchone()
                return dict(row) if row is not None else None

        try:
            return run_with_busy_retry(_do)
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_supervisor_lease failed: %s", exc)
            return None

    def write_parent_supervisor_unavailable(
        self,
        *,
        reason: str,
        restart_count: int,
        lease_id: str = "generic-worker-supervisor",
    ) -> None:
        """Parent bootstrap marks worker subsystem DEGRADED when restart budget exhausted."""

        def _do() -> None:
            with self.connect() as conn:
                self._ensure_lease_health_columns(conn)
                now_s = utc_now()
                conn.execute(
                    """
                    INSERT INTO supervisor_leases(
                        lease_id, holder_id, holder_pid, process_start_identity,
                        acquired_at, expires_at, last_heartbeat_at,
                        health_state, consecutive_tick_failures, last_tick_error,
                        restart_count, degraded_reason
                    ) VALUES (?, 'parent-bootstrap', 0, 'parent', ?, ?, ?, ?, 0, ?, ?, ?)
                    ON CONFLICT(lease_id) DO UPDATE SET
                        health_state=excluded.health_state,
                        last_tick_error=excluded.last_tick_error,
                        restart_count=excluded.restart_count,
                        degraded_reason=excluded.degraded_reason,
                        last_heartbeat_at=excluded.last_heartbeat_at
                    """,
                    (
                        lease_id,
                        now_s,
                        now_s,
                        now_s,
                        SupervisorHealth.DEGRADED.value,
                        reason[:2000],
                        int(restart_count),
                        reason[:2000],
                    ),
                )

        try:
            run_with_busy_retry(_do)
        except Exception as exc:  # noqa: BLE001
            logger.warning("write_parent_supervisor_unavailable failed: %s", exc)

    def _persist_quarantine(self, reg: WorkerRegistration) -> None:
        """Persist quarantined effective state and rewrite corrupt JSON columns."""

        def _do() -> None:
            with self.connect() as conn:
                conn.execute(
                    """
                    UPDATE worker_instances
                    SET state = ?,
                        degraded_reason = ?,
                        last_heartbeat_at = ?,
                        supported_job_kinds_json = ?,
                        metadata_json = ?
                    WHERE worker_id = ?
                    """,
                    (
                        reg.state.value,
                        reg.degraded_reason,
                        utc_now(),
                        json.dumps(list(reg.supported_job_kinds)),
                        json.dumps(reg.metadata or {}),
                        reg.worker_id,
                    ),
                )

        try:
            run_with_busy_retry(_do)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "quarantine persist failed worker_id=%s: %s",
                reg.worker_id,
                exc,
            )

    def _from_row_safe(self, row: sqlite3.Row) -> tuple[WorkerRegistration, bool]:
        """Decode a registry row without raising on legacy/corrupt data.

        Returns (registration, needs_quarantine_persist).
        """
        worker_id = str(row["worker_id"] if "worker_id" in row.keys() else "unknown")
        diagnostics: dict[str, Any] = {}
        quarantine = False

        raw_state = row["state"] if "state" in row.keys() else None
        state = WorkerInstanceState.STALE
        try:
            state = WorkerInstanceState(str(raw_state))
        except (TypeError, ValueError):
            quarantine = True
            diagnostics["invalid_persisted_state"] = raw_state
            state = WorkerInstanceState.INCOMPATIBLE

        kinds: list[Any] = []
        raw_kinds = row["supported_job_kinds_json"] if "supported_job_kinds_json" in row.keys() else None
        try:
            parsed_kinds = json.loads(raw_kinds or "[]")
            if isinstance(parsed_kinds, list):
                kinds = parsed_kinds
            else:
                raise TypeError("supported_job_kinds_json is not a list")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            quarantine = True
            diagnostics["malformed_supported_job_kinds_json"] = str(exc)
            diagnostics["raw_supported_job_kinds_json"] = raw_kinds
            kinds = []

        metadata: dict[str, Any] = {}
        raw_meta = row["metadata_json"] if "metadata_json" in row.keys() else None
        try:
            parsed_meta = json.loads(raw_meta or "{}")
            if isinstance(parsed_meta, dict):
                metadata = parsed_meta
            else:
                raise TypeError("metadata_json is not an object")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            quarantine = True
            diagnostics["malformed_metadata_json"] = str(exc)
            diagnostics["raw_metadata_json"] = raw_meta
            metadata = {}

        if quarantine:
            metadata = {
                **metadata,
                "registry_decode_diagnostics": diagnostics,
                "raw_persisted_state": raw_state,
            }
            if state in _HEALTHY_LIVE_STATES:
                state = WorkerInstanceState.DEGRADED
            if state not in {
                WorkerInstanceState.STALE,
                WorkerInstanceState.INCOMPATIBLE,
                WorkerInstanceState.DEGRADED,
                WorkerInstanceState.CRASHED,
                WorkerInstanceState.STOPPED,
            }:
                state = WorkerInstanceState.STALE
            reason = "invalid_persisted_state" if "invalid_persisted_state" in diagnostics else (
                "malformed_registry_json"
            )
            degraded_reason = reason
            self._decode_diagnostics.append(
                {
                    "worker_id": worker_id,
                    "reason": reason,
                    "diagnostics": diagnostics,
                }
            )
        else:
            degraded_reason = row["degraded_reason"] if "degraded_reason" in row.keys() else None

        def _int(key: str, default: int = 0) -> int:
            try:
                val = row[key] if key in row.keys() else None
                if val is None:
                    return default
                return int(val)
            except (TypeError, ValueError):
                return default

        def _str(key: str, default: str = "") -> str:
            try:
                val = row[key] if key in row.keys() else None
                return default if val is None else str(val)
            except (TypeError, ValueError):
                return default

        def _opt_str(key: str) -> str | None:
            try:
                val = row[key] if key in row.keys() else None
                return None if val is None else str(val)
            except (TypeError, ValueError):
                return None

        try:
            reg = WorkerRegistration(
                worker_id=worker_id,
                pool_id=_str("pool_id", "unknown"),
                slot=_int("slot", 0),
                pid=_int("pid", 0),
                process_start_identity=_str("process_start_identity", ""),
                protocol_version=_int("protocol_version", 1),
                implementation_version=_str("implementation_version", "1"),
                supported_job_kinds=tuple(str(k) for k in kinds),
                host=_str("host", "localhost"),
                started_at=_opt_str("started_at"),
                last_heartbeat_at=_opt_str("last_heartbeat_at"),
                state=state,
                current_job_id=_opt_str("current_job_id"),
                supervisor_generation=_opt_str("supervisor_generation"),
                restart_count=_int("restart_count", 0),
                degraded_reason=degraded_reason if quarantine else _opt_str("degraded_reason"),
                metadata=metadata,
            )
        except Exception as exc:  # noqa: BLE001 — absolute last resort
            quarantine = True
            logger.error("registry row decode catastrophic worker_id=%s: %s", worker_id, exc)
            reg = WorkerRegistration(
                worker_id=worker_id,
                pool_id="unknown",
                slot=0,
                pid=0,
                process_start_identity="",
                state=WorkerInstanceState.INCOMPATIBLE,
                degraded_reason="registry_row_decode_failure",
                metadata={"registry_decode_error": str(exc), "raw_persisted_state": raw_state},
            )
            self._decode_diagnostics.append(
                {"worker_id": worker_id, "reason": "registry_row_decode_failure", "error": str(exc)}
            )
        return reg, quarantine

    def list_pool_desired_overrides(self) -> dict[str, int]:
        """Durable operator-desired pool counts (overrides env defaults when set)."""
        def _do() -> list[sqlite3.Row]:
            with self.connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS worker_pool_desired (
                        pool_id TEXT PRIMARY KEY,
                        desired_count INTEGER NOT NULL,
                        updated_at TEXT NOT NULL,
                        updated_by TEXT
                    )
                    """
                )
                return list(conn.execute("SELECT pool_id, desired_count FROM worker_pool_desired"))

        rows = run_with_busy_retry(_do)
        return {str(r["pool_id"]): int(r["desired_count"]) for r in rows}

    def set_pool_desired_count(
        self,
        pool_id: str,
        desired_count: int,
        *,
        updated_by: str | None = "api",
    ) -> dict[str, Any]:
        """Persist desired count for a pool. Caller must enforce max_count / catalog membership."""
        now = utc_now()
        count = int(desired_count)

        def _do() -> None:
            with self.connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS worker_pool_desired (
                        pool_id TEXT PRIMARY KEY,
                        desired_count INTEGER NOT NULL,
                        updated_at TEXT NOT NULL,
                        updated_by TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO worker_pool_desired(pool_id, desired_count, updated_at, updated_by)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(pool_id) DO UPDATE SET
                        desired_count=excluded.desired_count,
                        updated_at=excluded.updated_at,
                        updated_by=excluded.updated_by
                    """,
                    (pool_id, count, now, updated_by),
                )

        run_with_busy_retry(_do)
        return {
            "poolId": pool_id,
            "desiredCount": count,
            "updatedAt": now,
            "updatedBy": updated_by,
        }

    @staticmethod
    def _from_row(row: sqlite3.Row) -> WorkerRegistration:
        """Strict decode for known-good rows (raises on corrupt data)."""
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
