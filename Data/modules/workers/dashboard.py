"""Worker Fabric operator read-model.

Joins WorkerRegistry + JobRuntime + POOL_CATALOG into one aggregate dashboard.
Does not store a second source of truth — derives from existing durable state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from .events import format_duration_ms, resolve_human_title
from .metrics import sample_process_resources
from .pools import POOL_CATALOG
from .protocol import SupervisorHealth, WorkerInstanceState
from .registry import WorkerRegistry
from .settings import WorkerSettings, load_worker_settings

# States considered "live" for running-worker counts.
_LIVE_STATES = frozenset(
    {
        WorkerInstanceState.STARTING.value,
        WorkerInstanceState.READY.value,
        WorkerInstanceState.BUSY.value,
        WorkerInstanceState.DRAINING.value,
        WorkerInstanceState.DEGRADED.value,
    }
)

_IDLE_STATES = frozenset({WorkerInstanceState.READY.value})
_BUSY_STATES = frozenset({WorkerInstanceState.BUSY.value})
_FAILED_STATES = frozenset(
    {
        WorkerInstanceState.CRASHED.value,
        WorkerInstanceState.STALE.value,
        WorkerInstanceState.INCOMPATIBLE.value,
    }
)

# Optional pools that are not required for fabric health.
_OPTIONAL_POOLS = frozenset({"knowledge_commit", "rerank", "document_ai", "telemetry"})


def _iso_age_seconds(iso: str | None) -> float | None:
    if not iso:
        return None
    raw = str(iso).strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds())
    except ValueError:
        return None


def _pool_status_reason(pool_id: str, *, desired: int, running: int, defn: Any) -> tuple[str, str | None]:
    """Return (status, reason) for a pool row."""
    if pool_id == "knowledge_commit":
        return "DEPRECATED", "Owner: db_commit — bulk COMMIT_WRITE uses db_commit"
    if pool_id == "rerank" and desired <= 0:
        return "DISABLED", "backend not configured"
    if pool_id == "document_ai" and desired <= 0:
        return "UNAVAILABLE", "OCR backend missing"
    if pool_id == "telemetry" and desired <= 0:
        return "DISABLED", "API owns telemetry by default"
    if desired <= 0:
        return "DISABLED", "desired_count=0"
    if running <= 0:
        return "DEGRADED", f"desired={desired} · running=0"
    if running < desired:
        return "STARTING", f"desired={desired} · running={running}"
    return "HEALTHY", None


def _safe_job_summary(job: Any) -> dict[str, Any] | None:
    if job is None:
        return None
    meta = dict(getattr(job, "metadata", None) or {})
    args = dict(getattr(job, "arguments", None) or {})
    capability = str(getattr(job, "capability_id", None) or "")
    title = resolve_human_title(
        capability_id=capability,
        metadata=meta,
        arguments=args,
        domain=getattr(job, "domain", None),
        domain_entity_type=getattr(job, "domain_entity_type", None),
    )
    progress = getattr(job, "progress", None)
    progress_current = meta.get("progress_current")
    progress_total = meta.get("progress_total")
    if progress_current is None and progress is not None:
        try:
            # Job.progress is often 0..1 float.
            p = float(progress)
            if 0.0 <= p <= 1.0:
                progress_current = round(p * 100)
                progress_total = 100
            else:
                progress_current = p
        except (TypeError, ValueError):
            progress_current = None
    percent = None
    try:
        if progress_current is not None and progress_total not in (None, 0):
            percent = round(100.0 * float(progress_current) / float(progress_total), 1)
        elif progress is not None:
            p = float(progress)
            percent = round(p * 100.0, 1) if 0.0 <= p <= 1.0 else round(p, 1)
    except (TypeError, ValueError):
        percent = None

    started = getattr(job, "started_at", None) or getattr(job, "claimed_at", None)
    elapsed_s = _iso_age_seconds(started)
    return {
        "job_id": getattr(job, "job_id", None),
        "capability_id": capability,
        "state": getattr(getattr(job, "state", None), "value", getattr(job, "state", None)),
        "human_title": title,
        "phase": getattr(job, "phase", None) or meta.get("phase"),
        "message": getattr(job, "message", None),
        "domain": getattr(job, "domain", None),
        "domain_entity_type": getattr(job, "domain_entity_type", None),
        "domain_entity_id": getattr(job, "domain_entity_id", None),
        "parent_job_id": getattr(job, "parent_job_id", None),
        "root_job_id": getattr(job, "root_job_id", None),
        "trace_id": getattr(job, "trace_id", None),
        "progress": progress,
        "progress_current": progress_current,
        "progress_total": progress_total,
        "progress_percent": percent,
        "started_at": started,
        "elapsed_seconds": elapsed_s,
        "elapsed_display": format_duration_ms((elapsed_s or 0) * 1000) if elapsed_s is not None else None,
        "worker_pool": getattr(job, "worker_pool", None),
        "attempt_number": getattr(job, "attempt_number", None),
        "error_code": getattr(job, "error_code", None),
        "error": None,  # never expose raw error payloads here
    }


def _current_work_label(job_summary: dict[str, Any] | None, state: str) -> str:
    if job_summary:
        title = job_summary.get("human_title") or "job"
        phase = job_summary.get("phase")
        pct = job_summary.get("progress_percent")
        cur = job_summary.get("progress_current")
        tot = job_summary.get("progress_total")
        parts = [str(title)]
        if phase:
            parts.append(str(phase))
        if cur is not None and tot is not None:
            parts.append(f"{cur}/{tot}")
        elif pct is not None:
            parts.append(f"{pct}%")
        return " · ".join(parts)
    if state in _IDLE_STATES:
        return "waiting"
    if state == WorkerInstanceState.STARTING.value:
        return "starting"
    if state == WorkerInstanceState.DRAINING.value:
        return "draining"
    return "—"


def build_worker_fabric_dashboard(
    *,
    db_path: Any,
    job_getter: Callable[[str], Any] | None = None,
    list_jobs: Callable[..., list[Any]] | None = None,
    settings: WorkerSettings | None = None,
    include_resources: bool = True,
    recent_failures_limit: int = 40,
) -> dict[str, Any]:
    """Build the Worker Fabric dashboard aggregate."""
    wsettings = settings or load_worker_settings()
    registry = WorkerRegistry(db_path)
    registry.initialize()
    overrides = registry.list_pool_desired_overrides()
    registrations = registry.list()
    lease = registry.get_supervisor_lease() or {}
    health = lease.get("health_state") or SupervisorHealth.UNAVAILABLE.value

    # Job lookup cache for current_job_id joins.
    job_cache: dict[str, Any] = {}

    def _get_job(job_id: str | None) -> Any:
        if not job_id or job_getter is None:
            return None
        if job_id in job_cache:
            return job_cache[job_id]
        try:
            job = job_getter(job_id)
        except Exception:  # noqa: BLE001
            job = None
        job_cache[job_id] = job
        return job

    # Queue depths by pool.
    queues: dict[str, int] = {pid: 0 for pid in POOL_CATALOG}
    queued_jobs: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    if list_jobs is not None:
        try:
            from Data.modules.jobs.states import JobState

            for job in list_jobs(state=JobState.QUEUED, limit=500):
                pool = str(getattr(job, "worker_pool", None) or "general")
                queues[pool] = int(queues.get(pool, 0)) + 1
                summary = _safe_job_summary(job)
                if summary:
                    queued_jobs.append(summary)
        except Exception:  # noqa: BLE001
            pass
        try:
            from Data.modules.jobs.states import JobState

            for job in list_jobs(state=JobState.FAILED, limit=recent_failures_limit):
                summary = _safe_job_summary(job)
                if summary:
                    failures.append(
                        {
                            **summary,
                            "finished_at": getattr(job, "finished_at", None),
                            "error_code": getattr(job, "error_code", None),
                        }
                    )
        except Exception:  # noqa: BLE001
            pass

    workers_out: list[dict[str, Any]] = []
    by_pool: dict[str, list[dict[str, Any]]] = {pid: [] for pid in POOL_CATALOG}

    for reg in registrations:
        state = reg.state.value if hasattr(reg.state, "value") else str(reg.state)
        job = _get_job(reg.current_job_id)
        job_summary = _safe_job_summary(job)
        resources = sample_process_resources(int(reg.pid)) if include_resources else None
        hb_age = _iso_age_seconds(reg.last_heartbeat_at)
        row = {
            **reg.public_dict(),
            "display_name": f"{reg.pool_id}-{reg.slot}",
            "current_work": _current_work_label(job_summary, state),
            "current_job": job_summary,
            "current_capability": (job_summary or {}).get("capability_id"),
            "progress_current": (job_summary or {}).get("progress_current"),
            "progress_total": (job_summary or {}).get("progress_total"),
            "progress_percent": (job_summary or {}).get("progress_percent"),
            "elapsed_seconds": (job_summary or {}).get("elapsed_seconds"),
            "elapsed_display": (job_summary or {}).get("elapsed_display"),
            "heartbeat_age_seconds": hb_age,
            "resources": resources,
            "cpu_percent": (resources or {}).get("cpu_percent"),
            "rss_mb": (resources or {}).get("rss_mb"),
            "gpu_percent": (resources or {}).get("gpu_percent"),
            "vram_mb": (resources or {}).get("vram_mb"),
            "resource_class": (
                list(POOL_CATALOG[reg.pool_id].resource_classes)
                if reg.pool_id in POOL_CATALOG
                else []
            ),
        }
        workers_out.append(row)
        by_pool.setdefault(reg.pool_id, []).append(row)

    pools_out: list[dict[str, Any]] = []
    desired_total = 0
    enabled_pools = 0
    required_degraded = 0

    for pid, defn in POOL_CATALOG.items():
        desired = int(overrides.get(pid, wsettings.desired_count(pid)))
        regs = by_pool.get(pid) or []
        running = sum(1 for r in regs if str(r.get("state")) in _LIVE_STATES)
        ready = sum(1 for r in regs if str(r.get("state")) in _IDLE_STATES)
        busy = sum(1 for r in regs if str(r.get("state")) in _BUSY_STATES)
        draining = sum(1 for r in regs if str(r.get("state")) == WorkerInstanceState.DRAINING.value)
        degraded = sum(1 for r in regs if str(r.get("state")) == WorkerInstanceState.DEGRADED.value)
        failed = sum(1 for r in regs if str(r.get("state")) in _FAILED_STATES)
        starting = sum(1 for r in regs if str(r.get("state")) == WorkerInstanceState.STARTING.value)
        status, reason = _pool_status_reason(pid, desired=desired, running=running, defn=defn)
        if desired > 0:
            enabled_pools += 1
            desired_total += desired
            if status == "DEGRADED" and pid not in _OPTIONAL_POOLS:
                required_degraded += 1
        restarts = sum(int(r.get("restart_count") or 0) for r in regs)
        pools_out.append(
            {
                **defn.public_dict(),
                "desired": desired,
                "env_desired": wsettings.desired_count(pid),
                "override": pid in overrides,
                "instances": len(regs),
                "running": running,
                "ready": ready,
                "idle": ready,
                "busy": busy,
                "draining": draining,
                "degraded": degraded,
                "failed": failed,
                "starting": starting,
                "queued": int(queues.get(pid, 0)),
                "restarts": restarts,
                "status": status,
                "status_reason": reason,
                "optional": pid in _OPTIONAL_POOLS,
                "workers": regs,
            }
        )

    running_total = sum(1 for w in workers_out if str(w.get("state")) in _LIVE_STATES)
    busy_total = sum(1 for w in workers_out if str(w.get("state")) in _BUSY_STATES)
    idle_total = sum(1 for w in workers_out if str(w.get("state")) in _IDLE_STATES)
    failed_total = sum(1 for w in workers_out if str(w.get("state")) in _FAILED_STATES)
    queue_total = sum(v for k, v in queues.items() if not k.startswith("__"))

    supervisor_ready = str(health).upper() in {
        SupervisorHealth.RUNNING.value,
        "RUNNING",
    }
    fabric_status = "READY"
    if not supervisor_ready:
        fabric_status = "DEGRADED"
    elif required_degraded > 0:
        fabric_status = "DEGRADED"
    elif running_total < desired_total:
        fabric_status = "STARTING"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": {
            "pools_total": len(POOL_CATALOG),
            "pools_enabled": enabled_pools,
            "desired_workers": desired_total,
            "running_workers": running_total,
            "busy_workers": busy_total,
            "idle_workers": idle_total,
            "failed_workers": failed_total,
            "queue_depth": queue_total,
            "degraded_pools": required_degraded,
            "fabric_status": fabric_status,
        },
        "control_plane": {
            "role": "API / CONTROL PLANE",
            "status": "READY",
        },
        "supervisor": {
            "health": health,
            "status": "READY" if supervisor_ready else "DEGRADED",
            "holder_id": lease.get("holder_id"),
            "holder_pid": lease.get("holder_pid"),
            "expires_at": lease.get("expires_at"),
            "last_heartbeat_at": lease.get("last_heartbeat_at"),
            "last_tick_at": lease.get("last_tick_at"),
            "last_successful_tick_at": lease.get("last_successful_tick_at"),
            "consecutive_tick_failures": lease.get("consecutive_tick_failures") or 0,
            "last_tick_error": lease.get("last_tick_error"),
            "restart_count": lease.get("restart_count") or 0,
            "degraded_reason": lease.get("degraded_reason"),
        },
        "pools": pools_out,
        "workers": workers_out,
        "queues": [{"pool_id": pid, "queued": queues.get(pid, 0)} for pid in POOL_CATALOG],
        "queued_jobs": queued_jobs[:100],
        "failures": failures[:recent_failures_limit],
        "settings": wsettings.public_dict(),
        "truth": {
            "no_mock_workers": True,
            "derived_from_registry_and_jobs": True,
            "gpu_null_when_unattributed": True,
            "optional_disabled_pools_visible": True,
            "active_workers_not_agent_count": True,
        },
    }


def build_worker_detail(
    worker_id: str,
    *,
    db_path: Any,
    job_getter: Callable[[str], Any] | None = None,
    include_resources: bool = True,
) -> dict[str, Any] | None:
    """Single-worker inspector payload."""
    registry = WorkerRegistry(db_path)
    registry.initialize()
    reg = registry.get(worker_id)
    if reg is None:
        return None
    job = None
    if job_getter and reg.current_job_id:
        try:
            job = job_getter(reg.current_job_id)
        except Exception:  # noqa: BLE001
            job = None
    job_summary = _safe_job_summary(job)
    state = reg.state.value if hasattr(reg.state, "value") else str(reg.state)
    resources = sample_process_resources(int(reg.pid)) if include_resources else None
    defn = POOL_CATALOG.get(reg.pool_id)
    return {
        "worker": {
            **reg.public_dict(),
            "display_name": f"{reg.pool_id}-{reg.slot}",
            "current_work": _current_work_label(job_summary, state),
            "current_job": job_summary,
            "resources": resources,
            "heartbeat_age_seconds": _iso_age_seconds(reg.last_heartbeat_at),
            "resource_class": list(defn.resource_classes) if defn else [],
        },
        "pool": defn.public_dict() if defn else None,
        "truth": {
            "no_secret_payloads": True,
            "derived_from_registry_and_jobs": True,
        },
    }
