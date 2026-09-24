"""TaskService — planning/coordination layer over existing LEVIATHAN runtimes."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .planner import TaskPlannerAdapter
from .projection import (
    apply_job_projection,
    apply_mission_projection,
    apply_workflow_projection,
    compute_display_progress,
)
from .store import TaskStore, utc_now
from .types import (
    AssigneeType,
    BlockReasonCode,
    BoardColumn,
    ExecutionBinding,
    SourceType,
    TaskAutoPlanProposal,
    TaskDependency,
    TaskError,
    TaskEventType,
    TaskNote,
    TaskPriority,
    TaskRecord,
    TaskSubtask,
    TaskSummary,
    TaskTimelineItem,
    TaskWorkloadEntry,
)


def _parse_enum(enum_cls: type, value: str | None, *, field_name: str) -> Any:
    if value is None:
        return None
    try:
        return enum_cls(str(value).strip().lower())
    except ValueError as exc:
        raise TaskError("INVALID_VALUE", f"Invalid {field_name}: {value}", http_status=422) from exc


def _zone(name: str | None) -> ZoneInfo:
    tz_name = (name or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise TaskError("INVALID_TIMEZONE", f"Unknown timezone: {tz_name}", http_status=422) from exc


def _day_bounds(tz: ZoneInfo, *, day: datetime | None = None) -> tuple[str, str]:
    local = (day or datetime.now(timezone.utc)).astimezone(tz)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return (
        start.astimezone(timezone.utc).isoformat(timespec="seconds"),
        end.astimezone(timezone.utc).isoformat(timespec="seconds"),
    )


class TaskService:
    """Thin control plane: persists planning metadata; delegates execution."""

    def __init__(
        self,
        store: TaskStore,
        *,
        job_runtime: Any | None = None,
        workflow_runtime: Any | None = None,
        agent_fleet: Any | None = None,
        approval_service: Any | None = None,
        schedule_store: Any | None = None,
        execution_gateway: Any | None = None,
        model_caller: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.store = store
        self.job_runtime = job_runtime
        self.workflow_runtime = workflow_runtime
        self.agent_fleet = agent_fleet
        self.approval_service = approval_service
        self.schedule_store = schedule_store
        self.execution_gateway = execution_gateway
        self.planner = TaskPlannerAdapter(model_caller)

    def initialize(self) -> None:
        self.store.initialize()

    # ── CRUD ────────────────────────────────────────────────────────────────

    def create(
        self,
        *,
        title: str,
        description: str = "",
        priority: str = "medium",
        board_column: str = "backlog",
        tags: list[str] | None = None,
        project: str | None = None,
        assignee_type: str = "none",
        assignee_id: str | None = None,
        assignee_name: str | None = None,
        due_at: str | None = None,
        planned_start_at: str | None = None,
        progress: float | None = None,
        execution_binding: str = "manual",
        capability_id: str | None = None,
        capability_arguments: dict[str, Any] | None = None,
        mission_request: str | None = None,
        workflow_id: str | None = None,
        schedule_id: str | None = None,
        source_type: str = "manual",
        source_ref: str | None = None,
        created_by: str = "operator",
        metadata: dict[str, Any] | None = None,
        actor_type: str = "operator",
        actor_id: str | None = None,
    ) -> TaskRecord:
        title = (title or "").strip()
        if not title:
            raise TaskError("INVALID_TITLE", "Title is required", http_status=422)
        if len(title) > 300:
            raise TaskError("INVALID_TITLE", "Title must be at most 300 characters", http_status=422)

        col = _parse_enum(BoardColumn, board_column, field_name="board_column") or BoardColumn.BACKLOG
        pri = _parse_enum(TaskPriority, priority, field_name="priority") or TaskPriority.MEDIUM
        a_type = _parse_enum(AssigneeType, assignee_type, field_name="assignee_type") or AssigneeType.NONE
        binding = (
            _parse_enum(ExecutionBinding, execution_binding, field_name="execution_binding")
            or ExecutionBinding.MANUAL
        )
        src = _parse_enum(SourceType, source_type, field_name="source_type") or SourceType.MANUAL

        if source_ref:
            existing = self.store.get_by_source(src.value, source_ref)
            if existing is not None:
                return existing

        resolved_name = assignee_name
        if a_type == AssigneeType.AGENT and assignee_id:
            self._assert_agent_usable(assignee_id)
            if not resolved_name and self.agent_fleet is not None:
                agent = self.agent_fleet.store.get_definition(assignee_id)
                if agent is not None:
                    resolved_name = agent.name

        if binding == ExecutionBinding.CAPABILITY_JOB:
            if not capability_id:
                raise TaskError("MISSING_CAPABILITY", "capability_id is required for job tasks", http_status=422)
            self._assert_capability_exists(capability_id)
        if binding == ExecutionBinding.AGENT_MISSION:
            if not assignee_id or a_type != AssigneeType.AGENT:
                raise TaskError(
                    "MISSING_AGENT",
                    "Agent mission tasks require an agent assignee",
                    http_status=422,
                )
            if not (mission_request or "").strip():
                raise TaskError(
                    "MISSING_MISSION_REQUEST",
                    "mission_request is required for agent mission tasks",
                    http_status=422,
                )
        if binding == ExecutionBinding.WORKFLOW:
            if not workflow_id:
                raise TaskError("MISSING_WORKFLOW", "workflow_id is required for workflow tasks", http_status=422)
            self._assert_workflow_exists(workflow_id)

        now = utc_now()
        record = TaskRecord(
            task_id=str(uuid.uuid4()),
            title=title,
            description=(description or "").strip(),
            board_column=col,
            priority=pri,
            tags=[str(t).strip() for t in (tags or []) if str(t).strip()],
            project=(project or "").strip() or None,
            assignee_type=a_type,
            assignee_id=assignee_id,
            assignee_name=resolved_name,
            due_at=due_at,
            planned_start_at=planned_start_at,
            progress=progress,
            created_at=now,
            updated_at=now,
            source_type=src,
            source_ref=source_ref,
            execution_binding=binding,
            capability_id=capability_id,
            capability_arguments=dict(capability_arguments or {}),
            mission_request=(mission_request or "").strip() or None,
            workflow_id=workflow_id,
            schedule_id=schedule_id,
            board_order=self.store.next_board_order(col.value),
            created_by=created_by,
            metadata=dict(metadata or {}),
        )
        if col == BoardColumn.DONE:
            record.completed_at = now

        self.store.create_task(record)
        self.store.append_event(
            task_id=record.task_id,
            event_type=TaskEventType.CREATED.value,
            actor_type=actor_type,
            actor_id=actor_id,
            payload={"title": record.title, "boardColumn": record.board_column.value},
        )
        return self.recompute_blocking(record.task_id)

    def get(self, task_id: str, *, sync: bool = True) -> TaskRecord:
        record = self.store.get_task(task_id)
        if record is None:
            raise TaskError("NOT_FOUND", f"Task not found: {task_id}", http_status=404)
        if sync:
            record = self.sync_execution(record.task_id)
            record = self.recompute_blocking(record.task_id)
        return record

    def list(
        self,
        *,
        search: str | None = None,
        board_column: str | None = None,
        execution_state: str | None = None,
        priority: str | None = None,
        assignee: str | None = None,
        blocked: bool | None = None,
        overdue: bool | None = None,
        due_from: str | None = None,
        due_to: str | None = None,
        project: str | None = None,
        archived: bool = False,
        date_preset: str | None = None,
        timezone_name: str | None = None,
        limit: int = 200,
        offset: int = 0,
        sync: bool = True,
    ) -> list[TaskRecord]:
        if date_preset:
            due_from, due_to = self._date_preset_bounds(date_preset, timezone_name)
        if board_column:
            _parse_enum(BoardColumn, board_column, field_name="board_column")
        if priority:
            _parse_enum(TaskPriority, priority, field_name="priority")

        tasks = self.store.list_tasks(
            search=search,
            board_column=board_column,
            execution_state=execution_state,
            priority=priority,
            assignee=assignee,
            blocked=blocked,
            overdue=overdue,
            due_from=due_from,
            due_to=due_to,
            project=project,
            archived=archived,
            limit=limit,
            offset=offset,
        )
        if sync:
            synced: list[TaskRecord] = []
            for t in tasks:
                try:
                    synced.append(self.sync_execution(t.task_id))
                except TaskError:
                    synced.append(t)
            tasks = [self.recompute_blocking(t.task_id) for t in synced]
        return tasks

    def update(
        self,
        task_id: str,
        *,
        patch: dict[str, Any],
        actor_type: str = "operator",
        actor_id: str | None = None,
    ) -> TaskRecord:
        record = self.get(task_id, sync=False)
        if record.archived_at:
            raise TaskError("ARCHIVED", "Cannot update an archived task", http_status=409)

        changes: dict[str, Any] = {}
        if "title" in patch and patch["title"] is not None:
            title = str(patch["title"]).strip()
            if not title:
                raise TaskError("INVALID_TITLE", "Title is required", http_status=422)
            if title != record.title:
                changes["title"] = {"from": record.title, "to": title}
                record.title = title
        if "description" in patch and patch["description"] is not None:
            desc = str(patch["description"])
            if desc != record.description:
                changes["description"] = True
                record.description = desc
        if "priority" in patch and patch["priority"] is not None:
            pri = _parse_enum(TaskPriority, str(patch["priority"]), field_name="priority")
            if pri != record.priority:
                changes["priority"] = {"from": record.priority.value, "to": pri.value}
                record.priority = pri
        if "boardColumn" in patch or "board_column" in patch:
            raw = patch.get("boardColumn", patch.get("board_column"))
            if raw is not None:
                col = _parse_enum(BoardColumn, str(raw), field_name="board_column")
                if col != record.board_column:
                    changes["boardColumn"] = {"from": record.board_column.value, "to": col.value}
                    record.board_column = col
                    if col == BoardColumn.DONE and not record.completed_at:
                        record.completed_at = utc_now()
                    if col != BoardColumn.DONE:
                        record.completed_at = None
        if "tags" in patch and patch["tags"] is not None:
            tags = [str(t).strip() for t in list(patch["tags"]) if str(t).strip()]
            if tags != record.tags:
                changes["tags"] = tags
                record.tags = tags
        if "project" in patch:
            project = (str(patch["project"]).strip() if patch["project"] is not None else None) or None
            if project != record.project:
                changes["project"] = project
                record.project = project
        if "dueAt" in patch or "due_at" in patch:
            due = patch.get("dueAt", patch.get("due_at"))
            due_s = str(due) if due not in (None, "") else None
            if due_s != record.due_at:
                changes["dueAt"] = due_s
                record.due_at = due_s
        if "plannedStartAt" in patch or "planned_start_at" in patch:
            ps = patch.get("plannedStartAt", patch.get("planned_start_at"))
            ps_s = str(ps) if ps not in (None, "") else None
            if ps_s != record.planned_start_at:
                changes["plannedStartAt"] = ps_s
                record.planned_start_at = ps_s
        if "progress" in patch and patch["progress"] is not None:
            try:
                progress = float(patch["progress"])
            except (TypeError, ValueError) as exc:
                raise TaskError("INVALID_PROGRESS", "progress must be a number", http_status=422) from exc
            if progress < 0 or progress > 1:
                raise TaskError("INVALID_PROGRESS", "progress must be between 0 and 1", http_status=422)
            if record.execution_binding != ExecutionBinding.MANUAL and record.job_id:
                raise TaskError(
                    "PROGRESS_LOCKED",
                    "Progress is owned by linked execution for non-manual tasks",
                    http_status=409,
                )
            changes["progress"] = progress
            record.progress = progress
        if any(k in patch for k in ("assigneeType", "assignee_type", "assigneeId", "assignee_id", "assigneeName", "assignee_name")):
            a_type_raw = patch.get("assigneeType", patch.get("assignee_type", record.assignee_type.value))
            a_type = _parse_enum(AssigneeType, str(a_type_raw), field_name="assignee_type")
            a_id = patch.get("assigneeId", patch.get("assignee_id", record.assignee_id))
            a_name = patch.get("assigneeName", patch.get("assignee_name", record.assignee_name))
            if a_id in ("", None):
                a_id = None
            else:
                a_id = str(a_id)
            if a_name in ("", None):
                a_name = None
            else:
                a_name = str(a_name)
            if a_type == AssigneeType.AGENT and a_id:
                self._assert_agent_usable(a_id)
                if not a_name and self.agent_fleet is not None:
                    agent = self.agent_fleet.store.get_definition(a_id)
                    if agent is not None:
                        a_name = agent.name
            if a_type == AssigneeType.NONE:
                a_id = None
                a_name = None
            if (a_type, a_id, a_name) != (record.assignee_type, record.assignee_id, record.assignee_name):
                changes["assignee"] = {"type": a_type.value, "id": a_id, "name": a_name}
                record.assignee_type = a_type
                record.assignee_id = a_id
                record.assignee_name = a_name
        if "manualBlock" in patch or "blocked" in patch:
            # Explicit manual block only when no other reason codes apply later.
            blocked = bool(patch.get("manualBlock", patch.get("blocked")))
            if blocked:
                record.blocked = True
                record.blocked_reason_code = BlockReasonCode.MANUAL_BLOCK.value
                record.blocked_reason = str(patch.get("blockedReason") or patch.get("blocked_reason") or "Manually blocked")
                changes["manualBlock"] = True
            elif record.blocked_reason_code == BlockReasonCode.MANUAL_BLOCK.value:
                record.blocked = False
                record.blocked_reason = None
                record.blocked_reason_code = None
                changes["manualBlock"] = False

        if not changes:
            return self.recompute_blocking(record.task_id)

        self.store.update_task(record)
        event_type = TaskEventType.MOVED.value if "boardColumn" in changes else TaskEventType.UPDATED.value
        if "assignee" in changes and len(changes) == 1:
            event_type = TaskEventType.ASSIGNED.value
        self.store.append_event(
            task_id=record.task_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            payload=changes,
        )
        return self.recompute_blocking(record.task_id)

    def archive(self, task_id: str, *, actor_type: str = "operator", actor_id: str | None = None) -> TaskRecord:
        record = self.get(task_id, sync=False)
        if record.archived_at:
            return record
        record.archived_at = utc_now()
        self.store.update_task(record)
        self.store.append_event(
            task_id=record.task_id,
            event_type=TaskEventType.ARCHIVED.value,
            actor_type=actor_type,
            actor_id=actor_id,
        )
        return record

    def duplicate_as_manual(self, task_id: str, *, actor_type: str = "operator", actor_id: str | None = None) -> TaskRecord:
        src = self.get(task_id, sync=False)
        return self.create(
            title=f"{src.title} (copy)",
            description=src.description,
            priority=src.priority.value,
            board_column=BoardColumn.BACKLOG.value,
            tags=list(src.tags),
            project=src.project,
            assignee_type=AssigneeType.NONE.value,
            execution_binding=ExecutionBinding.MANUAL.value,
            created_by=src.created_by,
            metadata={"duplicatedFrom": src.task_id},
            actor_type=actor_type,
            actor_id=actor_id,
        )

    # ── Execution actions ───────────────────────────────────────────────────

    def start(self, task_id: str, *, actor_type: str = "operator", actor_id: str | None = None) -> TaskRecord:
        record = self.get(task_id, sync=True)
        if record.archived_at:
            raise TaskError("ARCHIVED", "Cannot start an archived task", http_status=409)
        record = self.recompute_blocking(task_id)
        if record.blocked and record.blocked_reason_code in {
            BlockReasonCode.DEPENDENCY.value,
            BlockReasonCode.APPROVAL.value,
            BlockReasonCode.MISSING_AGENT.value,
            BlockReasonCode.DISABLED_AGENT.value,
            BlockReasonCode.MISSING_CAPABILITY.value,
            BlockReasonCode.WORKFLOW_MISSING.value,
            BlockReasonCode.MANUAL_BLOCK.value,
        }:
            raise TaskError(
                "TASK_BLOCKED",
                record.blocked_reason or "Task is blocked",
                http_status=409,
                details={"reasonCode": record.blocked_reason_code},
            )

        binding = record.execution_binding
        if binding == ExecutionBinding.MANUAL:
            if record.board_column == BoardColumn.BACKLOG:
                record.board_column = BoardColumn.IN_PROGRESS
            self.store.update_task(record)
            self.store.append_event(
                task_id=record.task_id,
                event_type=TaskEventType.STARTED.value,
                actor_type=actor_type,
                actor_id=actor_id,
                payload={"binding": "manual"},
            )
            return self.recompute_blocking(record.task_id)

        # Idempotent: already has active execution
        if record.job_id and binding == ExecutionBinding.CAPABILITY_JOB:
            job = self.job_runtime.get(record.job_id) if self.job_runtime else None
            if job is not None and _enum_val(job.state) in {"CREATED", "QUEUED", "RUNNING", "RETRY_WAIT", "CANCEL_REQUESTED"}:
                return self.sync_execution(record.task_id)
        if record.mission_id and binding == ExecutionBinding.AGENT_MISSION:
            if self.agent_fleet is not None:
                mission = self.agent_fleet.store.get_mission(record.mission_id)
                if mission is not None and _enum_val(mission.status) in {"queued", "starting", "running", "cancelling"}:
                    return self.sync_execution(record.task_id)
        if record.workflow_id and binding == ExecutionBinding.WORKFLOW:
            if self.workflow_runtime is not None:
                wf = self.workflow_runtime.store.get(record.workflow_id) if hasattr(self.workflow_runtime, "store") else None
                if wf is None and hasattr(self.workflow_runtime, "get"):
                    wf = self.workflow_runtime.get(record.workflow_id)
                if wf is not None and _enum_val(wf.state) in {"CREATED", "RUNNING"}:
                    return self.sync_execution(record.task_id)

        if binding == ExecutionBinding.CAPABILITY_JOB:
            if self.job_runtime is None:
                raise TaskError("JOB_RUNTIME_UNAVAILABLE", "JobRuntime is not configured", http_status=503)
            self._assert_capability_exists(record.capability_id or "")
            job = self.job_runtime.enqueue(
                capability_id=record.capability_id,
                arguments=dict(record.capability_arguments),
                requested_by=record.created_by or "tasks",
                idempotency_key=f"task:start:{record.task_id}",
                domain="tasks",
                domain_entity_type="task",
                domain_entity_id=record.task_id,
                metadata={"task_id": record.task_id},
            )
            record.job_id = job.job_id
            record.source_type = SourceType.JOB
            record.source_ref = job.job_id
            apply_job_projection(record, job)
            if record.board_column == BoardColumn.BACKLOG:
                record.board_column = BoardColumn.IN_PROGRESS
            self.store.update_task(record)
            self.store.append_event(
                task_id=record.task_id,
                event_type=TaskEventType.STARTED.value,
                actor_type=actor_type,
                actor_id=actor_id,
                source_type="job",
                source_ref=job.job_id,
                payload={"jobId": job.job_id},
            )
            return self.recompute_blocking(record.task_id)

        if binding == ExecutionBinding.AGENT_MISSION:
            if self.agent_fleet is None:
                raise TaskError("AGENT_FLEET_UNAVAILABLE", "AgentFleet is not configured", http_status=503)
            if not record.assignee_id:
                raise TaskError("MISSING_AGENT", "No agent assigned", http_status=422)
            self._assert_agent_usable(record.assignee_id)
            # Idempotency via metadata on mission is not native — use in-flight mission_id check above.
            mission = self.agent_fleet.launch_mission(
                agent_id=record.assignee_id,
                request=record.mission_request or record.title,
                title=record.title,
                priority={"high": "high", "medium": "med", "low": "low"}.get(record.priority.value, "med"),
                use_jobs=True,
            )
            record.mission_id = mission.mission_id
            record.source_type = SourceType.AGENT_MISSION
            record.source_ref = mission.mission_id
            apply_mission_projection(record, mission)
            if record.board_column == BoardColumn.BACKLOG:
                record.board_column = BoardColumn.IN_PROGRESS
            self.store.update_task(record)
            self.store.append_event(
                task_id=record.task_id,
                event_type=TaskEventType.STARTED.value,
                actor_type=actor_type,
                actor_id=actor_id,
                source_type="agent_mission",
                source_ref=mission.mission_id,
                payload={"missionId": mission.mission_id},
            )
            return self.recompute_blocking(record.task_id)

        if binding == ExecutionBinding.WORKFLOW:
            if self.workflow_runtime is None:
                raise TaskError("WORKFLOW_RUNTIME_UNAVAILABLE", "WorkflowRuntime is not configured", http_status=503)
            wf_id = record.workflow_id
            if not wf_id:
                raise TaskError("MISSING_WORKFLOW", "No workflow bound", http_status=422)
            # Prefer durable enqueue_advance when available
            if hasattr(self.workflow_runtime, "enqueue_advance"):
                self.workflow_runtime.enqueue_advance(wf_id)
            else:
                self.workflow_runtime.run(wf_id)
            wf = None
            if hasattr(self.workflow_runtime, "store"):
                wf = self.workflow_runtime.store.get(wf_id)
            if wf is not None:
                apply_workflow_projection(record, wf)
            if record.board_column == BoardColumn.BACKLOG:
                record.board_column = BoardColumn.IN_PROGRESS
            self.store.update_task(record)
            self.store.append_event(
                task_id=record.task_id,
                event_type=TaskEventType.STARTED.value,
                actor_type=actor_type,
                actor_id=actor_id,
                source_type="workflow",
                source_ref=wf_id,
                payload={"workflowId": wf_id},
            )
            return self.recompute_blocking(record.task_id)

        raise TaskError("UNSUPPORTED_BINDING", f"Unsupported execution binding: {binding}", http_status=422)

    def cancel(self, task_id: str, *, actor_type: str = "operator", actor_id: str | None = None) -> TaskRecord:
        record = self.get(task_id, sync=True)
        if record.archived_at:
            raise TaskError("ARCHIVED", "Cannot cancel an archived task", http_status=409)

        if record.execution_binding == ExecutionBinding.MANUAL:
            raise TaskError("NOT_CANCELLABLE", "Manual tasks have no running execution to cancel", http_status=409)

        if record.job_id and self.job_runtime is not None:
            job = self.job_runtime.get(record.job_id)
            if job is None:
                raise TaskError("JOB_NOT_FOUND", f"Linked job not found: {record.job_id}", http_status=404)
            state = _enum_val(job.state)
            if state in {"COMPLETED", "FAILED", "CANCELLED"}:
                raise TaskError("NOT_CANCELLABLE", f"Job is already {state}", http_status=409)
            job = self.job_runtime.cancel(record.job_id, reason="Cancelled from Tasks")
            apply_job_projection(record, job)
        elif record.mission_id and self.agent_fleet is not None:
            mission = self.agent_fleet.cancel_mission(record.mission_id)
            apply_mission_projection(record, mission)
        elif record.workflow_id and self.workflow_runtime is not None:
            wf = self.workflow_runtime.cancel(record.workflow_id)
            apply_workflow_projection(record, wf)
        else:
            raise TaskError("NOT_CANCELLABLE", "No cancellable execution is linked", http_status=409)

        self.store.update_task(record)
        self.store.append_event(
            task_id=record.task_id,
            event_type=TaskEventType.CANCELLED.value,
            actor_type=actor_type,
            actor_id=actor_id,
        )
        return self.recompute_blocking(record.task_id)

    def retry(self, task_id: str, *, actor_type: str = "operator", actor_id: str | None = None) -> TaskRecord:
        record = self.get(task_id, sync=True)
        if record.archived_at:
            raise TaskError("ARCHIVED", "Cannot retry an archived task", http_status=409)

        if record.job_id and self.job_runtime is not None:
            job = self.job_runtime.get(record.job_id)
            if job is None:
                raise TaskError("JOB_NOT_FOUND", f"Linked job not found: {record.job_id}", http_status=404)
            state = _enum_val(job.state)
            if state not in {"FAILED", "CANCELLED"}:
                raise TaskError("NOT_RETRIABLE", f"Job state {state} cannot be retried", http_status=409)
            # FAILED/CANCELLED are terminal in JobState — re-enqueue a fresh job rather than
            # illegal FAILED → RETRY_WAIT. Keep the Tasks binding authoritative.
            if not record.capability_id:
                raise TaskError("MISSING_CAPABILITY", "Cannot retry without capability_id", http_status=422)
            attempt = int(record.execution_attempt or job.attempt_number or 1) + 1
            new_job = self.job_runtime.enqueue(
                capability_id=record.capability_id,
                arguments=dict(record.capability_arguments),
                requested_by=record.created_by or "tasks",
                idempotency_key=f"task:retry:{record.task_id}:{attempt}",
                domain="tasks",
                domain_entity_type="task",
                domain_entity_id=record.task_id,
                metadata={"task_id": record.task_id, "retry_of": record.job_id, "attempt": attempt},
            )
            record.job_id = new_job.job_id
            record.source_ref = new_job.job_id
            record.execution_attempt = attempt
            record.blocked = False
            record.blocked_reason = None
            record.blocked_reason_code = None
            apply_job_projection(record, new_job)
            self.store.update_task(record)
            self.store.append_event(
                task_id=record.task_id,
                event_type=TaskEventType.RETRIED.value,
                actor_type=actor_type,
                actor_id=actor_id,
                source_type="job",
                source_ref=new_job.job_id,
                payload={"jobId": new_job.job_id, "retryOf": job.job_id, "attempt": attempt},
            )
            return self.recompute_blocking(record.task_id)

        if record.execution_binding == ExecutionBinding.AGENT_MISSION:
            # Clear prior mission and re-launch
            record.mission_id = None
            record.execution_state = None
            record.execution_error = None
            self.store.update_task(record)
            return self.start(record.task_id, actor_type=actor_type, actor_id=actor_id)

        raise TaskError("NOT_RETRIABLE", "No retriable execution is linked", http_status=409)

    # ── Sync / blocking ─────────────────────────────────────────────────────

    def sync_execution(self, task_id: str) -> TaskRecord:
        record = self.store.get_task(task_id)
        if record is None:
            raise TaskError("NOT_FOUND", f"Task not found: {task_id}", http_status=404)
        changed = False
        if record.job_id and self.job_runtime is not None:
            job = self.job_runtime.get(record.job_id)
            if job is not None:
                before = (record.execution_state, record.execution_progress, record.execution_error)
                apply_job_projection(record, job)
                after = (record.execution_state, record.execution_progress, record.execution_error)
                if before != after:
                    changed = True
        if record.mission_id and self.agent_fleet is not None:
            mission = self.agent_fleet.store.get_mission(record.mission_id)
            if mission is not None:
                before = (record.execution_state, record.execution_progress, record.execution_error)
                apply_mission_projection(record, mission)
                after = (record.execution_state, record.execution_progress, record.execution_error)
                if before != after:
                    changed = True
        if record.workflow_id and self.workflow_runtime is not None:
            wf = None
            if hasattr(self.workflow_runtime, "store"):
                wf = self.workflow_runtime.store.get(record.workflow_id)
            if wf is not None:
                before = (record.execution_state, record.execution_progress, record.execution_error)
                apply_workflow_projection(record, wf)
                after = (record.execution_state, record.execution_progress, record.execution_error)
                if before != after:
                    changed = True
        if changed:
            self.store.update_task(record)
        return record

    def recompute_blocking(self, task_id: str) -> TaskRecord:
        record = self.store.get_task(task_id)
        if record is None:
            raise TaskError("NOT_FOUND", f"Task not found: {task_id}", http_status=404)

        # Preserve execution-derived blocks first
        if record.execution_state in {"FAILED", "failed", "interrupted"}:
            record.blocked = True
            record.blocked_reason_code = BlockReasonCode.EXECUTION_FAILED.value
            record.blocked_reason = record.execution_error or "Execution failed"
            self.store.update_task(record)
            return record
        if record.execution_state == "RETRY_WAIT":
            record.blocked = True
            record.blocked_reason_code = BlockReasonCode.RETRY_WAIT.value
            record.blocked_reason = "Waiting to retry"
            self.store.update_task(record)
            return record

        # Approval pending
        if record.approval_id and self.approval_service is not None:
            approval = self.approval_service.store.get(record.approval_id) if hasattr(self.approval_service, "store") else None
            if approval is not None:
                status = _enum_val(approval.status)
                if status == "PENDING":
                    record.blocked = True
                    record.blocked_reason_code = BlockReasonCode.APPROVAL.value
                    record.blocked_reason = "Approval required"
                    self.store.update_task(record)
                    return record
                if status == "DENIED":
                    record.blocked = True
                    record.blocked_reason_code = BlockReasonCode.APPROVAL.value
                    record.blocked_reason = "Approval denied"
                    self.store.update_task(record)
                    return record

        # Agent usability
        if record.assignee_type == AssigneeType.AGENT and record.assignee_id and self.agent_fleet is not None:
            agent = self.agent_fleet.store.get_definition(record.assignee_id)
            if agent is None:
                record.blocked = True
                record.blocked_reason_code = BlockReasonCode.MISSING_AGENT.value
                record.blocked_reason = f"Assigned agent missing: {record.assignee_id}"
                self.store.update_task(record)
                return record
            if getattr(agent, "archived", False):
                record.blocked = True
                record.blocked_reason_code = BlockReasonCode.MISSING_AGENT.value
                record.blocked_reason = "Assigned agent is archived"
                self.store.update_task(record)
                return record
            if not getattr(agent, "enabled", True):
                record.blocked = True
                record.blocked_reason_code = BlockReasonCode.DISABLED_AGENT.value
                record.blocked_reason = "Assigned agent is disabled"
                self.store.update_task(record)
                return record

        # Capability / workflow presence for unbound-but-configured tasks
        if record.execution_binding == ExecutionBinding.CAPABILITY_JOB and record.capability_id:
            try:
                self._assert_capability_exists(record.capability_id)
            except TaskError as exc:
                if exc.code == "MISSING_CAPABILITY":
                    record.blocked = True
                    record.blocked_reason_code = BlockReasonCode.MISSING_CAPABILITY.value
                    record.blocked_reason = exc.message
                    self.store.update_task(record)
                    return record
        if record.execution_binding == ExecutionBinding.WORKFLOW and record.workflow_id:
            try:
                self._assert_workflow_exists(record.workflow_id)
            except TaskError as exc:
                if exc.code == "MISSING_WORKFLOW":
                    record.blocked = True
                    record.blocked_reason_code = BlockReasonCode.WORKFLOW_MISSING.value
                    record.blocked_reason = exc.message
                    self.store.update_task(record)
                    return record

        # Hard dependencies
        blockers = self._unresolved_hard_dependencies(record.task_id)
        if blockers:
            titles = ", ".join(b.title for b in blockers[:3])
            record.blocked = True
            record.blocked_reason_code = BlockReasonCode.DEPENDENCY.value
            record.blocked_reason = f"Blocked by: {titles}"
            self.store.update_task(record)
            return record

        # Clear auto blocks except explicit manual
        if record.blocked_reason_code != BlockReasonCode.MANUAL_BLOCK.value:
            if record.blocked or record.blocked_reason_code:
                record.blocked = False
                record.blocked_reason = None
                record.blocked_reason_code = None
                self.store.update_task(record)
        else:
            self.store.update_task(record)
        return record

    def _unresolved_hard_dependencies(self, task_id: str) -> list[TaskRecord]:
        deps = self.store.list_dependencies(task_id)
        blockers: list[TaskRecord] = []
        for dep in deps:
            if dep.soft:
                continue
            other = self.store.get_task(dep.depends_on_task_id)
            if other is None:
                continue
            if other.archived_at:
                continue
            if other.board_column == BoardColumn.DONE or other.completed_at:
                continue
            blockers.append(other)
        return blockers

    # ── Subtasks / notes / deps ─────────────────────────────────────────────

    def list_subtasks(self, task_id: str) -> list[TaskSubtask]:
        self.get(task_id, sync=False)
        return self.store.list_subtasks(task_id)

    def create_subtask(
        self,
        task_id: str,
        *,
        title: str,
        actor_type: str = "operator",
        actor_id: str | None = None,
    ) -> TaskSubtask:
        self.get(task_id, sync=False)
        title = (title or "").strip()
        if not title:
            raise TaskError("INVALID_TITLE", "Subtask title is required", http_status=422)
        existing = self.store.list_subtasks(task_id)
        now = utc_now()
        sub = TaskSubtask(
            subtask_id=str(uuid.uuid4()),
            task_id=task_id,
            title=title,
            sort_order=len(existing),
            created_at=now,
            updated_at=now,
        )
        self.store.create_subtask(sub)
        self.store.append_event(
            task_id=task_id,
            event_type=TaskEventType.SUBTASK_CREATED.value,
            actor_type=actor_type,
            actor_id=actor_id,
            payload={"subtaskId": sub.subtask_id, "title": title},
        )
        self._rollup_manual_progress(task_id)
        return sub

    def update_subtask(
        self,
        task_id: str,
        subtask_id: str,
        *,
        title: str | None = None,
        completed: bool | None = None,
        sort_order: int | None = None,
        actor_type: str = "operator",
        actor_id: str | None = None,
    ) -> TaskSubtask:
        self.get(task_id, sync=False)
        sub = self.store.get_subtask(subtask_id)
        if sub is None or sub.task_id != task_id:
            raise TaskError("NOT_FOUND", f"Subtask not found: {subtask_id}", http_status=404)
        if title is not None:
            t = title.strip()
            if not t:
                raise TaskError("INVALID_TITLE", "Subtask title is required", http_status=422)
            sub.title = t
        if completed is not None:
            sub.completed = bool(completed)
            sub.completed_at = utc_now() if sub.completed else None
        if sort_order is not None:
            sub.sort_order = int(sort_order)
        self.store.update_subtask(sub)
        self.store.append_event(
            task_id=task_id,
            event_type=TaskEventType.SUBTASK_UPDATED.value,
            actor_type=actor_type,
            actor_id=actor_id,
            payload={"subtaskId": sub.subtask_id, "completed": sub.completed},
        )
        self._rollup_manual_progress(task_id)
        return sub

    def delete_subtask(
        self,
        task_id: str,
        subtask_id: str,
        *,
        actor_type: str = "operator",
        actor_id: str | None = None,
    ) -> None:
        self.get(task_id, sync=False)
        sub = self.store.get_subtask(subtask_id)
        if sub is None or sub.task_id != task_id:
            raise TaskError("NOT_FOUND", f"Subtask not found: {subtask_id}", http_status=404)
        self.store.delete_subtask(subtask_id)
        self.store.append_event(
            task_id=task_id,
            event_type=TaskEventType.SUBTASK_DELETED.value,
            actor_type=actor_type,
            actor_id=actor_id,
            payload={"subtaskId": subtask_id},
        )
        self._rollup_manual_progress(task_id)

    def _rollup_manual_progress(self, task_id: str) -> None:
        record = self.store.get_task(task_id)
        if record is None:
            return
        if record.execution_binding != ExecutionBinding.MANUAL:
            return
        if record.job_id or record.mission_id:
            return
        subs = self.store.list_subtasks(task_id)
        if not subs:
            return
        done = sum(1 for s in subs if s.completed)
        record.progress = float(done) / float(len(subs))
        self.store.update_task(record)

    def list_notes(self, task_id: str) -> list[TaskNote]:
        self.get(task_id, sync=False)
        return self.store.list_notes(task_id)

    def create_note(
        self,
        task_id: str,
        *,
        body: str,
        author_type: str = "operator",
        author_id: str | None = None,
        author_name: str | None = None,
    ) -> TaskNote:
        self.get(task_id, sync=False)
        body = (body or "").strip()
        if not body:
            raise TaskError("INVALID_NOTE", "Note body is required", http_status=422)
        now = utc_now()
        note = TaskNote(
            note_id=str(uuid.uuid4()),
            task_id=task_id,
            body=body,
            author_type=author_type,
            author_id=author_id,
            author_name=author_name or "Operator",
            created_at=now,
            updated_at=now,
        )
        self.store.create_note(note)
        self.store.append_event(
            task_id=task_id,
            event_type=TaskEventType.NOTE_ADDED.value,
            actor_type=author_type,
            actor_id=author_id,
            payload={"noteId": note.note_id},
        )
        return note

    def update_note(self, task_id: str, note_id: str, *, body: str) -> TaskNote:
        self.get(task_id, sync=False)
        note = self.store.get_note(note_id)
        if note is None or note.task_id != task_id:
            raise TaskError("NOT_FOUND", f"Note not found: {note_id}", http_status=404)
        body = (body or "").strip()
        if not body:
            raise TaskError("INVALID_NOTE", "Note body is required", http_status=422)
        note.body = body
        return self.store.update_note(note)

    def delete_note(
        self,
        task_id: str,
        note_id: str,
        *,
        actor_type: str = "operator",
        actor_id: str | None = None,
    ) -> None:
        self.get(task_id, sync=False)
        note = self.store.get_note(note_id)
        if note is None or note.task_id != task_id:
            raise TaskError("NOT_FOUND", f"Note not found: {note_id}", http_status=404)
        self.store.delete_note(note_id)
        self.store.append_event(
            task_id=task_id,
            event_type=TaskEventType.NOTE_DELETED.value,
            actor_type=actor_type,
            actor_id=actor_id,
            payload={"noteId": note_id},
        )

    def list_dependencies(self, task_id: str) -> list[dict[str, Any]]:
        self.get(task_id, sync=False)
        deps = self.store.list_dependencies(task_id)
        out: list[dict[str, Any]] = []
        for dep in deps:
            other = self.store.get_task(dep.depends_on_task_id)
            payload = dep.public_dict()
            if other:
                payload["dependsOn"] = {
                    "taskId": other.task_id,
                    "title": other.title,
                    "boardColumn": other.board_column.value,
                    "executionState": other.execution_state,
                    "blocked": other.blocked,
                    "completed": bool(other.completed_at or other.board_column == BoardColumn.DONE),
                }
            out.append(payload)
        return out

    def add_dependency(
        self,
        task_id: str,
        *,
        depends_on_task_id: str,
        soft: bool = False,
        actor_type: str = "operator",
        actor_id: str | None = None,
    ) -> TaskDependency:
        self.get(task_id, sync=False)
        other = self.store.get_task(depends_on_task_id)
        if other is None:
            raise TaskError("NOT_FOUND", f"Dependency target not found: {depends_on_task_id}", http_status=404)
        dep = self.store.add_dependency(task_id=task_id, depends_on_task_id=depends_on_task_id, soft=soft)
        self.store.append_event(
            task_id=task_id,
            event_type=TaskEventType.DEPENDENCY_ADDED.value,
            actor_type=actor_type,
            actor_id=actor_id,
            payload={"dependencyId": dep.dependency_id, "dependsOnTaskId": depends_on_task_id},
        )
        self.recompute_blocking(task_id)
        return dep

    def remove_dependency(
        self,
        task_id: str,
        dependency_id: str,
        *,
        actor_type: str = "operator",
        actor_id: str | None = None,
    ) -> None:
        self.get(task_id, sync=False)
        dep = self.store.get_dependency(dependency_id)
        if dep is None or dep.task_id != task_id:
            raise TaskError("NOT_FOUND", f"Dependency not found: {dependency_id}", http_status=404)
        self.store.remove_dependency(dependency_id)
        self.store.append_event(
            task_id=task_id,
            event_type=TaskEventType.DEPENDENCY_REMOVED.value,
            actor_type=actor_type,
            actor_id=actor_id,
            payload={"dependencyId": dependency_id},
        )
        self.recompute_blocking(task_id)

    def list_events(self, task_id: str, *, limit: int = 100, offset: int = 0) -> list[Any]:
        self.get(task_id, sync=False)
        return self.store.list_events(task_id=task_id, limit=limit, offset=offset)

    # ── Mission control aggregates ──────────────────────────────────────────

    def summary(self, *, timezone_name: str | None = None) -> TaskSummary:
        tz = _zone(timezone_name)
        today_start, today_end = _day_bounds(tz)
        yday = datetime.now(timezone.utc).astimezone(tz) - timedelta(days=1)
        y_start, y_end = _day_bounds(tz, day=yday)
        now = utc_now()

        tasks = self.store.list_all_active(limit=5000)
        for t in tasks:
            try:
                self.sync_execution(t.task_id)
            except TaskError:
                pass
        tasks = [self.recompute_blocking(t.task_id) for t in tasks]
        archived = self.store.list_tasks(archived=True, limit=2000)

        column_counts = {c.value: 0 for c in BoardColumn}
        active = 0
        in_progress = 0
        blocked = 0
        completed_today = 0
        completed_yesterday = 0
        overdue = 0
        agent_ids: set[str] = set()

        def _completed_stamp(t: TaskRecord) -> str | None:
            if t.completed_at:
                return t.completed_at
            if t.board_column == BoardColumn.DONE:
                return t.updated_at
            return None

        for t in tasks:
            column_counts[t.board_column.value] = column_counts.get(t.board_column.value, 0) + 1
            if t.board_column != BoardColumn.DONE and not t.completed_at:
                active += 1
            if t.board_column == BoardColumn.IN_PROGRESS:
                in_progress += 1
            if t.blocked:
                blocked += 1
            if (
                t.due_at
                and t.due_at < now
                and not t.completed_at
                and t.board_column != BoardColumn.DONE
            ):
                overdue += 1
            if t.assignee_type == AssigneeType.AGENT and t.assignee_id and t.board_column != BoardColumn.DONE:
                agent_ids.add(t.assignee_id)

        for t in list(tasks) + list(archived):
            stamp = _completed_stamp(t)
            if not stamp:
                continue
            if today_start <= stamp < today_end:
                completed_today += 1
            if y_start <= stamp < y_end:
                completed_yesterday += 1

        return TaskSummary(
            active=active,
            in_progress=in_progress,
            blocked=blocked,
            completed_today=completed_today,
            overdue=overdue,
            agents_assigned=len(agent_ids),
            completed_previous_period=completed_yesterday,
            column_counts=column_counts,
            timezone=str(tz),
        )

    def activity(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        events = self.store.list_events(limit=limit, offset=offset)
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for ev in events:
            if ev.event_id in seen:
                continue
            seen.add(ev.event_id)
            task = self.store.get_task(ev.task_id)
            payload = ev.public_dict()
            payload["taskTitle"] = task.title if task else None
            out.append(payload)
        return out

    def timeline(
        self,
        *,
        view: str = "today",
        timezone_name: str | None = None,
    ) -> list[TaskTimelineItem]:
        tz = _zone(timezone_name)
        view = (view or "today").lower()
        now_local = datetime.now(timezone.utc).astimezone(tz)
        if view == "today":
            start_s, end_s = _day_bounds(tz)
        elif view == "week":
            weekday = now_local.weekday()
            week_start = (now_local - timedelta(days=weekday)).replace(hour=0, minute=0, second=0, microsecond=0)
            week_end = week_start + timedelta(days=7)
            start_s = week_start.astimezone(timezone.utc).isoformat(timespec="seconds")
            end_s = week_end.astimezone(timezone.utc).isoformat(timespec="seconds")
        else:  # calendar — current month
            month_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if month_start.month == 12:
                month_end = month_start.replace(year=month_start.year + 1, month=1)
            else:
                month_end = month_start.replace(month=month_start.month + 1)
            start_s = month_start.astimezone(timezone.utc).isoformat(timespec="seconds")
            end_s = month_end.astimezone(timezone.utc).isoformat(timespec="seconds")

        items: list[TaskTimelineItem] = []
        for t in self.store.list_all_active(limit=2000):
            candidates: list[tuple[str, str | None, str | None]] = []
            if t.planned_start_at or t.due_at:
                candidates.append(("planned", t.planned_start_at or t.due_at, t.due_at))
            if t.execution_started_at or t.execution_finished_at:
                candidates.append(("execution", t.execution_started_at, t.execution_finished_at or t.execution_started_at))
            if t.due_at and not t.planned_start_at:
                candidates.append(("due", t.due_at, t.due_at))
            for kind, s, e in candidates:
                if not s and not e:
                    continue
                # intersect window
                s_cmp = s or e
                e_cmp = e or s
                if s_cmp and e_cmp and e_cmp < start_s:
                    continue
                if s_cmp and s_cmp >= end_s:
                    continue
                items.append(
                    TaskTimelineItem(
                        task_id=t.task_id,
                        title=t.title,
                        board_column=t.board_column.value,
                        start_at=s,
                        end_at=e,
                        kind=kind,
                        execution_state=t.execution_state,
                        blocked=t.blocked,
                    )
                )
        items.sort(key=lambda i: i.start_at or i.end_at or "")
        return items

    def workload(self) -> list[TaskWorkloadEntry]:
        now = utc_now()
        by_key: dict[str, TaskWorkloadEntry] = {}
        for t in self.store.list_all_active(limit=5000):
            if t.board_column == BoardColumn.DONE or t.completed_at:
                continue
            key = t.assignee_id or t.assignee_name or "__unassigned__"
            name = t.assignee_name or ("Unassigned" if key == "__unassigned__" else str(t.assignee_id))
            entry = by_key.get(key)
            if entry is None:
                max_c = None
                if t.assignee_type == AssigneeType.AGENT and t.assignee_id and self.agent_fleet is not None:
                    agent = self.agent_fleet.store.get_definition(t.assignee_id)
                    if agent is not None:
                        max_c = int(getattr(agent, "max_concurrency", 1) or 1)
                        name = agent.name
                entry = TaskWorkloadEntry(
                    assignee_id=t.assignee_id,
                    assignee_name=name,
                    assignee_type=t.assignee_type.value,
                    max_concurrency=max_c,
                )
                by_key[key] = entry
            entry.active_count += 1
            if t.board_column == BoardColumn.IN_PROGRESS:
                entry.in_progress_count += 1
            if t.blocked:
                entry.blocked_count += 1
            if t.due_at and t.due_at < now:
                entry.overdue_count += 1
        return sorted(by_key.values(), key=lambda e: (-e.active_count, e.assignee_name.lower()))

    def weekday_completions(self, *, timezone_name: str | None = None) -> dict[str, Any]:
        tz = _zone(timezone_name)
        now_local = datetime.now(timezone.utc).astimezone(tz)
        weekday = now_local.weekday()
        week_start = (now_local - timedelta(days=weekday)).replace(hour=0, minute=0, second=0, microsecond=0)
        bars = [0] * 7
        # Scan active + archived
        for t in self.store.list_tasks(archived=False, limit=5000) + self.store.list_tasks(archived=True, limit=5000):
            stamp = t.completed_at
            if not stamp:
                continue
            try:
                dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError:
                continue
            local = dt.astimezone(tz)
            if local < week_start or local >= week_start + timedelta(days=7):
                continue
            bars[local.weekday()] += 1
        return {
            "timezone": str(tz),
            "weekStart": week_start.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "bars": bars,
            "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        }

    def agent_activity(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if self.agent_fleet is None:
            return []
        agents = self.agent_fleet.list_agents(include_archived=False)
        # Map assignee_id -> active tasks
        tasks = self.store.list_all_active(limit=2000)
        by_agent: dict[str, list[TaskRecord]] = {}
        for t in tasks:
            if t.assignee_type == AssigneeType.AGENT and t.assignee_id and t.board_column != BoardColumn.DONE:
                by_agent.setdefault(t.assignee_id, []).append(t)

        out: list[dict[str, Any]] = []
        for agent in agents:
            assigned = by_agent.get(agent.agent_id, [])
            mission = None
            if getattr(agent, "last_mission_id", None):
                mission = self.agent_fleet.store.get_mission(agent.last_mission_id)
            # Prefer task-linked mission
            linked_mission = None
            for t in assigned:
                if t.mission_id:
                    linked_mission = self.agent_fleet.store.get_mission(t.mission_id)
                    if linked_mission:
                        break
            active_mission = linked_mission or mission
            detail = None
            progress = None
            phase = None
            if assigned:
                detail = assigned[0].title
                progress = assigned[0].execution_progress
                phase = assigned[0].execution_phase
            if active_mission is not None:
                detail = detail or getattr(active_mission, "title", None) or getattr(active_mission, "request", None)
                if isinstance(getattr(active_mission, "result", None), dict):
                    raw_p = active_mission.result.get("progress")
                    if isinstance(raw_p, (int, float)):
                        progress = float(raw_p)
            status = _enum_val(getattr(agent, "health", "unknown"))
            if active_mission is not None:
                mstatus = _enum_val(active_mission.status)
                if mstatus in {"queued", "starting", "running", "cancelling"}:
                    status = mstatus
            out.append(
                {
                    "agentId": agent.agent_id,
                    "name": agent.name,
                    "status": status,
                    "detail": detail,
                    "phase": phase,
                    "progress": progress,
                    "activeTaskCount": len(assigned),
                    "activeTaskId": assigned[0].task_id if assigned else None,
                    "lastRunAt": getattr(agent, "last_run_at", None),
                    "missionId": getattr(active_mission, "mission_id", None) if active_mission else None,
                }
            )
        # Prefer agents with activity
        out.sort(key=lambda r: (-(r["activeTaskCount"] or 0), r["name"].lower()))
        return out[: max(1, min(limit, 100))]

    def enrich_task(self, task: TaskRecord) -> dict[str, Any]:
        subs = self.store.list_subtasks(task.task_id)
        done = sum(1 for s in subs if s.completed)
        progress = compute_display_progress(task, subtask_completed=done, subtask_total=len(subs))
        payload = task.public_dict()
        payload["displayProgress"] = progress
        payload["subtaskCount"] = len(subs)
        payload["subtaskCompleted"] = done
        blockers = self._unresolved_hard_dependencies(task.task_id)
        payload["blockingDependencies"] = [
            {"taskId": b.task_id, "title": b.title, "boardColumn": b.board_column.value, "executionState": b.execution_state}
            for b in blockers
        ]
        return payload

    # ── Quick capture / Auto-plan ───────────────────────────────────────────

    def quick_capture(
        self,
        *,
        title: str,
        description: str = "",
        priority: str = "medium",
        due_at: str | None = None,
        assignee_type: str = "none",
        assignee_id: str | None = None,
        assignee_name: str | None = None,
        actor_type: str = "operator",
        actor_id: str | None = None,
    ) -> TaskRecord:
        return self.create(
            title=title,
            description=description,
            priority=priority or "medium",
            board_column=BoardColumn.BACKLOG.value,
            due_at=due_at,
            assignee_type=assignee_type,
            assignee_id=assignee_id,
            assignee_name=assignee_name,
            execution_binding=ExecutionBinding.MANUAL.value,
            created_by="operator",
            actor_type=actor_type,
            actor_id=actor_id,
        )

    def auto_plan_preview(
        self,
        *,
        brief: str,
        target_date: str | None = None,
        project: str | None = None,
        priority: str | None = None,
        allowed_agent_ids: list[str] | None = None,
    ) -> list[TaskAutoPlanProposal]:
        agents_payload: list[dict[str, str]] = []
        allowed = list(allowed_agent_ids or [])
        if self.agent_fleet is not None:
            roster = self.agent_fleet.list_agents(include_archived=False)
            if not allowed:
                allowed = [a.agent_id for a in roster if getattr(a, "enabled", True)]
            for a in roster:
                if a.agent_id in allowed:
                    agents_payload.append({"id": a.agent_id, "name": a.name})
        return self.planner.preview(
            brief=brief,
            target_date=target_date,
            project=project,
            priority=priority,
            allowed_agent_ids=allowed,
            allowed_agents=agents_payload,
        )

    def auto_plan_commit(
        self,
        *,
        proposals: list[dict[str, Any]] | list[TaskAutoPlanProposal],
        project: str | None = None,
        actor_type: str = "operator",
        actor_id: str | None = None,
    ) -> list[TaskRecord]:
        allowed_ids: set[str] = set()
        if self.agent_fleet is not None:
            allowed_ids = {
                a.agent_id
                for a in self.agent_fleet.list_agents(include_archived=False)
                if getattr(a, "enabled", True)
            }
        normalized = self.planner.validate_proposals(
            {
                "tasks": [
                    p.public_dict()
                    if isinstance(p, TaskAutoPlanProposal)
                    else {
                        "title": p.get("title"),
                        "description": p.get("description") or p.get("description"),
                        "priority": p.get("priority") or "medium",
                        "suggested_assignee_id": p.get("suggestedAssigneeId", p.get("suggested_assignee_id")),
                        "tags": p.get("tags") or [],
                        "due_at": p.get("dueAt", p.get("due_at")),
                        "dependencies": p.get("dependencies") or [],
                    }
                    for p in proposals
                ]
            },
            allowed_agent_ids=allowed_ids if allowed_ids else None,
        )

        created: list[TaskRecord] = []
        # Transactional: create all tasks first, then deps; on failure archive created
        try:
            index_to_id: dict[int, str] = {}
            for idx, prop in enumerate(normalized):
                a_type = AssigneeType.NONE.value
                a_id = None
                a_name = None
                if prop.suggested_assignee_id:
                    a_type = AssigneeType.AGENT.value
                    a_id = prop.suggested_assignee_id
                task = self.create(
                    title=prop.title,
                    description=prop.description,
                    priority=prop.priority,
                    board_column=BoardColumn.BACKLOG.value,
                    tags=list(prop.tags),
                    project=project,
                    assignee_type=a_type,
                    assignee_id=a_id,
                    assignee_name=a_name,
                    due_at=prop.due_at,
                    execution_binding=ExecutionBinding.MANUAL.value,
                    created_by="auto-plan",
                    metadata={"autoPlan": True},
                    actor_type=actor_type,
                    actor_id=actor_id,
                )
                created.append(task)
                index_to_id[idx] = task.task_id
            for idx, prop in enumerate(normalized):
                for dep_idx in prop.dependencies:
                    self.add_dependency(
                        index_to_id[idx],
                        depends_on_task_id=index_to_id[dep_idx],
                        actor_type=actor_type,
                        actor_id=actor_id,
                    )
            for task in created:
                self.store.append_event(
                    task_id=task.task_id,
                    event_type=TaskEventType.AUTO_PLAN_COMMITTED.value,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    payload={"count": len(created)},
                )
        except Exception:
            for task in created:
                try:
                    self.archive(task.task_id, actor_type="system", actor_id="auto-plan-rollback")
                except TaskError:
                    pass
            raise
        return [self.get(t.task_id) for t in created]

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _date_preset_bounds(self, preset: str, timezone_name: str | None) -> tuple[str, str]:
        tz = _zone(timezone_name)
        now_local = datetime.now(timezone.utc).astimezone(tz)
        preset = preset.lower().strip()
        if preset == "today":
            return _day_bounds(tz)
        if preset == "week":
            weekday = now_local.weekday()
            start = (now_local - timedelta(days=weekday)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=7)
            return (
                start.astimezone(timezone.utc).isoformat(timespec="seconds"),
                end.astimezone(timezone.utc).isoformat(timespec="seconds"),
            )
        if preset == "month":
            start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if start.month == 12:
                end = start.replace(year=start.year + 1, month=1)
            else:
                end = start.replace(month=start.month + 1)
            return (
                start.astimezone(timezone.utc).isoformat(timespec="seconds"),
                end.astimezone(timezone.utc).isoformat(timespec="seconds"),
            )
        raise TaskError("INVALID_DATE_PRESET", f"Unknown date preset: {preset}", http_status=422)

    def _assert_agent_usable(self, agent_id: str) -> None:
        if self.agent_fleet is None:
            return
        agent = self.agent_fleet.store.get_definition(agent_id)
        if agent is None:
            raise TaskError("MISSING_AGENT", f"Agent not found: {agent_id}", http_status=422)
        if getattr(agent, "archived", False):
            raise TaskError("MISSING_AGENT", f"Agent is archived: {agent_id}", http_status=422)
        if not getattr(agent, "enabled", True):
            raise TaskError("DISABLED_AGENT", f"Agent is disabled: {agent_id}", http_status=422)

    def _assert_capability_exists(self, capability_id: str) -> None:
        if not capability_id:
            raise TaskError("MISSING_CAPABILITY", "capability_id is required", http_status=422)
        if self.execution_gateway is None:
            return
        caps = None
        if hasattr(self.execution_gateway, "list_capabilities"):
            caps = self.execution_gateway.list_capabilities()
        elif hasattr(self.execution_gateway, "catalog") and hasattr(self.execution_gateway.catalog, "list"):
            caps = self.execution_gateway.catalog.list()
        if caps is None:
            return
        ids = set()
        for c in caps:
            cid = getattr(c, "capability_id", None) or getattr(c, "id", None)
            if isinstance(c, dict):
                cid = c.get("capability_id") or c.get("id")
            if cid:
                ids.add(str(cid))
        if capability_id not in ids:
            raise TaskError("MISSING_CAPABILITY", f"Capability not found: {capability_id}", http_status=422)

    def _assert_workflow_exists(self, workflow_id: str) -> None:
        if self.workflow_runtime is None:
            return
        wf = None
        if hasattr(self.workflow_runtime, "store"):
            wf = self.workflow_runtime.store.get(workflow_id)
        if wf is None:
            raise TaskError("MISSING_WORKFLOW", f"Workflow not found: {workflow_id}", http_status=422)


def _enum_val(value: Any) -> str:
    return str(getattr(value, "value", value) or "")
