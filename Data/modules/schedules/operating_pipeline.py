"""Autonomous operating scheduler pipeline (Wave 19).

Durable cadence for:
  market open / data refresh → research → qualification → paper candidate →
  monitoring → postmortem → lesson consolidation

Uses ScheduleStore next_run_at + JobRuntime idempotency. Does not invent a
second scheduler loop. Backpressure skips fire when job queues are saturated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .store import ScheduleStore
from .types import ScheduleRecord, ScheduleStatus, ScheduleTargetKind

# Ordered operating stages — each becomes (or reuses) one durable schedule.
# Capability IDs MUST exist in ExecutionGateway catalog / EXTERNAL_WORKER_CAPABILITIES.
OPERATING_STAGES: tuple[dict[str, Any], ...] = (
    {
        "stage": "market_open_data_refresh",
        "name_suffix": "data-refresh",
        "capability_id": "market_sim.data.scan",
        "interval_seconds": 300,
        "domain": "market_sim",
    },
    {
        "stage": "research",
        "name_suffix": "research",
        "capability_id": "market_sim.research_campaign",
        "interval_seconds": 900,
        "domain": "market_sim",
    },
    {
        "stage": "qualification",
        "name_suffix": "qualification",
        "capability_id": "market_sim.qualification_run",
        "interval_seconds": 1800,
        "domain": "market_sim",
    },
    {
        "stage": "paper_candidate",
        "name_suffix": "paper-candidate",
        "capability_id": "market_sim.autonomous_step",
        "interval_seconds": 600,
        "domain": "market_sim",
    },
    {
        "stage": "monitoring",
        "name_suffix": "monitoring",
        "capability_id": "market_sim.paper_forward_step",
        "interval_seconds": 900,
        "domain": "market_sim",
    },
    {
        "stage": "postmortem",
        "name_suffix": "postmortem",
        "capability_id": "market_sim.learning_run",
        "interval_seconds": 3600,
        "domain": "market_sim",
    },
    {
        "stage": "lesson_consolidation",
        "name_suffix": "lesson-consolidation",
        "capability_id": "market_sim.learning_run",
        "interval_seconds": 7200,
        "domain": "market_sim",
    },
)

DEFAULT_QUEUE_BACKPRESSURE_LIMIT = 50
PIPELINE_PREFIX = "leviathan-ops"


@dataclass
class OperatingPipelinePlan:
    pipeline_id: str
    universe: list[str] = field(default_factory=list)
    strategy_id: str | None = None
    schedules: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "pipeline_id": self.pipeline_id,
            "universe": list(self.universe),
            "strategy_id": self.strategy_id,
            "schedules": list(self.schedules),
            "stages": [s["stage"] for s in OPERATING_STAGES],
            "metadata": dict(self.metadata),
            "truth": {
                "durable_next_run_at": True,
                "no_fastapi_daemon_loop": True,
                "idempotent_schedule_ensure": True,
                "live_money": "BLOCKED",
            },
        }


def _schedule_name(pipeline_id: str, suffix: str) -> str:
    return f"{PIPELINE_PREFIX}:{pipeline_id}:{suffix}"


def ensure_operating_pipeline(
    store: ScheduleStore,
    *,
    pipeline_id: str = "default",
    universe: Sequence[str] | None = None,
    strategy_id: str | None = None,
    stages: Sequence[dict[str, Any]] | None = None,
    start_after_seconds: int = 0,
) -> OperatingPipelinePlan:
    """Idempotently create durable schedules for the autonomous operating loop."""
    pid = str(pipeline_id or "default").strip() or "default"
    symbols = [str(s).upper() for s in (universe or []) if str(s).strip()]
    stage_defs = list(stages or OPERATING_STAGES)
    existing_by_name: dict[str, ScheduleRecord] = {}
    try:
        for row in store.list(limit=500):
            existing_by_name[str(row.name)] = row
    except Exception:  # noqa: BLE001
        existing_by_name = {}

    created: list[dict[str, Any]] = []
    for stage in stage_defs:
        suffix = str(stage["name_suffix"])
        name = _schedule_name(pid, suffix)
        existing = existing_by_name.get(name)
        if existing is not None:
            created.append(
                {
                    "stage": stage["stage"],
                    "schedule_id": existing.schedule_id,
                    "name": existing.name,
                    "target_ref": existing.target_ref,
                    "interval_seconds": existing.interval_seconds,
                    "next_run_at": existing.next_run_at,
                    "reused": True,
                }
            )
            continue
        payload_args: dict[str, Any] = {
            "pipeline_id": pid,
            "stage": stage["stage"],
            "universe": symbols,
        }
        if strategy_id:
            payload_args["strategy_id"] = strategy_id
        record = store.create(
            name=name,
            target_kind=ScheduleTargetKind.JOB,
            target_ref=str(stage["capability_id"]),
            interval_seconds=max(30, int(stage.get("interval_seconds") or 300)),
            target_payload={"arguments": payload_args},
            metadata={
                "domain": stage.get("domain") or "market_sim",
                "purpose": "autonomous_operating_pipeline",
                "pipeline_id": pid,
                "stage": stage["stage"],
                "dedupe_key": name,
            },
            start_after_seconds=max(0, int(start_after_seconds)),
        )
        created.append(
            {
                "stage": stage["stage"],
                "schedule_id": record.schedule_id,
                "name": record.name,
                "target_ref": record.target_ref,
                "interval_seconds": record.interval_seconds,
                "next_run_at": record.next_run_at,
                "reused": False,
            }
        )

    return OperatingPipelinePlan(
        pipeline_id=pid,
        universe=symbols,
        strategy_id=strategy_id,
        schedules=created,
        metadata={"stage_count": len(created)},
    )


def pause_operating_pipeline(store: ScheduleStore, *, pipeline_id: str = "default") -> dict[str, Any]:
    pid = str(pipeline_id or "default").strip() or "default"
    prefix = f"{PIPELINE_PREFIX}:{pid}:"
    paused: list[str] = []
    for row in store.list(limit=500):
        if str(row.name).startswith(prefix):
            store.set_status(row.schedule_id, ScheduleStatus.PAUSED)
            paused.append(row.schedule_id)
    return {"pipeline_id": pid, "paused_schedule_ids": paused}


def queue_is_saturated(
    job_store: Any,
    *,
    limit: int = DEFAULT_QUEUE_BACKPRESSURE_LIMIT,
    states: Sequence[str] | None = None,
) -> bool:
    """True when durable job backlog exceeds backpressure limit."""
    from Data.modules.jobs.states import JobState

    wanted = list(states or [JobState.QUEUED.value, JobState.RETRY_WAIT.value])
    if hasattr(job_store, "count_by_states"):
        return int(job_store.count_by_states(wanted)) >= int(limit)
    # Fallback: bounded list probe (never invents counts).
    total = 0
    for state_name in wanted:
        try:
            state = JobState(state_name)
        except ValueError:
            continue
        rows = job_store.list(state=state, limit=int(limit) + 1)
        total += len(rows)
        if total >= int(limit):
            return True
    return False
