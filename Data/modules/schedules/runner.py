from __future__ import annotations

from typing import Any

from Data.modules.jobs import JobRuntime
from Data.modules.workflows import WorkflowRuntime, WorkflowStepDef

from .store import ScheduleStore, utc_now
from .types import ScheduleRecord, ScheduleTargetKind


class ScheduleRunner:
    """Fire due schedules into JobRuntime or WorkflowRuntime.

    Wave 11: EVENT targets are armed until ``emit_event`` matches their
    ``metadata.event_name`` (or target_ref), then enqueue the same Jobs/Workflows.
    """

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
            "events_received": 0,
            "event_matched": 0,
        }
        self._armed_events: list[ScheduleRecord] = []

    def tick(self) -> list[dict[str, Any]]:
        self.telemetry["ticks"] += 1
        results: list[dict[str, Any]] = []
        for schedule in self.store.due(now=utc_now()):
            if schedule.target_kind == ScheduleTargetKind.EVENT:
                # Interval tick only re-arms; firing happens on emit_event.
                self._armed_events = [
                    s for s in self._armed_events if s.schedule_id != schedule.schedule_id
                ]
                self._armed_events.append(schedule)
                self.store.mark_ran(schedule.schedule_id)
                results.append(
                    {
                        "schedule_id": schedule.schedule_id,
                        "ok": True,
                        "target": "event",
                        "armed": True,
                        "event_name": schedule.metadata.get("event_name") or schedule.target_ref,
                    }
                )
                continue
            try:
                fired = self._fire(schedule)
                self.store.mark_ran(schedule.schedule_id)
                self.telemetry["fired"] += 1
                results.append({"schedule_id": schedule.schedule_id, "ok": True, **fired})
            except Exception as exc:  # noqa: BLE001
                self.telemetry["errors"] += 1
                results.append(
                    {"schedule_id": schedule.schedule_id, "ok": False, "error": str(exc)}
                )
        return results

    def emit_event(
        self,
        event_name: str,
        *,
        payload: dict[str, Any] | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Match armed EVENT schedules and enqueue canonical Jobs/Workflows."""
        self.telemetry["events_received"] += 1
        results: list[dict[str, Any]] = []
        remaining: list[ScheduleRecord] = []
        for schedule in list(self._armed_events):
            expected = str(schedule.metadata.get("event_name") or schedule.target_ref)
            if expected != event_name:
                remaining.append(schedule)
                continue
            sched_project = schedule.metadata.get("project_id")
            if project_id and sched_project and sched_project != project_id:
                remaining.append(schedule)
                continue
            try:
                # EVENT schedules carry nested job/workflow target in payload.
                nested_kind = str(schedule.target_payload.get("enqueue_kind") or "JOB").upper()
                nested_ref = str(
                    schedule.target_payload.get("enqueue_ref") or schedule.target_payload.get("capability_id") or ""
                )
                if not nested_ref:
                    raise ValueError("EVENT schedule requires enqueue_ref/capability_id")
                synthetic = ScheduleRecord(
                    schedule_id=schedule.schedule_id,
                    name=schedule.name,
                    status=schedule.status,
                    target_kind=ScheduleTargetKind.JOB
                    if nested_kind == "JOB"
                    else ScheduleTargetKind.WORKFLOW,
                    target_ref=nested_ref,
                    interval_seconds=schedule.interval_seconds,
                    created_at=schedule.created_at,
                    updated_at=schedule.updated_at,
                    next_run_at=schedule.next_run_at,
                    last_run_at=schedule.last_run_at,
                    target_payload={
                        **dict(schedule.target_payload),
                        "arguments": {
                            **dict(schedule.target_payload.get("arguments") or {}),
                            **(payload or {}),
                            **({"project_id": project_id} if project_id else {}),
                        },
                    },
                    metadata=schedule.metadata,
                )
                fired = self._fire(synthetic)
                self.telemetry["fired"] += 1
                self.telemetry["event_matched"] += 1
                results.append(
                    {
                        "schedule_id": schedule.schedule_id,
                        "ok": True,
                        "event_name": event_name,
                        **fired,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                self.telemetry["errors"] += 1
                remaining.append(schedule)
                results.append(
                    {"schedule_id": schedule.schedule_id, "ok": False, "error": str(exc)}
                )
        self._armed_events = remaining
        return results

    def _fire(self, schedule: ScheduleRecord) -> dict[str, Any]:
        if schedule.target_kind == ScheduleTargetKind.JOB:
            if self.jobs is None:
                raise RuntimeError("JobRuntime not configured for schedules")
            job = self.jobs.enqueue(
                capability_id=schedule.target_ref,
                arguments=dict(schedule.target_payload.get("arguments") or {}),
                approval_id=schedule.target_payload.get("approval_id"),
                requested_by=f"schedule:{schedule.schedule_id}",
            )
            done = self.jobs.process_next()
            return {
                "target": "job",
                "job_id": job.job_id,
                "job_state": done.state.value if done else job.state.value,
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
                steps = [
                    WorkflowStepDef(
                        step_id="s0",
                        capability_id=schedule.target_ref,
                        arguments=dict(schedule.target_payload.get("arguments") or {}),
                        approval_id=schedule.target_payload.get("approval_id"),
                    )
                ]
            wf = self.workflows.create(name=f"sched:{schedule.name}", steps=steps)
            done = self.workflows.run(wf.workflow_id)
            return {
                "target": "workflow",
                "workflow_id": done.workflow_id,
                "workflow_state": done.state.value,
            }
        raise ValueError(f"Unsupported target kind: {schedule.target_kind}")
