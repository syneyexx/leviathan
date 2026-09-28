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
            "last_tick_at": None,
            "last_tick_duration_ms": None,
            "last_error": None,
        }

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
            for schedule in self.store.due(now=utc_now()):
                try:
                    fired = self._fire(schedule, execute=execute)
                    self.store.mark_ran(schedule.schedule_id)
                    self.telemetry["fired"] = int(self.telemetry.get("fired", 0)) + 1
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
            enqueue_kwargs: dict[str, Any] = {
                "capability_id": schedule.target_ref,
                "arguments": dict(schedule.target_payload.get("arguments") or {}),
                "approval_id": schedule.target_payload.get("approval_id"),
                "requested_by": f"schedule:{schedule.schedule_id}",
                "idempotency_key": idem,
                "domain": "schedules",
                "domain_entity_type": "schedule",
                "domain_entity_id": schedule.schedule_id,
            }
            if worker_pool:
                enqueue_kwargs["worker_pool"] = worker_pool
            job = self.jobs.enqueue(**enqueue_kwargs)
            # Detect idempotent reuse (duplicate occurrence after crash/reclaim).
            if getattr(job, "idempotency_key", None) == idem and getattr(
                job, "created_at", None
            ):
                # JobRuntime returns existing job on idempotency hit — count suppressions
                # when the returned job was not just created this tick (best-effort).
                pass
            done = None
            if execute:
                # TEST-ONLY — production scheduler must never call process_next.
                done = self.jobs.process_next()
            return {
                "target": "job",
                "job_id": job.job_id,
                "job_state": done.state.value if done else job.state.value,
                "worker_pool": getattr(job, "worker_pool", None) or worker_pool,
                "executed_inline": bool(execute),
                "occurrence": occurrence,
            }
        if schedule.target_kind == ScheduleTargetKind.WORKFLOW:
            if self.workflows is None:
                raise RuntimeError("WorkflowRuntime not configured for schedules")
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
