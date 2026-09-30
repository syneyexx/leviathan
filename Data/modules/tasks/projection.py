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


# Domain labels exposed to the Taken UI. Derived — never a second type authority.
_KNOWN_TASK_TYPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("research", ("research", "onderzoek", "web.research", "web_research")),
    ("trading", ("trading", "trade", "market", "marketsim", "paper")),
    ("data", ("data", "dataset", "ingest", "etl", "parquet", "csv")),
    ("training", ("training", "finetune", "fine-tune", "model.train", "train")),
    ("analysis", ("analysis", "analyse", "analytics", "evaluate_market")),
    ("system", ("system", "maintenance", "host", "backup", "runtime")),
    ("browser", ("browser", "scrape", "playwright", "selenium")),
    ("tool", ("tool", "capability", "function")),
    ("development", ("development", "coding", "code", "dev", "patch")),
    ("evaluation", ("evaluation", "eval", "benchmark", "qa")),
    ("knowledge", ("knowledge", "memory", "brain", "rag", "document")),
)

_RUNNING_EXEC = frozenset({"RUNNING", "running", "starting", "cancelling", "CANCEL_REQUESTED"})
_WAITING_EXEC = frozenset(
    {
        "CREATED",
        "QUEUED",
        "RETRY_WAIT",
        "queued",
        "created",
        "retry_wait",
        "cancel_requested",
    }
)
_FAILED_EXEC = frozenset({"FAILED", "failed", "interrupted"})
_DONE_EXEC = frozenset({"COMPLETED", "completed"})
_CANCELLED_EXEC = frozenset({"CANCELLED", "cancelled"})


def _haystack(task: TaskRecord) -> str:
    parts = [
        " ".join(task.tags or []),
        task.project or "",
        task.capability_id or "",
        task.source_type.value if task.source_type else "",
        task.execution_binding.value if task.execution_binding else "",
        task.title or "",
    ]
    return " ".join(parts).lower()


def derive_task_type(task: TaskRecord) -> str:
    """Classify a task into a UI domain type from existing fields only."""
    for tag in task.tags or []:
        raw = str(tag or "").strip().lower()
        if raw.startswith("type:"):
            value = raw.split(":", 1)[1].strip()
            if value:
                return value
        for type_id, keywords in _KNOWN_TASK_TYPES:
            if raw == type_id or raw in keywords:
                return type_id

    hay = _haystack(task)
    for type_id, keywords in _KNOWN_TASK_TYPES:
        for kw in keywords:
            if kw in hay:
                return type_id

    binding = task.execution_binding.value if task.execution_binding else "manual"
    if binding == "capability_job":
        return "tool"
    if binding == "agent_mission":
        return "system"
    if binding == "workflow":
        return "system"
    if task.schedule_id or (task.source_type and task.source_type.value == "schedule"):
        return "system"
    if task.source_type and task.source_type.value == "cognition":
        return "knowledge"
    return "general"


def derive_operational_status(task: TaskRecord) -> str:
    """Map board + execution into Taken UI status: running|waiting|completed|failed|cancelled."""
    state = (task.execution_state or "").strip()
    if state in _FAILED_EXEC or (
        task.blocked
        and task.blocked_reason_code == BlockReasonCode.EXECUTION_FAILED.value
    ):
        return "failed"
    if state in _CANCELLED_EXEC:
        return "cancelled"
    if state in _DONE_EXEC or task.board_column == BoardColumn.DONE or task.completed_at:
        return "completed"
    if state in _RUNNING_EXEC or task.board_column == BoardColumn.IN_PROGRESS:
        return "running"
    if state in _WAITING_EXEC or task.board_column in {BoardColumn.BACKLOG, BoardColumn.REVIEW} or task.blocked:
        return "waiting"
    return "waiting"


def short_display_id(task_id: str) -> str:
    """Presentation-only short id derived from the canonical UUID (not a second authority)."""
    compact = (task_id or "").replace("-", "")
    if len(compact) >= 4:
        return compact[-4:].upper()
    return (task_id or "?")[:4].upper()
