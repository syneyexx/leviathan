"""Project linked Job / Mission / Workflow state onto TaskRecords."""

from __future__ import annotations

from typing import Any, Protocol

from .types import BlockReasonCode, BoardColumn, TaskRecord


class _JobLike(Protocol):
    job_id: str
    state: Any
    progress: float | None
    phase: str | None
    error: str | None
    attempt_number: int
    started_at: str | None
    finished_at: str | None
    approval_id: str | None
    run_id: str | None


class _MissionLike(Protocol):
    mission_id: str
    status: Any
    result: dict[str, Any] | None
    error: str | None
    started_at: str | None
    finished_at: str | None
    run_id: str | None


class _WorkflowLike(Protocol):
    workflow_id: str
    state: Any
    error: str | None
    current_step: int
    run_id: str | None
    updated_at: str


ACTIVE_JOB_STATES = frozenset({"CREATED", "QUEUED", "RUNNING", "RETRY_WAIT", "CANCEL_REQUESTED"})
FAILED_JOB_STATES = frozenset({"FAILED"})
DONE_JOB_STATES = frozenset({"COMPLETED"})
CANCELLED_JOB_STATES = frozenset({"CANCELLED"})

ACTIVE_MISSION_STATES = frozenset({"queued", "starting", "running", "cancelling"})
FAILED_MISSION_STATES = frozenset({"failed", "interrupted", "disabled"})
DONE_MISSION_STATES = frozenset({"completed"})
CANCELLED_MISSION_STATES = frozenset({"cancelled"})

ACTIVE_WORKFLOW_STATES = frozenset({"CREATED", "RUNNING"})
FAILED_WORKFLOW_STATES = frozenset({"FAILED"})
DONE_WORKFLOW_STATES = frozenset({"COMPLETED"})
CANCELLED_WORKFLOW_STATES = frozenset({"CANCELLED"})


def _enum_val(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def apply_job_projection(task: TaskRecord, job: _JobLike) -> TaskRecord:
    state = _enum_val(job.state)
    task.job_id = job.job_id
    task.execution_state = state
    task.execution_progress = job.progress
    task.execution_phase = job.phase
    task.execution_error = job.error
    task.execution_attempt = int(getattr(job, "attempt_number", 1) or 1)
    task.execution_started_at = job.started_at
    task.execution_finished_at = job.finished_at
    if job.approval_id:
        task.approval_id = job.approval_id
    if job.run_id:
        task.run_id = job.run_id

    if state in FAILED_JOB_STATES:
        task.blocked = True
        task.blocked_reason_code = BlockReasonCode.EXECUTION_FAILED.value
        task.blocked_reason = job.error or "Job execution failed"
    elif state == "RETRY_WAIT":
        task.blocked = True
        task.blocked_reason_code = BlockReasonCode.RETRY_WAIT.value
        task.blocked_reason = "Waiting to retry failed job"
    elif state in DONE_JOB_STATES:
        if task.board_column != BoardColumn.DONE:
            # Do not auto-move board; surface completion via execution only.
            pass
        if task.blocked_reason_code in {
            BlockReasonCode.EXECUTION_FAILED.value,
            BlockReasonCode.RETRY_WAIT.value,
        }:
            task.blocked = False
            task.blocked_reason = None
            task.blocked_reason_code = None
    return task


def apply_mission_projection(task: TaskRecord, mission: _MissionLike) -> TaskRecord:
    state = _enum_val(mission.status)
    task.mission_id = mission.mission_id
    task.execution_state = state
    task.execution_error = getattr(mission, "error", None) or (
        str((mission.result or {}).get("error")) if isinstance(mission.result, dict) and mission.result.get("error") else None
    )
    task.execution_started_at = getattr(mission, "started_at", None)
    task.execution_finished_at = getattr(mission, "finished_at", None)
    if getattr(mission, "run_id", None):
        task.run_id = mission.run_id

    progress = None
    if isinstance(mission.result, dict):
        raw = mission.result.get("progress")
        if isinstance(raw, (int, float)):
            progress = float(raw)
    task.execution_progress = progress

    if state in FAILED_MISSION_STATES:
        task.blocked = True
        task.blocked_reason_code = BlockReasonCode.EXECUTION_FAILED.value
        task.blocked_reason = task.execution_error or "Agent mission failed"
    elif state in DONE_MISSION_STATES:
        if task.blocked_reason_code == BlockReasonCode.EXECUTION_FAILED.value:
            task.blocked = False
            task.blocked_reason = None
            task.blocked_reason_code = None
    return task


def apply_workflow_projection(task: TaskRecord, workflow: _WorkflowLike) -> TaskRecord:
    state = _enum_val(workflow.state)
    task.workflow_id = workflow.workflow_id
    task.execution_state = state
    task.execution_error = workflow.error
    task.execution_phase = f"step:{workflow.current_step}"
    if workflow.run_id:
        task.run_id = workflow.run_id

    steps = getattr(workflow, "steps", None)
    total = len(steps) if steps else 0
    if total > 0:
        task.execution_progress = min(1.0, float(workflow.current_step) / float(total))

    if state in FAILED_WORKFLOW_STATES:
        task.blocked = True
        task.blocked_reason_code = BlockReasonCode.EXECUTION_FAILED.value
        task.blocked_reason = workflow.error or "Workflow failed"
    elif state in DONE_WORKFLOW_STATES:
        if task.blocked_reason_code == BlockReasonCode.EXECUTION_FAILED.value:
            task.blocked = False
            task.blocked_reason = None
            task.blocked_reason_code = None
    return task


def compute_display_progress(task: TaskRecord, *, subtask_completed: int = 0, subtask_total: int = 0) -> float | None:
    """Progress precedence: linked execution → subtasks → manual → unknown."""
    if task.execution_progress is not None:
        return float(task.execution_progress)
    if subtask_total > 0:
        return float(subtask_completed) / float(subtask_total)
    if task.progress is not None:
        return float(task.progress)
    return None
