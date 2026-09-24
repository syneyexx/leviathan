"""FastAPI routes for the Tasks Mission Control surface."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from Data.modules.tasks import TaskError, TaskService


def _raise(exc: TaskError) -> None:
    raise HTTPException(status_code=exc.http_status, detail=exc.public_dict()) from exc


class TaskCreateBody(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    priority: str = "medium"
    boardColumn: str = "backlog"
    tags: list[str] = Field(default_factory=list)
    project: str | None = None
    assigneeType: str = "none"
    assigneeId: str | None = None
    assigneeName: str | None = None
    dueAt: str | None = None
    plannedStartAt: str | None = None
    progress: float | None = Field(default=None, ge=0, le=1)
    executionBinding: str = "manual"
    capabilityId: str | None = None
    capabilityArguments: dict[str, Any] = Field(default_factory=dict)
    missionRequest: str | None = None
    workflowId: str | None = None
    scheduleId: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskPatchBody(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    priority: str | None = None
    boardColumn: str | None = None
    tags: list[str] | None = None
    project: str | None = None
    assigneeType: str | None = None
    assigneeId: str | None = None
    assigneeName: str | None = None
    dueAt: str | None = None
    plannedStartAt: str | None = None
    progress: float | None = Field(default=None, ge=0, le=1)
    manualBlock: bool | None = None
    blockedReason: str | None = None


class SubtaskCreateBody(BaseModel):
    title: str = Field(min_length=1, max_length=300)


class SubtaskPatchBody(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    completed: bool | None = None
    sortOrder: int | None = None


class NoteCreateBody(BaseModel):
    body: str = Field(min_length=1, max_length=20_000)
    authorName: str | None = None


class NotePatchBody(BaseModel):
    body: str = Field(min_length=1, max_length=20_000)


class DependencyCreateBody(BaseModel):
    dependsOnTaskId: str = Field(min_length=1)
    soft: bool = False


class QuickCaptureBody(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    priority: str = "medium"
    dueAt: str | None = None
    assigneeType: str = "none"
    assigneeId: str | None = None
    assigneeName: str | None = None


class AutoPlanPreviewBody(BaseModel):
    brief: str = Field(min_length=1, max_length=20_000)
    targetDate: str | None = None
    project: str | None = None
    priority: str | None = None
    allowedAgentIds: list[str] = Field(default_factory=list)


class AutoPlanCommitBody(BaseModel):
    proposals: list[dict[str, Any]] = Field(min_length=1)
    project: str | None = None


def build_tasks_router(service: TaskService) -> APIRouter:
    router = APIRouter(tags=["tasks"])

    @router.get("/api/tasks/summary")
    def tasks_summary(timezone: str | None = Query(default=None)) -> dict:
        try:
            return {"summary": service.summary(timezone_name=timezone).public_dict()}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.get("/api/tasks/activity")
    def tasks_activity(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict:
        return {"activity": service.activity(limit=limit, offset=offset)}

    @router.get("/api/tasks/timeline")
    def tasks_timeline(
        view: str = Query("today"),
        timezone: str | None = Query(default=None),
    ) -> dict:
        try:
            items = service.timeline(view=view, timezone_name=timezone)
            return {"timeline": [i.public_dict() for i in items], "view": view}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.get("/api/tasks/workload")
    def tasks_workload() -> dict:
        return {"workload": [w.public_dict() for w in service.workload()]}

    @router.get("/api/tasks/weekday-completions")
    def tasks_weekday(timezone: str | None = Query(default=None)) -> dict:
        try:
            return service.weekday_completions(timezone_name=timezone)
        except TaskError as exc:
            _raise(exc)
            raise

    @router.get("/api/tasks/agent-activity")
    def tasks_agent_activity(limit: int = Query(20, ge=1, le=100)) -> dict:
        return {"agents": service.agent_activity(limit=limit)}

    @router.post("/api/tasks/quick-capture")
    def quick_capture(payload: QuickCaptureBody) -> dict:
        try:
            task = service.quick_capture(
                title=payload.title,
                description=payload.description,
                priority=payload.priority,
                due_at=payload.dueAt,
                assignee_type=payload.assigneeType,
                assignee_id=payload.assigneeId,
                assignee_name=payload.assigneeName,
            )
            return {"task": service.enrich_task(task)}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.post("/api/tasks/auto-plan/preview")
    def auto_plan_preview(payload: AutoPlanPreviewBody) -> dict:
        try:
            proposals = service.auto_plan_preview(
                brief=payload.brief,
                target_date=payload.targetDate,
                project=payload.project,
                priority=payload.priority,
                allowed_agent_ids=payload.allowedAgentIds or None,
            )
            return {"proposals": [p.public_dict() for p in proposals]}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.post("/api/tasks/auto-plan/commit")
    def auto_plan_commit(payload: AutoPlanCommitBody) -> dict:
        try:
            tasks = service.auto_plan_commit(proposals=payload.proposals, project=payload.project)
            return {"tasks": [service.enrich_task(t) for t in tasks]}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.get("/api/tasks")
    def list_tasks(
        search: str | None = None,
        boardColumn: str | None = None,
        executionState: str | None = None,
        priority: str | None = None,
        assignee: str | None = None,
        blocked: bool | None = None,
        overdue: bool | None = None,
        dueFrom: str | None = None,
        dueTo: str | None = None,
        project: str | None = None,
        archived: bool = False,
        datePreset: str | None = None,
        timezone: str | None = None,
        limit: int = Query(200, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ) -> dict:
        try:
            tasks = service.list(
                search=search,
                board_column=boardColumn,
                execution_state=executionState,
                priority=priority,
                assignee=assignee,
                blocked=blocked,
                overdue=overdue,
                due_from=dueFrom,
                due_to=dueTo,
                project=project,
                archived=archived,
                date_preset=datePreset,
                timezone_name=timezone,
                limit=limit,
                offset=offset,
            )
            return {"tasks": [service.enrich_task(t) for t in tasks]}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.post("/api/tasks")
    def create_task(payload: TaskCreateBody) -> dict:
        try:
            task = service.create(
                title=payload.title,
                description=payload.description,
                priority=payload.priority,
                board_column=payload.boardColumn,
                tags=payload.tags,
                project=payload.project,
                assignee_type=payload.assigneeType,
                assignee_id=payload.assigneeId,
                assignee_name=payload.assigneeName,
                due_at=payload.dueAt,
                planned_start_at=payload.plannedStartAt,
                progress=payload.progress,
                execution_binding=payload.executionBinding,
                capability_id=payload.capabilityId,
                capability_arguments=payload.capabilityArguments,
                mission_request=payload.missionRequest,
                workflow_id=payload.workflowId,
                schedule_id=payload.scheduleId,
                metadata=payload.metadata,
            )
            return {"task": service.enrich_task(task)}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.get("/api/tasks/{task_id}")
    def get_task(task_id: str) -> dict:
        try:
            task = service.get(task_id)
            return {"task": service.enrich_task(task)}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.patch("/api/tasks/{task_id}")
    def patch_task(task_id: str, payload: TaskPatchBody) -> dict:
        try:
            patch = payload.model_dump(exclude_unset=True)
            task = service.update(task_id, patch=patch)
            return {"task": service.enrich_task(task)}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.post("/api/tasks/{task_id}/archive")
    def archive_task(task_id: str) -> dict:
        try:
            task = service.archive(task_id)
            return {"task": service.enrich_task(task)}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.post("/api/tasks/{task_id}/duplicate")
    def duplicate_task(task_id: str) -> dict:
        try:
            task = service.duplicate_as_manual(task_id)
            return {"task": service.enrich_task(task)}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.post("/api/tasks/{task_id}/start")
    def start_task(task_id: str) -> dict:
        try:
            task = service.start(task_id)
            return {"task": service.enrich_task(task)}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.post("/api/tasks/{task_id}/cancel")
    def cancel_task(task_id: str) -> dict:
        try:
            task = service.cancel(task_id)
            return {"task": service.enrich_task(task)}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.post("/api/tasks/{task_id}/retry")
    def retry_task(task_id: str) -> dict:
        try:
            task = service.retry(task_id)
            return {"task": service.enrich_task(task)}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.get("/api/tasks/{task_id}/events")
    def task_events(task_id: str, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)) -> dict:
        try:
            events = service.list_events(task_id, limit=limit, offset=offset)
            return {"events": [e.public_dict() for e in events]}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.get("/api/tasks/{task_id}/subtasks")
    def list_subtasks(task_id: str) -> dict:
        try:
            return {"subtasks": [s.public_dict() for s in service.list_subtasks(task_id)]}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.post("/api/tasks/{task_id}/subtasks")
    def create_subtask(task_id: str, payload: SubtaskCreateBody) -> dict:
        try:
            sub = service.create_subtask(task_id, title=payload.title)
            return {"subtask": sub.public_dict()}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.patch("/api/tasks/{task_id}/subtasks/{subtask_id}")
    def patch_subtask(task_id: str, subtask_id: str, payload: SubtaskPatchBody) -> dict:
        try:
            sub = service.update_subtask(
                task_id,
                subtask_id,
                title=payload.title,
                completed=payload.completed,
                sort_order=payload.sortOrder,
            )
            return {"subtask": sub.public_dict()}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.delete("/api/tasks/{task_id}/subtasks/{subtask_id}")
    def delete_subtask(task_id: str, subtask_id: str) -> dict:
        try:
            service.delete_subtask(task_id, subtask_id)
            return {"ok": True}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.get("/api/tasks/{task_id}/notes")
    def list_notes(task_id: str) -> dict:
        try:
            return {"notes": [n.public_dict() for n in service.list_notes(task_id)]}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.post("/api/tasks/{task_id}/notes")
    def create_note(task_id: str, payload: NoteCreateBody) -> dict:
        try:
            note = service.create_note(task_id, body=payload.body, author_name=payload.authorName)
            return {"note": note.public_dict()}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.patch("/api/tasks/{task_id}/notes/{note_id}")
    def patch_note(task_id: str, note_id: str, payload: NotePatchBody) -> dict:
        try:
            note = service.update_note(task_id, note_id, body=payload.body)
            return {"note": note.public_dict()}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.delete("/api/tasks/{task_id}/notes/{note_id}")
    def delete_note(task_id: str, note_id: str) -> dict:
        try:
            service.delete_note(task_id, note_id)
            return {"ok": True}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.get("/api/tasks/{task_id}/dependencies")
    def list_dependencies(task_id: str) -> dict:
        try:
            return {"dependencies": service.list_dependencies(task_id)}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.post("/api/tasks/{task_id}/dependencies")
    def add_dependency(task_id: str, payload: DependencyCreateBody) -> dict:
        try:
            dep = service.add_dependency(
                task_id,
                depends_on_task_id=payload.dependsOnTaskId,
                soft=payload.soft,
            )
            return {"dependency": dep.public_dict()}
        except TaskError as exc:
            _raise(exc)
            raise

    @router.delete("/api/tasks/{task_id}/dependencies/{dependency_id}")
    def remove_dependency(task_id: str, dependency_id: str) -> dict:
        try:
            service.remove_dependency(task_id, dependency_id)
            return {"ok": True}
        except TaskError as exc:
            _raise(exc)
            raise

    return router
