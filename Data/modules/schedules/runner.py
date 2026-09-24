from __future__ import annotations

from typing import Any, Protocol

from Data.modules.jobs import JobRuntime
from Data.modules.workflows import WorkflowRuntime, WorkflowStepDef

from .store import ScheduleStore, utc_now
from .types import ScheduleRecord, ScheduleTargetKind


class ScheduleRunner:
    """Fire due schedules into JobRuntime or WorkflowRuntime."""

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
        self.telemetry: dict[str, Any] = {"ticks": 0, "fired": 0, "errors": 0}

    def tick(self, *, execute: bool = False) -> list[dict[str, Any]]:
        """Fire due schedules.

        Production default ``execute=False`` enqueues only. Pass ``execute=True``
        for legacy tests that still expect inline ``process_next``.
        """
        self.telemetry["ticks"] += 1
        results: list[dict[str, Any]] = []
        for schedule in self.store.due(now=utc_now()):
            try:
                fired = self._fire(schedule, execute=execute)
                self.store.mark_ran(schedule.schedule_id)
                self.telemetry["fired"] += 1
                results.append({"schedule_id": schedule.schedule_id, "ok": True, **fired})
            except Exception as exc:  # noqa: BLE001
                self.telemetry["errors"] += 1
                results.append(
                    {"schedule_id": schedule.schedule_id, "ok": False, "error": str(exc)}
                )
        return results

    def tick_enqueue_only(self) -> list[dict[str, Any]]:
        """Evaluate due schedules and enqueue targets — never executes jobs inline."""
        self.telemetry["ticks"] = int(self.telemetry.get("ticks", 0)) + 1
        results: list[dict[str, Any]] = []
        for schedule in self.store.due(now=utc_now()):
            try:
                fired = self._fire(schedule, execute=False)
                self.store.mark_ran(schedule.schedule_id)
                self.telemetry["fired"] = int(self.telemetry.get("fired", 0)) + 1
                results.append({"schedule_id": schedule.schedule_id, "ok": True, **fired})
            except Exception as exc:  # noqa: BLE001
                self.telemetry["errors"] = int(self.telemetry.get("errors", 0)) + 1
                results.append(
                    {"schedule_id": schedule.schedule_id, "ok": False, "error": str(exc)}
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
            job = self.jobs.enqueue(
                capability_id=schedule.target_ref,
                arguments=dict(schedule.target_payload.get("arguments") or {}),
                approval_id=schedule.target_payload.get("approval_id"),
                requested_by=f"schedule:{schedule.schedule_id}",
                idempotency_key=idem,
                domain="schedules",
                domain_entity_type="schedule",
                domain_entity_id=schedule.schedule_id,
                worker_pool="general",
            )
            done = None
            if execute:
                # Legacy/test path only — production scheduler must not execute inline.
                done = self.jobs.process_next()
            return {
                "target": "job",
                "job_id": job.job_id,
                "job_state": done.state.value if done else job.state.value,
                "executed_inline": bool(execute),
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
