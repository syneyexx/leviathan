"""Generic worker supervisor — singleton owner of background worker pools.

Does NOT own model-serving residency (Model Control Plane / ServingSupervisor).
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .admission import ResourceAdmission
from .events import WorkerEventKind, get_worker_event_emitter
from .pools import POOL_CATALOG
from .process import OwnedProcess, spawn_worker_process, terminate_owned, verify_owned
from .protocol import (
    WORKER_PROTOCOL_VERSION,
    SupervisorHealth,
    WorkerInstanceState,
    WorkerRegistration,
)
from .registry import WorkerRegistry, utc_now
from .settings import WorkerSettings, load_worker_settings
from .sqlite_support import is_transient_sqlite_error

logger = logging.getLogger(__name__)


class SupervisorLeaseLost(RuntimeError):
    """Singleton lease no longer owned by this process — fatal for this owner."""


class SupervisorFatalError(RuntimeError):
    """Unrecoverable supervisor invariant / schema failure."""


@dataclass
class PoolRuntimeState:
    pool_id: str
    desired: int = 0
    degraded: bool = False
    degraded_reason: str | None = None
    crash_timestamps: list[float] = field(default_factory=list)
    cooldown_until: float = 0.0


class WorkerSupervisor:
    """Spawns, heartbeats, drains, and restarts generic worker processes."""

    def __init__(
        self,
        db_path: Path,
        *,
        settings: WorkerSettings | None = None,
        repo_root: Path | None = None,
        admission: ResourceAdmission | None = None,
        log_dir: Path | None = None,
        restart_count: int = 0,
    ) -> None:
        self.db_path = Path(db_path)
        self.settings = settings or load_worker_settings()
        self.repo_root = repo_root or Path(__file__).resolve().parents[3]
        self.registry = WorkerRegistry(self.db_path)
        self.admission = admission or ResourceAdmission(
            self.db_path,
            ram_headroom_mb=self.settings.ram_headroom_mb,
            vram_headroom_mb=self.settings.vram_headroom_mb,
        )
        self.log_dir = log_dir or (self.db_path.parent / "worker_logs")
        self.holder_id = f"supervisor-{uuid.uuid4().hex[:12]}"
        self.generation = uuid.uuid4().hex
        self._owned: dict[str, OwnedProcess] = {}
        self._pools: dict[str, PoolRuntimeState] = {
            pid: PoolRuntimeState(pool_id=pid, desired=self.settings.desired_count(pid))
            for pid in POOL_CATALOG
        }
        self._running = False
        self._process_start_identity = f"supervisor:{os.getpid()}:{time.time_ns()}"
        self.health = SupervisorHealth.STOPPED
        self.last_tick_at: str | None = None
        self.last_successful_tick_at: str | None = None
        self.consecutive_tick_failures = 0
        self.last_tick_error: str | None = None
        self.restart_count = int(restart_count)
        self._shutdown_errors: list[str] = []
        self._announced_pools: set[str] = set()
        self._restart_attempts: dict[str, int] = {}
        self._events = get_worker_event_emitter()

    def _apply_desired_overrides(self) -> None:
        """Hot-apply durable API/operator pool desired counts before reconcile."""
        try:
            overrides = self.registry.list_pool_desired_overrides()
        except Exception:  # noqa: BLE001
            return
        for pool_id, desired in overrides.items():
            if pool_id not in self._pools or pool_id not in POOL_CATALOG:
                continue
            max_count = POOL_CATALOG[pool_id].max_count
            clamped = max(0, min(int(desired), max_count))
            self._pools[pool_id].desired = clamped
            self.settings.pool_counts[pool_id] = clamped

    def initialize(self) -> None:
        self.registry.initialize()
        self.admission.initialize()
        self._apply_desired_overrides()

    def acquire(self) -> bool:
        return self.registry.try_acquire_supervisor_lease(
            holder_id=self.holder_id,
            holder_pid=os.getpid(),
            process_start_identity=self._process_start_identity,
            ttl_seconds=self.settings.supervisor_lease_ttl_seconds,
            restart_count=self.restart_count,
        )

    def start(self) -> None:
        self.initialize()
        if not self.acquire():
            self.health = SupervisorHealth.LEASE_LOST
            raise RuntimeError("WORKER_SUPERVISOR_LEASE_HELD: another supervisor owns worker pools")
        self.health = SupervisorHealth.RUNNING
        try:
            self.registry.reconcile_stale(
                heartbeat_ttl_seconds=self.settings.lease_ttl_seconds * 2,
                supervisor_generation=self.generation,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("reconcile_stale at start failed: %s", exc)
            self._note_transient("reconcile_stale", exc)
        try:
            self.admission.recover_expired()
        except Exception as exc:  # noqa: BLE001
            logger.warning("recover_expired at start failed: %s", exc)
            self._note_transient("recover_expired", exc)
        self._running = True
        self._persist_health()
        try:
            self.reconcile_pools()
            self._announce_started_pools()
        except Exception as exc:  # noqa: BLE001
            logger.warning("reconcile_pools at start failed: %s", exc)
            self._note_transient("reconcile_pools", exc)

    def stop(self, *, grace_seconds: float | None = None) -> None:
        """Best-effort drain. Collects shutdown errors; does not mask caller failures."""
        self.health = SupervisorHealth.STOPPING
        self._running = False
        self._shutdown_errors = []
        grace = (
            self.settings.shutdown_grace_seconds
            if grace_seconds is None
            else float(grace_seconds)
        )
        try:
            self._persist_health()
        except Exception as exc:  # noqa: BLE001
            self._shutdown_errors.append(f"persist_health: {exc}")

        for worker_id, proc in list(self._owned.items()):
            try:
                proc.draining = True
                self.registry.mark_state(worker_id, WorkerInstanceState.DRAINING)
            except Exception as exc:  # noqa: BLE001
                self._shutdown_errors.append(f"mark_draining:{worker_id}: {exc}")

        deadline = time.time() + grace
        while time.time() < deadline and any(
            verify_owned(p) and p.popen and p.popen.poll() is None for p in self._owned.values()
        ):
            time.sleep(0.2)

        for worker_id, proc in list(self._owned.items()):
            try:
                terminate_owned(proc, grace_seconds=2.0)
            except Exception as exc:  # noqa: BLE001
                self._shutdown_errors.append(f"terminate:{worker_id}: {exc}")
            try:
                self.registry.mark_state(worker_id, WorkerInstanceState.STOPPED)
            except Exception as exc:  # noqa: BLE001
                self._shutdown_errors.append(f"mark_stopped:{worker_id}: {exc}")
            try:
                self._events.worker_stopping(pool=proc.pool_id, worker_id=worker_id)
            except Exception:  # noqa: BLE001
                pass
            self._owned.pop(worker_id, None)

        try:
            self.registry.release_supervisor_lease(holder_id=self.holder_id)
        except Exception as exc:  # noqa: BLE001
            self._shutdown_errors.append(f"release_lease: {exc}")

        self.health = SupervisorHealth.STOPPED
        if self._shutdown_errors:
            logger.error(
                "supervisor stop completed with %d error(s): %s",
                len(self._shutdown_errors),
                "; ".join(self._shutdown_errors[:8]),
            )

    def tick(self) -> dict[str, Any]:
        """One supervisor loop iteration — failure domains are isolated."""
        if not self._running:
            return {"ok": False, "reason": "not_running", "fatal": False, "health": self.health.value}

        self._apply_desired_overrides()
        tick_errors: list[dict[str, Any]] = []
        now_s = utc_now()
        self.last_tick_at = now_s

        # --- Fatal domain: singleton lease ---
        try:
            owned = self.registry.heartbeat_supervisor_lease(
                holder_id=self.holder_id,
                ttl_seconds=self.settings.supervisor_lease_ttl_seconds,
            )
        except Exception as exc:
            if is_transient_sqlite_error(exc):
                self._record_tick_failure(exc, phase="heartbeat_lease")
                tick_errors.append({"phase": "heartbeat_lease", "error": str(exc), "transient": True})
                self.health = SupervisorHealth.DEGRADED
                self._persist_health()
                return {
                    "ok": True,
                    "degraded": True,
                    "fatal": False,
                    "reason": "transient_lease_heartbeat_failure",
                    "health": self.health.value,
                    "errors": tick_errors,
                    "owned": len(self._owned),
                    "pools": self._safe_pool_status(tick_errors),
                }
            self._record_tick_failure(exc, phase="heartbeat_lease")
            self.health = SupervisorHealth.DEGRADED
            self._persist_health()
            raise SupervisorFatalError(f"lease heartbeat failed: {exc}") from exc

        if not owned:
            self._running = False
            self.health = SupervisorHealth.LEASE_LOST
            self.last_tick_error = "lost_supervisor_lease"
            self._persist_health()
            return {
                "ok": False,
                "fatal": True,
                "reason": "lost_supervisor_lease",
                "health": self.health.value,
            }

        # --- Transient-safe: expired reservation recovery ---
        try:
            self.admission.recover_expired()
        except Exception as exc:  # noqa: BLE001
            transient = is_transient_sqlite_error(exc)
            tick_errors.append(
                {"phase": "recover_expired", "error": str(exc), "transient": transient}
            )
            logger.warning("recover_expired failed transient=%s: %s", transient, exc)
            if not transient and _looks_like_schema_error(exc):
                self._record_tick_failure(exc, phase="recover_expired")
                self.health = SupervisorHealth.DEGRADED
                self._persist_health()
                return {
                    "ok": False,
                    "fatal": True,
                    "reason": "schema_error_recover_expired",
                    "health": self.health.value,
                    "errors": tick_errors,
                }

        # --- Per-child isolation ---
        self._reap_exited(tick_errors)

        # --- Per-pool isolation ---
        self.reconcile_pools(tick_errors)

        pools = self._safe_pool_status(tick_errors)
        decode_diags = self.registry.pop_decode_diagnostics()
        if decode_diags:
            tick_errors.append(
                {
                    "phase": "registry_decode",
                    "error": f"{len(decode_diags)} quarantined row(s)",
                    "diagnostics": decode_diags,
                    "transient": False,
                }
            )

        degraded = bool(tick_errors) or any(p.degraded for p in self._pools.values())
        if tick_errors:
            self.consecutive_tick_failures += 1
            self.last_tick_error = str(tick_errors[-1].get("error") or tick_errors[-1])
            self.health = SupervisorHealth.DEGRADED
        elif degraded:
            self.health = SupervisorHealth.DEGRADED
        else:
            self.health = SupervisorHealth.RUNNING
            self.consecutive_tick_failures = 0
            self.last_tick_error = None
            self.last_successful_tick_at = now_s

        self._persist_health()
        return {
            "ok": True,
            "degraded": degraded,
            "fatal": False,
            "health": self.health.value,
            "owned": len(self._owned),
            "pools": pools,
            "errors": tick_errors,
            "consecutive_tick_failures": self.consecutive_tick_failures,
            "last_tick_error": self.last_tick_error,
        }

    def set_desired_count(self, pool_id: str, count: int) -> None:
        if pool_id not in self._pools:
            raise KeyError(pool_id)
        defn = POOL_CATALOG[pool_id]
        self._pools[pool_id].desired = max(0, min(int(count), defn.max_count))
        self.settings.pool_counts[pool_id] = self._pools[pool_id].desired
        self.reconcile_pools()

    def reconcile_pools(self, tick_errors: list[dict[str, Any]] | None = None) -> None:
        errors = tick_errors if tick_errors is not None else []
        for pool_id, state in self._pools.items():
            try:
                self._reconcile_one_pool(pool_id, state)
            except Exception as exc:  # noqa: BLE001 — per-pool isolation
                # Reduce log spam for expected per-pool isolation failures under broken schema.
                logger.warning("reconcile pool %s failed: %s", pool_id, exc)
                state.degraded = True
                state.degraded_reason = f"pool_reconcile_failed: {exc}"
                errors.append(
                    {
                        "phase": "reconcile_pool",
                        "pool_id": pool_id,
                        "error": str(exc),
                        "transient": is_transient_sqlite_error(exc),
                    }
                )
        try:
            self._announce_started_pools()
        except Exception:  # noqa: BLE001
            pass

    def _reconcile_one_pool(self, pool_id: str, state: PoolRuntimeState) -> None:
        if state.degraded and time.time() < state.cooldown_until:
            return
        # Clear cooldown degradation after window if crashes stopped.
        if state.degraded and time.time() >= state.cooldown_until:
            state.degraded = False
            state.degraded_reason = None

        live = [
            w
            for w in self.registry.list(pool_id=pool_id)
            if w.worker_id in self._owned
            and w.state
            not in {
                WorkerInstanceState.STOPPED,
                WorkerInstanceState.STALE,
                WorkerInstanceState.CRASHED,
                WorkerInstanceState.DRAINING,
                WorkerInstanceState.INCOMPATIBLE,
                WorkerInstanceState.DEGRADED,
            }
        ]
        # Scale up
        while len(live) < state.desired and not (
            state.degraded and time.time() < state.cooldown_until
        ):
            try:
                owned = self._spawn(pool_id, slot=len(live))
            except Exception as exc:  # noqa: BLE001
                self._record_crash(pool_id, str(exc))
                try:
                    self._events.pool_start_failed(pool_id, reason=str(exc))
                except Exception:  # noqa: BLE001
                    pass
                break
            live.append(
                WorkerRegistration(
                    worker_id=owned.worker_id,
                    pool_id=pool_id,
                    slot=owned.slot,
                    pid=owned.pid,
                    process_start_identity=owned.process_start_identity,
                )
            )
            # Restart visibility when recovering after a crash window.
            attempts = self._restart_attempts.get(pool_id, 0)
            if attempts > 0:
                try:
                    self._events.worker_restarted(
                        pool=pool_id,
                        worker_id=owned.worker_id,
                        attempt=attempts,
                    )
                except Exception:  # noqa: BLE001
                    pass
                self._restart_attempts[pool_id] = 0
        # Scale down — drain excess; do not kill active non-preemptible jobs.
        excess = len(live) - state.desired
        if excess > 0:
            for reg in sorted(live, key=lambda r: r.slot, reverse=True)[:excess]:
                proc = self._owned.get(reg.worker_id)
                if proc is None:
                    continue
                if reg.current_job_id:
                    proc.draining = True
                    try:
                        self.registry.mark_state(reg.worker_id, WorkerInstanceState.DRAINING)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("mark_draining failed %s: %s", reg.worker_id, exc)
                    continue
                try:
                    terminate_owned(proc, grace_seconds=5.0)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("terminate_owned failed %s: %s", reg.worker_id, exc)
                try:
                    self.registry.mark_state(reg.worker_id, WorkerInstanceState.STOPPED)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("mark_stopped failed %s: %s", reg.worker_id, exc)
                self._owned.pop(reg.worker_id, None)

    def _spawn(self, pool_id: str, *, slot: int) -> OwnedProcess:
        defn = POOL_CATALOG[pool_id]
        worker_id = f"{pool_id}-{slot}-{uuid.uuid4().hex[:8]}"
        # Spawn outside any registry transaction (connect() already short).
        owned = spawn_worker_process(
            worker_id=worker_id,
            pool_id=pool_id,
            slot=slot,
            entrypoint=defn.entrypoint,
            cwd=self.repo_root,
            log_dir=self.log_dir,
            env={
                "LEVIATHAN_DATABASE_PATH": str(self.db_path),
                "LEVIATHAN_WORKER_SUPERVISOR_GENERATION": self.generation,
                "LEVIATHAN_WORKERS_LEASE_TTL_SECONDS": str(self.settings.lease_ttl_seconds),
                "LEVIATHAN_WORKERS_HEARTBEAT_SECONDS": str(self.settings.heartbeat_seconds),
                "LEVIATHAN_WORKERS_POLL_SECONDS": str(self.settings.poll_seconds),
            },
        )
        self._owned[worker_id] = owned
        try:
            self.registry.upsert(
                WorkerRegistration(
                    worker_id=worker_id,
                    pool_id=pool_id,
                    slot=slot,
                    pid=owned.pid,
                    process_start_identity=owned.process_start_identity,
                    protocol_version=WORKER_PROTOCOL_VERSION,
                    supported_job_kinds=defn.job_kinds,
                    started_at=utc_now(),
                    last_heartbeat_at=utc_now(),
                    state=WorkerInstanceState.STARTING,
                    supervisor_generation=self.generation,
                )
            )
        except Exception:
            # Registry write failed after spawn — terminate orphan and surface.
            try:
                terminate_owned(owned, grace_seconds=1.0)
            except Exception:  # noqa: BLE001
                pass
            self._owned.pop(worker_id, None)
            raise
        return owned

    def _reap_exited(self, tick_errors: list[dict[str, Any]] | None = None) -> None:
        errors = tick_errors if tick_errors is not None else []
        for worker_id, proc in list(self._owned.items()):
            try:
                exited = proc.popen is not None and proc.popen.poll() is not None
                if exited or not verify_owned(proc):
                    exit_code = None
                    try:
                        if proc.popen is not None:
                            exit_code = proc.popen.poll()
                    except Exception:  # noqa: BLE001
                        exit_code = None
                    try:
                        self.registry.mark_state(
                            worker_id,
                            WorkerInstanceState.CRASHED,
                            degraded_reason="process_exited",
                        )
                    except Exception as exc:  # noqa: BLE001
                        errors.append(
                            {
                                "phase": "reap_mark",
                                "worker_id": worker_id,
                                "error": str(exc),
                                "transient": is_transient_sqlite_error(exc),
                            }
                        )
                    try:
                        self._events.worker_crashed(
                            pool=proc.pool_id,
                            worker_id=worker_id,
                            exit_code=exit_code,
                            reason="process_exited",
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    self._owned.pop(worker_id, None)
                    self._record_crash(proc.pool_id, "process_exited")
                    self._restart_attempts[proc.pool_id] = (
                        self._restart_attempts.get(proc.pool_id, 0) + 1
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    {
                        "phase": "reap_child",
                        "worker_id": worker_id,
                        "error": str(exc),
                        "transient": False,
                    }
                )
                logger.exception("reap child %s failed", worker_id)

    def _record_crash(self, pool_id: str, reason: str) -> None:
        state = self._pools[pool_id]
        now = time.time()
        window = float(self.settings.restart_window_seconds)
        state.crash_timestamps = [t for t in state.crash_timestamps if now - t <= window]
        state.crash_timestamps.append(now)
        if len(state.crash_timestamps) >= int(self.settings.restart_max_attempts):
            n = len(state.crash_timestamps)
            backoff = min(
                self.settings.restart_max_backoff,
                self.settings.restart_base_backoff * (2 ** max(0, n - 1)),
            )
            state.degraded = True
            state.degraded_reason = f"WORKER_RESTART_EXHAUSTED: {reason}"
            state.cooldown_until = now + backoff
            try:
                self._events.emit_kind(
                    WorkerEventKind.WORKER_CRASHED,
                    pool=pool_id,
                    worker_id=f"{pool_id}-pool",
                    error_code="UITGESCHAKELD — restartlimiet bereikt",
                )
            except Exception:  # noqa: BLE001
                pass

    def _announce_started_pools(self) -> None:
        """Log pools that actually have owned processes after reconcile."""
        owned_by_pool: dict[str, int] = {}
        for proc in self._owned.values():
            owned_by_pool[proc.pool_id] = owned_by_pool.get(proc.pool_id, 0) + 1
        for pool_id, count in sorted(owned_by_pool.items()):
            if count <= 0 or pool_id in self._announced_pools:
                continue
            try:
                self._events.pool_started(pool_id, worker_count=count)
            except Exception:  # noqa: BLE001
                pass
            self._announced_pools.add(pool_id)
        # Also announce desired==0 pools? No — only actually started.

    def _safe_pool_status(self, tick_errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
        try:
            return self.pool_status()
        except Exception as exc:  # noqa: BLE001
            tick_errors.append(
                {
                    "phase": "pool_status",
                    "error": str(exc),
                    "transient": is_transient_sqlite_error(exc),
                }
            )
            logger.warning("pool_status failed: %s", exc)
            return [
                {
                    "pool_id": pid,
                    "desired": st.desired,
                    "degraded": True,
                    "degraded_reason": st.degraded_reason or "status_unavailable",
                    "owned": sum(1 for p in self._owned.values() if p.pool_id == pid),
                    "status_error": str(exc),
                }
                for pid, st in self._pools.items()
            ]

    def pool_status(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        quarantined = 0
        for pool_id, state in self._pools.items():
            try:
                regs = self.registry.list(pool_id=pool_id)
            except Exception as exc:  # noqa: BLE001
                out.append(
                    {
                        "pool_id": pool_id,
                        "desired": state.desired,
                        "degraded": True,
                        "degraded_reason": f"list_failed: {exc}",
                        "owned": sum(1 for p in self._owned.values() if p.pool_id == pool_id),
                    }
                )
                continue
            counts = {
                "starting": 0,
                "ready": 0,
                "busy": 0,
                "draining": 0,
                "degraded": 0,
                "incompatible": 0,
                "stale": 0,
                "other": 0,
            }
            for r in regs:
                if r.state in {
                    WorkerInstanceState.INCOMPATIBLE,
                    WorkerInstanceState.STALE,
                } and r.degraded_reason in {
                    "invalid_persisted_state",
                    "malformed_registry_json",
                    "registry_row_decode_failure",
                }:
                    quarantined += 1
                if r.worker_id not in self._owned and r.state not in {
                    WorkerInstanceState.READY,
                    WorkerInstanceState.BUSY,
                    WorkerInstanceState.STARTING,
                    WorkerInstanceState.DRAINING,
                }:
                    if r.state == WorkerInstanceState.INCOMPATIBLE:
                        counts["incompatible"] += 1
                    elif r.state == WorkerInstanceState.STALE:
                        counts["stale"] += 1
                    elif r.state == WorkerInstanceState.DEGRADED:
                        counts["degraded"] += 1
                    continue
                # Never count quarantined/corrupt rows as READY.
                if r.state in {
                    WorkerInstanceState.INCOMPATIBLE,
                    WorkerInstanceState.STALE,
                    WorkerInstanceState.DEGRADED,
                } and r.degraded_reason in {
                    "invalid_persisted_state",
                    "malformed_registry_json",
                    "registry_row_decode_failure",
                }:
                    counts["degraded"] += 1
                    continue
                key = {
                    WorkerInstanceState.STARTING: "starting",
                    WorkerInstanceState.READY: "ready",
                    WorkerInstanceState.BUSY: "busy",
                    WorkerInstanceState.DRAINING: "draining",
                    WorkerInstanceState.DEGRADED: "degraded",
                    WorkerInstanceState.INCOMPATIBLE: "incompatible",
                    WorkerInstanceState.STALE: "stale",
                }.get(r.state, "other")
                counts[key] += 1
            out.append(
                {
                    "pool_id": pool_id,
                    "desired": state.desired,
                    "degraded": state.degraded,
                    "degraded_reason": state.degraded_reason,
                    **counts,
                    "owned": sum(1 for p in self._owned.values() if p.pool_id == pool_id),
                }
            )
        if quarantined:
            for item in out:
                item.setdefault("quarantined_rows_total", quarantined)
        return out

    def public_status(self) -> dict[str, Any]:
        lease = self.registry.get_supervisor_lease() or {}
        return {
            "holder_id": self.holder_id,
            "generation": self.generation,
            "running": self._running,
            "health": self.health.value,
            "last_tick_at": self.last_tick_at,
            "last_successful_tick_at": self.last_successful_tick_at,
            "consecutive_tick_failures": self.consecutive_tick_failures,
            "last_tick_error": self.last_tick_error,
            "restart_count": self.restart_count,
            "settings": self.settings.public_dict(),
            "pools": self._safe_pool_status([]),
            "workers": [w.public_dict() for w in self.registry.list()],
            "reservations": self._safe_reservations(),
            "lease": {
                "holder_id": lease.get("holder_id"),
                "health_state": lease.get("health_state"),
                "expires_at": lease.get("expires_at"),
                "last_tick_at": lease.get("last_tick_at"),
                "last_successful_tick_at": lease.get("last_successful_tick_at"),
                "consecutive_tick_failures": lease.get("consecutive_tick_failures"),
                "last_tick_error": lease.get("last_tick_error"),
                "restart_count": lease.get("restart_count"),
                "degraded_reason": lease.get("degraded_reason"),
            },
            "truth": {
                "model_serving_not_owned_here": True,
                "pid_alone_is_not_ownership": True,
            },
        }

    def _safe_reservations(self) -> list[dict[str, Any]]:
        try:
            return self.admission.list_held()
        except Exception as exc:  # noqa: BLE001
            logger.warning("list_held failed: %s", exc)
            return []

    def _note_transient(self, phase: str, exc: BaseException) -> None:
        self.health = SupervisorHealth.DEGRADED
        self.last_tick_error = f"{phase}: {exc}"
        self.consecutive_tick_failures += 1

    def _record_tick_failure(self, exc: BaseException, *, phase: str) -> None:
        self.consecutive_tick_failures += 1
        self.last_tick_error = f"{phase}: {exc}"
        logger.error("supervisor tick failure phase=%s: %s", phase, exc)

    def _persist_health(self) -> None:
        try:
            self.registry.update_supervisor_health(
                holder_id=self.holder_id,
                health=self.health,
                last_tick_at=self.last_tick_at,
                last_successful_tick_at=self.last_successful_tick_at,
                consecutive_tick_failures=self.consecutive_tick_failures,
                last_tick_error=self.last_tick_error,
                restart_count=self.restart_count,
                degraded_reason=self.last_tick_error if self.health == SupervisorHealth.DEGRADED else None,
                clear_error=self.last_tick_error is None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("persist health failed: %s", exc)


def _looks_like_schema_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "no such table",
            "no such column",
            "has no column",
            "syntax error",
            "datatype mismatch",
        )
    )
