"""Task planning / coordination domain types (thin control plane).

Board state is separate from execution state. Linked Job/Mission/Workflow
remain authoritative for runtime lifecycle fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class BoardColumn(str, Enum):
    BACKLOG = "backlog"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"


class TaskPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AssigneeType(str, Enum):
    NONE = "none"
    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"


class SourceType(str, Enum):
    MANUAL = "manual"
    JOB = "job"
    WORKFLOW = "workflow"
    AGENT_MISSION = "agent_mission"
    COGNITION = "cognition"
    SCHEDULE = "schedule"
    OTHER = "other"


class ExecutionBinding(str, Enum):
    """How the task starts work when Start is invoked."""

    MANUAL = "manual"
    AGENT_MISSION = "agent_mission"
    CAPABILITY_JOB = "capability_job"
    WORKFLOW = "workflow"


class BlockReasonCode(str, Enum):
    DEPENDENCY = "DEPENDENCY"
    APPROVAL = "APPROVAL"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    RETRY_WAIT = "RETRY_WAIT"
    MISSING_AGENT = "MISSING_AGENT"
    MISSING_CAPABILITY = "MISSING_CAPABILITY"
    DISABLED_AGENT = "DISABLED_AGENT"
    SCHEDULE_PAUSED = "SCHEDULE_PAUSED"
    MANUAL_BLOCK = "MANUAL_BLOCK"
    WORKFLOW_MISSING = "WORKFLOW_MISSING"


class TaskEventType(str, Enum):
    CREATED = "task.created"
    UPDATED = "task.updated"
    ARCHIVED = "task.archived"
    MOVED = "task.moved"
    ASSIGNED = "task.assigned"
    STARTED = "task.started"
    CANCELLED = "task.cancelled"
    RETRIED = "task.retried"
    COMPLETED = "task.completed"
    BLOCKED = "task.blocked"
    UNBLOCKED = "task.unblocked"
    NOTE_ADDED = "task.note_added"
    NOTE_DELETED = "task.note_deleted"
    SUBTASK_CREATED = "task.subtask_created"
    SUBTASK_UPDATED = "task.subtask_updated"
    SUBTASK_DELETED = "task.subtask_deleted"
    DEPENDENCY_ADDED = "task.dependency_added"
    DEPENDENCY_REMOVED = "task.dependency_removed"
    EXECUTION_BOUND = "task.execution_bound"
    EXECUTION_SYNCED = "task.execution_synced"
    AUTO_PLAN_COMMITTED = "task.auto_plan_committed"


class TaskError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 400, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}

    def public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"error": self.code, "code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


@dataclass
class TaskRecord:
    task_id: str
    title: str
    description: str = ""
    board_column: BoardColumn = BoardColumn.BACKLOG
    blocked: bool = False
    blocked_reason: str | None = None
    blocked_reason_code: str | None = None
    priority: TaskPriority = TaskPriority.MEDIUM
    tags: list[str] = field(default_factory=list)
    project: str | None = None
    assignee_type: AssigneeType = AssigneeType.NONE
    assignee_id: str | None = None
    assignee_name: str | None = None
    due_at: str | None = None
    planned_start_at: str | None = None
    completed_at: str | None = None
    progress: float | None = None
    created_at: str = ""
    updated_at: str = ""
    archived_at: str | None = None
    source_type: SourceType = SourceType.MANUAL
    source_ref: str | None = None
    execution_binding: ExecutionBinding = ExecutionBinding.MANUAL
    job_id: str | None = None
    workflow_id: str | None = None
    mission_id: str | None = None
    run_id: str | None = None
    approval_id: str | None = None
    schedule_id: str | None = None
    capability_id: str | None = None
    capability_arguments: dict[str, Any] = field(default_factory=dict)
    mission_request: str | None = None
    execution_state: str | None = None
    execution_error: str | None = None
    execution_phase: str | None = None
    execution_attempt: int | None = None
    execution_progress: float | None = None
    execution_started_at: str | None = None
    execution_finished_at: str | None = None
    board_order: int = 0
    created_by: str = "operator"
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "taskId": self.task_id,
            "title": self.title,
            "description": self.description,
            "boardColumn": self.board_column.value,
            "blocked": self.blocked,
            "blockedReason": self.blocked_reason,
            "blockedReasonCode": self.blocked_reason_code,
            "priority": self.priority.value,
            "tags": list(self.tags),
            "project": self.project,
            "assigneeType": self.assignee_type.value,
            "assigneeId": self.assignee_id,
            "assigneeName": self.assignee_name,
            "dueAt": self.due_at,
            "plannedStartAt": self.planned_start_at,
            "completedAt": self.completed_at,
            "progress": self.progress,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "archivedAt": self.archived_at,
            "sourceType": self.source_type.value,
            "sourceRef": self.source_ref,
            "executionBinding": self.execution_binding.value,
            "jobId": self.job_id,
            "workflowId": self.workflow_id,
            "missionId": self.mission_id,
            "runId": self.run_id,
            "approvalId": self.approval_id,
            "scheduleId": self.schedule_id,
            "capabilityId": self.capability_id,
            "capabilityArguments": dict(self.capability_arguments),
            "missionRequest": self.mission_request,
            "executionState": self.execution_state,
            "executionError": self.execution_error,
            "executionPhase": self.execution_phase,
            "executionAttempt": self.execution_attempt,
            "executionProgress": self.execution_progress,
            "executionStartedAt": self.execution_started_at,
            "executionFinishedAt": self.execution_finished_at,
            "boardOrder": self.board_order,
            "createdBy": self.created_by,
            "metadata": dict(self.metadata),
        }


@dataclass
class TaskSubtask:
    subtask_id: str
    task_id: str
    title: str
    completed: bool = False
    completed_at: str | None = None
    sort_order: int = 0
    created_at: str = ""
    updated_at: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "subtaskId": self.subtask_id,
            "taskId": self.task_id,
            "title": self.title,
            "completed": self.completed,
            "completedAt": self.completed_at,
            "sortOrder": self.sort_order,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass
class TaskNote:
    note_id: str
    task_id: str
    body: str
    author_type: str = "operator"
    author_id: str | None = None
    author_name: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "noteId": self.note_id,
            "taskId": self.task_id,
            "body": self.body,
            "authorType": self.author_type,
            "authorId": self.author_id,
            "authorName": self.author_name,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass
class TaskDependency:
    dependency_id: str
    task_id: str
    depends_on_task_id: str
    soft: bool = False
    created_at: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "dependencyId": self.dependency_id,
            "taskId": self.task_id,
            "dependsOnTaskId": self.depends_on_task_id,
            "soft": self.soft,
            "createdAt": self.created_at,
        }


@dataclass
class TaskEvent:
    event_id: str
    task_id: str
    event_type: str
    actor_type: str = "system"
    actor_id: str | None = None
    source_type: str | None = None
    source_ref: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "eventId": self.event_id,
            "taskId": self.task_id,
            "eventType": self.event_type,
            "actorType": self.actor_type,
            "actorId": self.actor_id,
            "sourceType": self.source_type,
            "sourceRef": self.source_ref,
            "payload": dict(self.payload),
            "createdAt": self.created_at,
        }


@dataclass
class TaskSummary:
    active: int = 0
    in_progress: int = 0
    blocked: int = 0
    completed_today: int = 0
    overdue: int = 0
    agents_assigned: int = 0
    completed_previous_period: int | None = None
    column_counts: dict[str, int] = field(default_factory=dict)
    timezone: str = "UTC"

    def public_dict(self) -> dict[str, Any]:
        delta: str | None = None
        if self.completed_previous_period is not None and self.completed_previous_period > 0:
            change = ((self.completed_today - self.completed_previous_period) / self.completed_previous_period) * 100
            sign = "↑" if change >= 0 else "↓"
            delta = f"{sign} {change:+.0f}%"
        elif self.completed_today > 0 and self.completed_previous_period == 0:
            delta = "↑ new"
        return {
            "active": self.active,
            "inProgress": self.in_progress,
            "blocked": self.blocked,
            "completedToday": self.completed_today,
            "overdue": self.overdue,
            "agentsAssigned": self.agents_assigned,
            "completedPreviousPeriod": self.completed_previous_period,
            "completedTodayDelta": delta,
            "columnCounts": dict(self.column_counts),
            "timezone": self.timezone,
        }


@dataclass
class TaskWorkloadEntry:
    assignee_id: str | None
    assignee_name: str
    assignee_type: str
    active_count: int = 0
    in_progress_count: int = 0
    blocked_count: int = 0
    overdue_count: int = 0
    max_concurrency: int | None = None

    def public_dict(self) -> dict[str, Any]:
        capacity_pct: float | None = None
        if self.max_concurrency and self.max_concurrency > 0:
            capacity_pct = round(min(100.0, (self.in_progress_count / self.max_concurrency) * 100), 1)
        return {
            "assigneeId": self.assignee_id,
            "assigneeName": self.assignee_name,
            "assigneeType": self.assignee_type,
            "activeCount": self.active_count,
            "inProgressCount": self.in_progress_count,
            "blockedCount": self.blocked_count,
            "overdueCount": self.overdue_count,
            "maxConcurrency": self.max_concurrency,
            "capacityPct": capacity_pct,
        }


@dataclass
class TaskTimelineItem:
    task_id: str
    title: str
    board_column: str
    start_at: str | None
    end_at: str | None
    kind: str  # planned | due | execution
    execution_state: str | None = None
    blocked: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "taskId": self.task_id,
            "title": self.title,
            "boardColumn": self.board_column,
            "startAt": self.start_at,
            "endAt": self.end_at,
            "kind": self.kind,
            "executionState": self.execution_state,
            "blocked": self.blocked,
        }


@dataclass
class TaskAutoPlanProposal:
    title: str
    description: str = ""
    priority: str = "medium"
    suggested_assignee_id: str | None = None
    tags: list[str] = field(default_factory=list)
    due_at: str | None = None
    dependencies: list[int] = field(default_factory=list)  # indices into proposals list

    def public_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "suggestedAssigneeId": self.suggested_assignee_id,
            "tags": list(self.tags),
            "dueAt": self.due_at,
            "dependencies": list(self.dependencies),
        }
