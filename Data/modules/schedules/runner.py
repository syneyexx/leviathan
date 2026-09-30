"""Schedule evaluation — enqueue targets only; never execute them."""

from __future__ import annotations

from typing import Any

from Data.modules.jobs import JobRuntime
from Data.modules.workflows import WorkflowRuntime, WorkflowStepDef

from .store import ScheduleStore, utc_now
from .types import ScheduleRecord, ScheduleTargetKind


def _resolve_target_pool(capability_id: str) -> str | None:
    """Let canonical pool routing choose the specialist owner (never hardcode general)."""
    try:
        from Data.modules.workers.pools import pool_for_capability

        pool = pool_for_capability(capability_id)
        return str(pool) if pool else None
    except Exception:  # noqa: BLE001
        return None


class ScheduleRunner:
    """Fire due schedules into JobRuntime or WorkflowRuntime (enqueue-only in production)."""

    def __init__(
        self,
        store: ScheduleStore,
        *,
        jobs: JobRuntime | None = None,
        workflows: WorkflowRuntime | None = None,
    ) -> None:
        self.store = store
        self.jobs = jobs
        self.workflows = workflows
        self.telemetry: dict[str, Any] = {
            "ticks": 0,
            "fired": 0,
            "errors": 0,
            "duplicates_suppressed": 0,
            "backpressure_skips": 0,
            "last_tick_at": None,
            "last_tick_duration_ms": None,
            "last_error": None,
        }
        self.queue_backpressure_limit = 50

    def configure_backpressure(self, *, limit: int = 50) -> None:
        self.queue_backpressure_limit = max(1, int(limit))

    def tick(self, *, execute: bool = False) -> list[dict[str, Any]]:
        """Fire due schedules.

        Production must use ``execute=False`` (enqueue only). ``execute=True`` is
        retained solely for explicit TEST-ONLY callers that still need inline drain.
        """
        if execute:
            # Documented test/legacy path — never used by scheduler worker or API.
            return self._tick_inner(execute=True)
        return self.tick_enqueue_only()

    def tick_enqueue_only(self) -> list[dict[str, Any]]:
        """Evaluate due schedules and enqueue targets — never executes jobs inline."""
        return self._tick_inner(execute=False)

    def _tick_inner(self, *, execute: bool) -> list[dict[str, Any]]:
        import time

        started = time.monotonic()
        self.telemetry["ticks"] = int(self.telemetry.get("ticks", 0)) + 1
        results: list[dict[str, Any]] = []
        try:
            # Global backpressure: when job queues are saturated, skip firing to
            # avoid duplicate research waves from scheduler races under load.
            if self.jobs is not None and self._queues_saturated():
                self.telemetry["backpressure_skips"] = (
                    int(self.telemetry.get("backpressure_skips", 0)) + 1
                )
                results.append(
                    {
                        "ok": False,
                        "backpressure": True,
                        "reason": "job_queue_saturated",
                        "limit": self.queue_backpressure_limit,
                    }
                )
                return results
            for schedule in self.store.due(now=utc_now()):
                try:
                    fired = self._fire(schedule, execute=execute)
                    self.store.mark_ran(schedule.schedule_id)
                    self.telemetry["fired"] = int(self.telemetry.get("fired", 0)) + 1
                    # Count idempotent reuse when occurrence already had a job.
                    if fired.get("idempotent_reuse"):
                        self.telemetry["duplicates_suppressed"] = (
                            int(self.telemetry.get("duplicates_suppressed", 0)) + 1
                        )
                    results.append({"schedule_id": schedule.schedule_id, "ok": True, **fired})
                except Exception as exc:  # noqa: BLE001
                    self.telemetry["errors"] = int(self.telemetry.get("errors", 0)) + 1
                    self.telemetry["last_error"] = str(exc)[:500]
                    results.append(
                        {"schedule_id": schedule.schedule_id, "ok": False, "error": str(exc)}
                    )
        finally:
            self.telemetry["last_tick_at"] = utc_now()
            self.telemetry["last_tick_duration_ms"] = round(
                (time.monotonic() - started) * 1000.0, 3
            )
        return results

    def _queues_saturated(self) -> bool:
        from .operating_pipeline import queue_is_saturated

        store = getattr(self.jobs, "store", None)
        if store is None:
            return False
        return queue_is_saturated(store, limit=self.queue_backpressure_limit)

    def _fire(self, schedule: ScheduleRecord, *, execute: bool = False) -> dict[str, Any]:
        if schedule.target_kind == ScheduleTargetKind.JOB:
            if self.jobs is None:
                raise RuntimeError("JobRuntime not configured for schedules")
            # Occurrence idempotency: schedule_id + next_run / occurrence key
            occurrence = str(
                schedule.target_payload.get("occurrence")
                or getattr(schedule, "next_run_at", None)
                or schedule.schedule_id
            )
            idem = f"schedule:{schedule.schedule_id}:{occurrence}"
            # Specialist routing — do NOT hardcode general.
            worker_pool = _resolve_target_pool(schedule.target_ref)
            payload = dict(schedule.target_payload or {})
            arguments = dict(payload.get("arguments") or {})
            # Allow top-level workflow_id for durable delay resumes.
            if payload.get("workflow_id") and "workflow_id" not in arguments:
                arguments["workflow_id"] = payload["workflow_id"]
            if payload.get("execution_id") and "workflow_id" not in arguments:
                arguments["workflow_id"] = payload["execution_id"]
            enqueue_kwargs: dict[str, Any] = {
                "capability_id": schedule.target_ref,
                "arguments": arguments,
                "approval_id": payload.get("approval_id"),
                "requested_by": f"schedule:{schedule.schedule_id}",
                "idempotency_key": idem,
                "domain": "schedules",
                "domain_entity_type": "schedule",
                "domain_entity_id": schedule.schedule_id,
            }
            if worker_pool:
                enqueue_kwargs["worker_pool"] = worker_pool
            # workflow.advance must land on the workflow pool.
            if schedule.target_ref == "workflow.advance":
                enqueue_kwargs["worker_pool"] = "workflow"
            job = self.jobs.enqueue(**enqueue_kwargs)
            # Detect idempotent reuse (duplicate occurrence after crash/reclaim).
            idempotent_reuse = False
            existing = None
            try:
                existing = self.jobs.store.get_by_idempotency_key(idem)
            except Exception:  # noqa: BLE001
                existing = None
            if existing is not None and existing.job_id == job.job_id:
                if schedule.last_run_at:
                    idempotent_reuse = True
            done = None
            if execute:
                # TEST-ONLY — production scheduler must never call process_next.
                done = self.jobs.process_next()
            # One-shot delay schedules must not recur.
            if (schedule.metadata or {}).get("one_shot"):
                try:
                    from .types import ScheduleStatus

                    self.store.set_status(schedule.schedule_id, ScheduleStatus.DISABLED)
                except Exception:  # noqa: BLE001
                    pass
            return {
                "target": "job",
                "job_id": job.job_id,
                "job_state": done.state.value if done else job.state.value,
                "worker_pool": getattr(job, "worker_pool", None) or worker_pool,
                "executed_inline": bool(execute),
                "occurrence": occurrence,
                "idempotent_reuse": idempotent_reuse,
            }
        if schedule.target_kind == ScheduleTargetKind.WORKFLOW:
            if self.workflows is None:
                raise RuntimeError("WorkflowRuntime not configured for schedules")
            # Prefer reusable definition target when target_ref is a known definition.
            definition_id = str(
                schedule.target_payload.get("workflow_id")
                or schedule.target_payload.get("definition_id")
                or ""
            )
            if not definition_id and hasattr(self.workflows, "store"):
                maybe = self.workflows.store.get_definition(schedule.target_ref)
                if maybe is not None:
                    definition_id = maybe.workflow_id
            if definition_id and hasattr(self.workflows, "run_definition"):
                from Data.modules.workflows.types import WorkflowDefinitionStatus

                definition = self.workflows.store.get_definition(definition_id)
                if definition is None:
                    raise RuntimeError(f"SCHEDULE stale workflow target: {definition_id}")
                if definition.status != WorkflowDefinitionStatus.ACTIVE:
                    return {
                        "target": "workflow",
                        "skipped": True,
                        "reason": "workflow_inactive",
                        "workflow_id": definition_id,
                        "definition_status": definition.status.value,
                    }
                execution, job = self.workflows.run_definition(
                    definition_id,
                    requested_by=f"schedule:{schedule.schedule_id}",
                    trigger_source="SCHEDULE",
                    inputs=dict(schedule.target_payload.get("inputs") or {}),
                    idempotency_key=f"schedule:{schedule.schedule_id}:{schedule.next_run_at}",
                )
                if execute and hasattr(self.workflows, "run"):
                    done = self.workflows.run(execution.execution_id)
                    return {
                        "target": "workflow",
                        "workflow_id": definition_id,
                        "execution_id": done.workflow_id,
                        "workflow_state": done.state.value,
                        "executed_inline": True,
                    }
                return {
                    "target": "workflow",
                    "workflow_id": definition_id,
                    "execution_id": execution.execution_id,
                    "workflow_state": execution.state.value,
                    "job_id": getattr(job, "job_id", None),
                    "executed_inline": False,
                }
            steps_raw = schedule.target_payload.get("steps") or []
            steps = [
                WorkflowStepDef(
                    step_id=str(item.get("step_id") or f"s{idx}"),
                    capability_id=str(item["capability_id"]),
                    arguments=dict(item.get("arguments") or {}),
                    approval_id=item.get("approval_id"),
                )
                for idx, item in enumerate(steps_raw)
            ]
            if not steps:
                # Allow target_ref as single knowledge.search convenience.
                steps = [
                    WorkflowStepDef(
                        step_id="s0",
                        capability_id=schedule.target_ref,
                        arguments=dict(schedule.target_payload.get("arguments") or {}),
                        approval_id=schedule.target_payload.get("approval_id"),
                    )
                ]
            wf = self.workflows.create(name=f"sched:{schedule.name}", steps=steps)
            # Production: enqueue durable workflow.advance. execute=True keeps the
            # legacy foreground path for tests that still expect inline completion.
            if execute:
                done = self.workflows.run(wf.workflow_id)
                return {
                    "target": "workflow",
                    "workflow_id": done.workflow_id,
                    "workflow_state": done.state.value,
                    "executed_inline": True,
                }
            if getattr(self.workflows, "job_runtime", None) is None and self.jobs is not None:
                self.workflows.bind_job_runtime(self.jobs)
            job = self.workflows.enqueue_advance(
                wf.workflow_id,
                requested_by=f"schedule:{schedule.schedule_id}",
            )
            refreshed = self.workflows.store.get(wf.workflow_id) or wf
            return {
                "target": "workflow",
                "workflow_id": refreshed.workflow_id,
                "workflow_state": refreshed.state.value,
                "job_id": job.job_id,
                "executed_inline": False,
            }
        raise ValueError(f"Unsupported target kind: {schedule.target_kind}")
