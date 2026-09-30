"""Helpers to decide when Control Plane may enqueue model_runtime work.

Worker Fabric allows model_runtime to scale to zero when idle. Callers must
therefore be able to enqueue against a *cold but valid* pool so queue demand
can wake the singleton worker. Requiring READY/BUSY before enqueue creates a
deadlock (no demand → never starts).

Truth layers (kept separate):
  - pool configured
  - supervisor available
  - pool cold / starting / ready
  - pool unavailable
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ModelRuntimePoolAvailability(str, Enum):
    """Operator-visible model_runtime pool availability (not provider health)."""

    DISABLED = "DISABLED"
    SUPERVISOR_UNAVAILABLE = "SUPERVISOR_UNAVAILABLE"
    COLD = "COLD"
    STARTING = "STARTING"
    READY = "READY"
    UNAVAILABLE = "UNAVAILABLE"


def _parse_iso(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _supervisor_lease_accepts_work(lease: dict[str, Any] | None) -> tuple[bool, str]:
    """True when a live WorkerSupervisor lease can cold-start pools."""
    if not lease:
        return False, "no_supervisor_lease"
    health = str(lease.get("health_state") or "").upper()
    if health in {"LEASE_LOST", "STOPPING", "STOPPED", "UNAVAILABLE"}:
        return False, f"supervisor_health_{health.lower() or 'unknown'}"
    # Parent bootstrap marks DEGRADED with holder_id=parent-bootstrap when
    # restart budget is exhausted — that cannot spawn workers.
    holder_id = str(lease.get("holder_id") or "")
    if holder_id == "parent-bootstrap":
        return False, "supervisor_parent_unavailable"
    if health == "DEGRADED" and lease.get("degraded_reason"):
        reason = str(lease.get("degraded_reason") or "")
        if "unavailable" in reason.lower() or "restart" in reason.lower():
            return False, "supervisor_degraded_unavailable"

    expires = _parse_iso(lease.get("expires_at"))
    now = datetime.now(timezone.utc)
    if expires is not None and now >= expires:
        return False, "supervisor_lease_expired"

    holder_pid = lease.get("holder_pid")
    try:
        pid = int(holder_pid) if holder_pid is not None else 0
    except (TypeError, ValueError):
        pid = 0
    if pid <= 0:
        return False, "supervisor_pid_missing"
    try:
        from Data.modules.common.process import pid_is_alive

        if not pid_is_alive(pid):
            return False, "supervisor_pid_dead"
    except Exception:  # noqa: BLE001
        # If PID check fails unexpectedly, still trust unexpired RUNNING lease.
        if health != "RUNNING":
            return False, "supervisor_pid_check_failed"

    if health in {"", "RUNNING", "DEGRADED"}:
        return True, "supervisor_running"
    return False, f"supervisor_health_{health.lower()}"


def model_runtime_workers_ready(database_path: Any | None = None) -> bool:
    """True when the singleton model_runtime worker is READY or BUSY.

    Kept for warm-path callers / snapshots. Prefer
    ``model_runtime_can_accept_jobs`` for enqueue gates.
    """
    snap = model_runtime_readiness_snapshot(database_path)
    return snap.get("poolState") == ModelRuntimePoolAvailability.READY.value


def model_runtime_can_accept_jobs(database_path: Any | None = None) -> bool:
    """True when enqueue is allowed: warm worker OR cold-startable pool."""
    return bool(model_runtime_readiness_snapshot(database_path).get("acceptJobs"))


def model_runtime_readiness_snapshot(database_path: Any | None = None) -> dict[str, Any]:
    """Separate worker readiness from serving-backend / model readiness."""
    pool_state = ModelRuntimePoolAvailability.UNAVAILABLE
    accept = False
    reason = "unknown"
    configured = 0
    workers_enabled = False
    supervisor_enabled = False
    supervisor_ok = False
    supervisor_reason = "unchecked"
    worker_states: list[str] = []
    warm = False
    starting = False

    try:
        from Data.modules.workers.settings import load_worker_settings

        settings = load_worker_settings()
        workers_enabled = bool(settings.enabled)
        supervisor_enabled = bool(settings.supervisor_enabled)
        configured = int(settings.desired_count("model_runtime"))
        if not workers_enabled or not supervisor_enabled:
            pool_state = ModelRuntimePoolAvailability.DISABLED
            reason = "workers_or_supervisor_disabled"
        elif configured <= 0:
            pool_state = ModelRuntimePoolAvailability.DISABLED
            reason = "pool_desired_count_zero"
    except Exception as exc:  # noqa: BLE001
        pool_state = ModelRuntimePoolAvailability.UNAVAILABLE
        reason = f"settings_error:{type(exc).__name__}"

    if pool_state != ModelRuntimePoolAvailability.DISABLED:
        try:
            from pathlib import Path

            from Data.modules.workers.protocol import WorkerInstanceState
            from Data.modules.workers.registry import WorkerRegistry

            if database_path is None:
                from Data.backend.config import load_settings

                database_path = load_settings().database_path
            registry = WorkerRegistry(Path(database_path))
            registry.initialize()
            workers = registry.list(pool_id="model_runtime")
            worker_states = [
                (w.state.value if hasattr(w.state, "value") else str(w.state)) for w in workers
            ]
            warm = any(
                w.state in {WorkerInstanceState.READY, WorkerInstanceState.BUSY}
                for w in workers
            )
            starting = any(w.state == WorkerInstanceState.STARTING for w in workers)

            lease = registry.get_supervisor_lease()
            supervisor_ok, supervisor_reason = _supervisor_lease_accepts_work(lease)

            if warm:
                pool_state = ModelRuntimePoolAvailability.READY
                accept = True
                reason = "worker_ready"
            elif starting and supervisor_ok:
                pool_state = ModelRuntimePoolAvailability.STARTING
                accept = True
                reason = "worker_starting"
            elif supervisor_ok:
                pool_state = ModelRuntimePoolAvailability.COLD
                accept = True
                reason = "cold_startable"
            else:
                pool_state = ModelRuntimePoolAvailability.SUPERVISOR_UNAVAILABLE
                accept = False
                reason = supervisor_reason
        except Exception as exc:  # noqa: BLE001
            pool_state = ModelRuntimePoolAvailability.UNAVAILABLE
            accept = False
            reason = f"registry_error:{type(exc).__name__}"

    return {
        "pool": "model_runtime",
        "state": (
            "READY"
            if pool_state == ModelRuntimePoolAvailability.READY
            else (
                "STARTING"
                if pool_state == ModelRuntimePoolAvailability.STARTING
                else (
                    "COLD"
                    if pool_state == ModelRuntimePoolAvailability.COLD
                    else "UNAVAILABLE"
                )
            )
        ),
        "poolState": pool_state.value,
        "acceptJobs": accept,
        "reason": reason,
        "configuredCount": configured,
        "workersEnabled": workers_enabled,
        "supervisorEnabled": supervisor_enabled,
        "supervisorAvailable": supervisor_ok,
        "supervisorReason": supervisor_reason,
        "workerStates": worker_states,
        "warm": warm,
        "starting": starting,
        "cold": pool_state == ModelRuntimePoolAvailability.COLD,
        "truth": {
            "worker_ready_is_not_backend_ready": True,
            "worker_ready_is_not_model_loaded": True,
            "provider_health_is_not_worker_ready": True,
            "cold_pool_may_accept_queued_jobs": True,
            "queue_demand_wakes_scale_to_zero": True,
        },
    }
