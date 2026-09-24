"""Generic worker supervisor — singleton owner of background worker pools.

Does NOT own model-serving residency (Model Control Plane / ServingSupervisor).
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .admission import ResourceAdmission
from .pools import POOL_CATALOG
from .process import OwnedProcess, spawn_worker_process, terminate_owned, verify_owned
from .protocol import WORKER_PROTOCOL_VERSION, WorkerInstanceState, WorkerRegistration
from .registry import WorkerRegistry, utc_now
from .settings import WorkerSettings, load_worker_settings


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

    def initialize(self) -> None:
        self.registry.initialize()
        self.admission.initialize()

    def acquire(self) -> bool:
        return self.registry.try_acquire_supervisor_lease(
            holder_id=self.holder_id,
            holder_pid=os.getpid(),
            process_start_identity=self._process_start_identity,
            ttl_seconds=self.settings.supervisor_lease_ttl_seconds,
        )

    def start(self) -> None:
        self.initialize()
        if not self.acquire():
            raise RuntimeError("WORKER_SUPERVISOR_LEASE_HELD: another supervisor owns worker pools")
        self.registry.reconcile_stale(
            heartbeat_ttl_seconds=self.settings.lease_ttl_seconds * 2,
            supervisor_generation=self.generation,
        )
        self.admission.recover_expired()
        self._running = True
        self.reconcile_pools()

    def stop(self, *, grace_seconds: float | None = None) -> None:
        self._running = False
        grace = (
            self.settings.shutdown_grace_seconds
            if grace_seconds is None
            else float(grace_seconds)
        )
        # Mark draining then terminate owned processes.
        for worker_id, proc in list(self._owned.items()):
            proc.draining = True
            self.registry.mark_state(worker_id, WorkerInstanceState.DRAINING)
        deadline = time.time() + grace
        while time.time() < deadline and any(
            verify_owned(p) and p.popen and p.popen.poll() is None for p in self._owned.values()
        ):
            time.sleep(0.2)
        for worker_id, proc in list(self._owned.items()):
            terminate_owned(proc, grace_seconds=2.0)
            self.registry.mark_state(worker_id, WorkerInstanceState.STOPPED)
            self._owned.pop(worker_id, None)
        self.registry.release_supervisor_lease(holder_id=self.holder_id)

    def tick(self) -> dict[str, Any]:
        """One supervisor loop iteration — call from bootstrap or tests."""
        if not self._running:
            return {"ok": False, "reason": "not_running"}
        if not self.registry.heartbeat_supervisor_lease(
            holder_id=self.holder_id,
            ttl_seconds=self.settings.supervisor_lease_ttl_seconds,
        ):
            self._running = False
            return {"ok": False, "reason": "lost_supervisor_lease"}
        self.admission.recover_expired()
        self._reap_exited()
        self.reconcile_pools()
        return {"ok": True, "owned": len(self._owned), "pools": self.pool_status()}

    def set_desired_count(self, pool_id: str, count: int) -> None:
        if pool_id not in self._pools:
            raise KeyError(pool_id)
        defn = POOL_CATALOG[pool_id]
        self._pools[pool_id].desired = max(0, min(int(count), defn.max_count))
        self.settings.pool_counts[pool_id] = self._pools[pool_id].desired
        self.reconcile_pools()

    def reconcile_pools(self) -> None:
        for pool_id, state in self._pools.items():
            if state.degraded and time.time() < state.cooldown_until:
                continue
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
            # Scale down — drain excess; do not kill active non-preemptible jobs.
            excess = len(live) - state.desired
            if excess > 0:
                for reg in sorted(live, key=lambda r: r.slot, reverse=True)[:excess]:
                    proc = self._owned.get(reg.worker_id)
                    if proc is None:
                        continue
                    if reg.current_job_id:
                        proc.draining = True
                        self.registry.mark_state(reg.worker_id, WorkerInstanceState.DRAINING)
                        continue
                    terminate_owned(proc, grace_seconds=5.0)
                    self.registry.mark_state(reg.worker_id, WorkerInstanceState.STOPPED)
                    self._owned.pop(reg.worker_id, None)

    def _spawn(self, pool_id: str, *, slot: int) -> OwnedProcess:
        defn = POOL_CATALOG[pool_id]
        worker_id = f"{pool_id}-{slot}-{uuid.uuid4().hex[:8]}"
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
        return owned

    def _reap_exited(self) -> None:
        for worker_id, proc in list(self._owned.items()):
            exited = proc.popen is not None and proc.popen.poll() is not None
            if exited or not verify_owned(proc):
                self.registry.mark_state(
                    worker_id,
                    WorkerInstanceState.CRASHED,
                    degraded_reason="process_exited",
                )
                self._owned.pop(worker_id, None)
                self._record_crash(proc.pool_id, "process_exited")

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

    def pool_status(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for pool_id, state in self._pools.items():
            regs = self.registry.list(pool_id=pool_id)
            counts = {
                "starting": 0,
                "ready": 0,
                "busy": 0,
                "draining": 0,
                "degraded": 0,
                "other": 0,
            }
            for r in regs:
                if r.worker_id not in self._owned and r.state not in {
                    WorkerInstanceState.READY,
                    WorkerInstanceState.BUSY,
                    WorkerInstanceState.STARTING,
                    WorkerInstanceState.DRAINING,
                }:
                    continue
                key = {
                    WorkerInstanceState.STARTING: "starting",
                    WorkerInstanceState.READY: "ready",
                    WorkerInstanceState.BUSY: "busy",
                    WorkerInstanceState.DRAINING: "draining",
                    WorkerInstanceState.DEGRADED: "degraded",
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
        return out

    def public_status(self) -> dict[str, Any]:
        return {
            "holder_id": self.holder_id,
            "generation": self.generation,
            "running": self._running,
            "settings": self.settings.public_dict(),
            "pools": self.pool_status(),
            "workers": [w.public_dict() for w in self.registry.list()],
            "reservations": self.admission.list_held(),
            "truth": {
                "model_serving_not_owned_here": True,
                "pid_alone_is_not_ownership": True,
            },
        }
