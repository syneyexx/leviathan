"""Agents page dashboard read-model.

Aggregates fleet, missions, workers, and inventory into a truthful operator
snapshot. Never invents healthy/success metrics when data is unavailable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any, Callable

from .fleet_types import ACTIVE_MISSION_STATUSES, AgentDefinition, AgentMission, MissionStatus
from .system_inventory import classify_fleet_agent


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _in_window(dt: datetime | None, *, start: datetime, end: datetime) -> bool:
    return dt is not None and start <= dt <= end


def _mission_duration_ms(mission: AgentMission) -> float | None:
    started = _parse_iso(mission.started_at)
    finished = _parse_iso(mission.finished_at)
    if started is None or finished is None:
        return None
    delta = (finished - started).total_seconds() * 1000.0
    if delta < 0:
        return None
    return delta


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = max(0, min(len(sorted_vals) - 1, int(round((p / 100.0) * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]


def team_bucket_for_agent(agent: AgentDefinition) -> str:
    """Deterministic team/domain grouping for distribution charts."""
    kind = str(agent.kind or "").lower()
    role = str(agent.role or "").lower()
    name = str(agent.name or "").lower()
    tags = {str(t).lower() for t in (agent.tags or [])}
    system_key = str(
        getattr(agent, "system_key", None)
        or (agent.metadata or {}).get("systemKey")
        or ""
    ).lower()
    blob = " ".join([kind, role, name, system_key, " ".join(sorted(tags))])

    if kind == "research" or "research" in blob or system_key == "research":
        return "Research"
    if kind == "coding" or "coding" in blob or "development" in blob or system_key == "coding":
        return "Development"
    if kind == "trading" or "trading" in blob or "trade" in blob:
        return "Trading"
    if kind == "orchestrator" or "plan" in blob or system_key == "planner":
        return "Planning"
    if "risk" in blob or "critic" in blob or "guard" in blob or system_key == "critic":
        return "Risk"
    if "memory" in blob:
        return "Memory"
    if "evaluat" in blob or "qa" in tags or "review" in tags:
        return "Evaluation"
    if "vision" in blob or "media" in blob or "image" in blob:
        return "Vision"
    return "Other"


def build_agents_dashboard(
    *,
    agents: list[AgentDefinition],
    missions: list[AgentMission],
    architecture_entries: list[dict[str, Any]],
    agents_enabled: bool,
    workers_payload: dict[str, Any] | None = None,
    jobs_by_pool: dict[str, dict[str, int]] | None = None,
    memory_writeback_count: int | None = None,
    window_hours: int = 24,
    failure_window_hours: int = 168,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a truthful dashboard read-model from already-loaded authoritative data."""
    now_utc = now or datetime.now(timezone.utc)
    window_h = max(1, min(int(window_hours), 168))
    fail_h = max(1, min(int(failure_window_hours), 720))
    window_start = now_utc - timedelta(hours=window_h)
    fail_start = now_utc - timedelta(hours=fail_h)
    generated_at = now_utc.isoformat(timespec="seconds")

    live_agents = [a for a in agents if not a.archived]
    fleet_agent_count = len(live_agents)
    orch_fleet = 0
    for agent in live_agents:
        ownership = classify_fleet_agent(agent)
        if ownership.get("entityType") == "orchestrator" or str(agent.kind) == "orchestrator":
            orch_fleet += 1
    system_orch = sum(
        1 for e in architecture_entries if str(e.get("entityType") or e.get("entity_type")) == "orchestrator"
    )
    orchestrator_count = orch_fleet + system_orch

    memory_linked = sum(
        1
        for a in live_agents
        if str(a.memory_policy or "default").strip().lower() not in {"", "none"}
    )

    active_missions = [m for m in missions if m.status.value in ACTIVE_MISSION_STATUSES]
    queued = [m for m in missions if m.status == MissionStatus.QUEUED]
    starting = [m for m in missions if m.status == MissionStatus.STARTING]
    running = [m for m in missions if m.status == MissionStatus.RUNNING]
    cancelling = [m for m in missions if m.status == MissionStatus.CANCELLING]

    def _terminal_in_window(start: datetime) -> tuple[list[AgentMission], list[AgentMission]]:
        completed: list[AgentMission] = []
        failed: list[AgentMission] = []
        for m in missions:
            finished = _parse_iso(m.finished_at) or _parse_iso(m.updated_at)
            if not _in_window(finished, start=start, end=now_utc):
                continue
            if m.status == MissionStatus.COMPLETED:
                completed.append(m)
            elif m.status == MissionStatus.FAILED:
                failed.append(m)
        return completed, failed

    completed_w, failed_w = _terminal_in_window(window_start)
    completed_f, failed_f = _terminal_in_window(fail_start)

    eligible_w = len(completed_w) + len(failed_w)
    success_rate = (len(completed_w) / eligible_w) if eligible_w else None

    durations = []
    for m in completed_w:
        ms = _mission_duration_ms(m)
        if ms is not None:
            durations.append(ms)
    durations.sort()
    avg_duration_ms = mean(durations) if durations else None
    p50 = _percentile(durations, 50)
    p95 = _percentile(durations, 95)

    # Hourly performance buckets over the primary window.
    buckets: list[dict[str, Any]] = []
    bucket_count = min(window_h, 24) if window_h <= 24 else 24
    bucket_seconds = (window_h * 3600) / bucket_count
    for i in range(bucket_count):
        b_start = window_start + timedelta(seconds=i * bucket_seconds)
        b_end = window_start + timedelta(seconds=(i + 1) * bucket_seconds)
        c = 0
        f = 0
        for m in missions:
            finished = _parse_iso(m.finished_at) or _parse_iso(m.updated_at)
            if finished is None or not (b_start <= finished < b_end):
                continue
            if m.status == MissionStatus.COMPLETED:
                c += 1
            elif m.status == MissionStatus.FAILED:
                f += 1
        elig = c + f
        buckets.append(
            {
                "start": b_start.isoformat(timespec="seconds"),
                "end": b_end.isoformat(timespec="seconds"),
                "completed": c,
                "failed": f,
                "successRate": (c / elig) if elig else None,
            }
        )

    # Failure / retry insights — retries come from job attempt_number when provided.
    retry_count = 0
    if jobs_by_pool is not None:
        # jobs_by_pool may include a special "__retries__" key from caller.
        retry_count = int((jobs_by_pool.get("__retries__") or {}).get("count") or 0)
    fail_eligible = len(completed_f) + len(failed_f) + retry_count
    failure_retry = {
        "windowHours": fail_h,
        "success": len(completed_f),
        "failed": len(failed_f),
        "retry": retry_count,
        "successRate": (len(completed_f) / (len(completed_f) + len(failed_f)))
        if (len(completed_f) + len(failed_f))
        else None,
        "retryRate": (retry_count / fail_eligible) if fail_eligible else None,
        "failedRate": (len(failed_f) / (len(completed_f) + len(failed_f)))
        if (len(completed_f) + len(failed_f))
        else None,
        "truth": {
            "retry_from_job_attempts_only": True,
            "cancelled_not_success": True,
        },
    }

    team_counts: dict[str, int] = {}
    for agent in live_agents:
        bucket = team_bucket_for_agent(agent)
        team_counts[bucket] = team_counts.get(bucket, 0) + 1
    team_distribution = [
        {"team": name, "count": count}
        for name, count in sorted(team_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    # Workers summary — only from real registry payload.
    workers_summary: dict[str, Any] = {
        "available": False,
        "active": None,
        "instances": None,
        "supervisorHealth": None,
        "pools": [],
        "truth": {"active_means_ready_or_busy_registry_instances": True},
    }
    if workers_payload is not None:
        workers = list(workers_payload.get("workers") or [])
        active_states = {"READY", "BUSY", "STARTING", "DRAINING"}
        active = sum(1 for w in workers if str(w.get("state") or "").upper() in active_states)
        pools_out = []
        for pool in workers_payload.get("pools") or []:
            pid = str(pool.get("pool_id") or pool.get("poolId") or "")
            instances = int(pool.get("instances") if pool.get("instances") is not None else len(pool.get("workers") or []))
            ready = int(pool.get("ready") or 0)
            busy = int(pool.get("busy") or 0)
            desired = int(pool.get("desired") or 0)
            max_count = int(pool.get("max_count") or pool.get("maxCount") or 0)
            live = ready + busy
            util = (live / desired) if desired > 0 else None
            queue = None
            if jobs_by_pool and pid in jobs_by_pool:
                queue = jobs_by_pool[pid].get("queued")
            pools_out.append(
                {
                    "poolId": pid,
                    "description": pool.get("description") or "",
                    "desired": desired,
                    "maxCount": max_count,
                    "instances": instances,
                    "ready": ready,
                    "busy": busy,
                    "draining": int(pool.get("draining") or 0),
                    "degraded": int(pool.get("degraded") or 0),
                    "queue": queue,
                    "utilization": util,
                    "resourceClasses": list(pool.get("resource_classes") or pool.get("resourceClasses") or []),
                    "jobKinds": list(pool.get("job_kinds") or pool.get("jobKinds") or []),
                    "entrypoint": pool.get("entrypoint"),
                }
            )
        supervisor = workers_payload.get("supervisor") or {}
        workers_summary = {
            "available": True,
            "active": active,
            "instances": len(workers),
            "supervisorHealth": supervisor.get("health"),
            "degradedReason": supervisor.get("degraded_reason") or supervisor.get("degradedReason"),
            "pools": pools_out,
            "truth": {
                "active_means_ready_or_busy_or_starting_or_draining": True,
                "stale_row_is_not_live_worker": True,
            },
        }

    # Orchestration flow — mapped from real mission statuses; verification/memory
    # only when honestly available.
    verifying = sum(
        1
        for m in running
        if bool((m.metadata or {}).get("verifying") or (m.metadata or {}).get("verification"))
    )
    flow = {
        "incoming": len(queued),
        "routing": len(starting),
        "orchestrators": orchestrator_count,
        "executing": len(running) + len(cancelling),
        "verifying": verifying if verifying else None,
        "memoryWriteback": memory_writeback_count,
        "completed": len(completed_w),
        "truth": {
            "incoming_is_queued_missions": True,
            "routing_is_starting_missions": True,
            "executing_is_running_or_cancelling": True,
            "verifying_only_when_mission_metadata_marks_it": True,
            "memory_writeback_null_when_untraced": memory_writeback_count is None,
            "completed_in_window_hours": window_h,
        },
    }

    return {
        "generatedAt": generated_at,
        "windowHours": window_h,
        "agentsEnabled": agents_enabled,
        "fleet": {
            "totalAgents": fleet_agent_count,
            "orchestrators": orchestrator_count,
            "orchestratorsFleet": orch_fleet,
            "orchestratorsSystem": system_orch,
            "architecture": len(architecture_entries),
            "memoryLinked": memory_linked,
            "truth": {
                "totalAgents_excludes_architecture_descriptors": True,
                "totalAgents_excludes_archived": True,
                "memoryLinked_is_non_none_memory_policy": True,
                "orchestrators_include_system_inventory_orchestrators": True,
            },
        },
        "workers": workers_summary,
        "missions": {
            "queued": len(queued),
            "starting": len(starting),
            "running": len(running),
            "cancelling": len(cancelling),
            "active": len(active_missions),
            "completedInWindow": len(completed_w),
            "failedInWindow": len(failed_w),
            "cancelledInWindow": sum(
                1
                for m in missions
                if m.status == MissionStatus.CANCELLED
                and _in_window(
                    _parse_iso(m.finished_at) or _parse_iso(m.updated_at),
                    start=window_start,
                    end=now_utc,
                )
            ),
        },
        "performance": {
            "successRate": success_rate,
            "avgDurationMs": avg_duration_ms,
            "p50DurationMs": p50,
            "p95DurationMs": p95,
            "sampleSize": len(durations),
            "eligibleTerminal": eligible_w,
            "buckets": buckets,
            "truth": {
                "successRate_completed_over_completed_plus_failed": True,
                "cancelled_excluded_from_success": True,
                "duration_from_started_at_to_finished_at": True,
                "null_when_no_eligible_terminal": success_rate is None,
            },
        },
        "failureRetry": failure_retry,
        "flow": flow,
        "teamDistribution": team_distribution,
        "lastSync": generated_at,
        "truth": {
            "read_model_only": True,
            "no_invented_metrics": True,
            "unknown_remains_null": True,
        },
    }


def collect_job_pool_stats(
    list_jobs: Callable[..., list[Any]],
    *,
    limit: int = 500,
) -> dict[str, dict[str, int]]:
    """Group queued jobs and retry evidence by worker_pool from JobStore/JobRuntime."""
    from Data.modules.jobs.states import JobState

    out: dict[str, dict[str, int]] = {}
    retries = 0
    try:
        queued = list_jobs(state=JobState.QUEUED, limit=limit)
    except Exception:  # noqa: BLE001
        queued = []
    for job in queued:
        pool = getattr(job, "worker_pool", None) or (job.get("worker_pool") if isinstance(job, dict) else None) or "general"
        bucket = out.setdefault(str(pool), {"queued": 0})
        bucket["queued"] = int(bucket.get("queued") or 0) + 1

    # Retry evidence: attempt_number > 1 on recent jobs (any state sample).
    try:
        recent = list_jobs(state=None, limit=limit)
    except TypeError:
        try:
            recent = list_jobs(limit=limit)
        except Exception:  # noqa: BLE001
            recent = []
    except Exception:  # noqa: BLE001
        recent = []
    for job in recent:
        attempt = getattr(job, "attempt_number", None)
        if attempt is None and isinstance(job, dict):
            attempt = job.get("attempt_number") or job.get("attemptNumber")
        try:
            if int(attempt or 0) > 1:
                retries += 1
        except (TypeError, ValueError):
            continue
    out["__retries__"] = {"count": retries}
    return out
