"""HTTP routes for artifacts, approvals, inbox, schedules, search, build and memory review."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

import fastapi_nested_annotations  # noqa: F401 — nested PEP 563 OpenAPI fix

router = APIRouter(tags=["capabilities"])


def _mcp_max_connections(default: int = 8) -> int | None:
    try:
        from control.service import resolve_setting

        value = resolve_setting("mcp.max_connections", default=default)
        return None if value is None else int(value)
    except Exception:
        return default


class ArtifactGenerateInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=0, max_length=2_000_000)
    mime_type: str | None = Field(default=None, max_length=120)
    conversation_id: str | None = None
    task_id: str | None = None
    project_id: str | None = None
    kind: Literal["generated", "log", "evidence"] = "generated"


class ApprovalDecisionInput(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=2000)
    response_payload: dict[str, Any] = Field(default_factory=dict)


class ScheduleInput(BaseModel):
    frequency: Literal["once", "daily", "weekly"]
    timezone: str = Field(default="UTC", max_length=80)
    run_at: str | None = None
    time_of_day: str | None = Field(default=None, max_length=8)
    weekday: int | None = Field(default=None, ge=0, le=6)
    enabled: bool = True
    catch_up: bool = True
    preview_only: bool = False


class SearchInput(BaseModel):
    query: str = Field(min_length=0, max_length=500)
    project_id: str | None = None
    limit_per_type: int = Field(default=8, ge=1, le=30)


class MemoryProposalDecision(BaseModel):
    action: Literal["accept", "edit", "reject", "merge"]
    edited: dict[str, Any] = Field(default_factory=dict)


class ForgetInput(BaseModel):
    conversation_id: str | None = None
    memory_id: str | None = None
    include_derived: bool = True
    preview_only: bool = False


class BuildEdit(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    action: Literal["create", "replace", "patch_lines"]
    content: str | None = None
    old_content: str | None = None
    start_line: int | None = None
    end_line: int | None = None


class BuildRunInput(BaseModel):
    source_repo: str = Field(min_length=1, max_length=1000)
    edits: list[BuildEdit] = Field(default_factory=list, max_length=50)
    repair_waves: list[list[BuildEdit]] = Field(default_factory=list, max_length=3)
    test_suite: Literal["pytest", "unittest", "npm_test"] = "unittest"
    test_args: list[str] = Field(default_factory=list, max_length=20)
    max_attempts: int = Field(default=2, ge=1, le=5)
    goal: str = Field(default="", max_length=2000)
    auto_repair: bool = False
    use_omniroute: bool = False


class CodingGoalInput(BaseModel):
    source_repo: str = Field(min_length=1, max_length=1000)
    goal: str = Field(min_length=1, max_length=4000)
    test_suite: Literal["pytest", "unittest", "npm_test", "auto", "go_test", "cargo_test", "ctest"] = "auto"
    test_args: list[str] = Field(default_factory=list, max_length=20)
    max_attempts: int = Field(default=3, ge=1, le=5)
    model_id: str | None = Field(default=None, max_length=200)
    auto_repair: bool = True
    # fast = existing propose path; investigate = interactive research loop; auto = investigate for fix goals
    strategy: Literal["fast", "investigate", "auto"] = "fast"
    # deterministic = existing rules; model = allowed-action selector (still validated/dispatched deterministically)
    selector_mode: Literal["deterministic", "model"] = "deterministic"
    # Skill ≠ permission: analyze_only | managed_workspace_modify | reviewable_result
    autonomy_profile: Literal["analyze_only", "managed_workspace_modify", "reviewable_result"] = (
        "reviewable_result"
    )
    task_type: Literal["bugfix", "feature", "regression", "review"] | None = None
    # Optional OmniRoute coding backend. Default OFF; missing field deserializes as false.
    use_omniroute: bool = False
    # Advanced: optional pre-baked edits still allowed.
    edits: list[BuildEdit] = Field(default_factory=list, max_length=50)
    repair_waves: list[list[BuildEdit]] = Field(default_factory=list, max_length=3)
    approved_subprocess: bool = False


class CodingJobRedirectInput(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


class CodingJobStartInput(CodingGoalInput):
    """Same as CodingGoalInput; starts a background job and returns job id immediately."""

    pass


class BuildPlanInput(BaseModel):
    edits: list[BuildEdit] = Field(default_factory=list, max_length=50)
    goal: str = Field(default="", max_length=2000)


class BuildApplyInput(BaseModel):
    approved: bool = False


class TerminalRunInput(BaseModel):
    argv: list[str] = Field(min_length=1, max_length=40)
    cwd: str | None = Field(default=None, max_length=1000)
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    conversation_id: str | None = None
    task_id: str | None = None
    approved: bool = False
    # Distinct from file-write `approved`: subprocess ask must not reuse it.
    approved_subprocess: bool = False


class OnboardingCompleteInput(BaseModel):
    step: str = Field(default="done", max_length=80)


class SymbolSearchInput(BaseModel):
    workspace_id: str | None = None
    path: str | None = Field(default=None, max_length=1000)
    query: str = Field(default="", max_length=200)
    limit: int = Field(default=80, ge=1, le=300)
    refresh: bool = False
    use_cache: bool = True


class SymbolRefreshInput(BaseModel):
    workspace_id: str | None = None
    path: str | None = Field(default=None, max_length=1000)
    force: bool = False
    max_files: int = Field(default=400, ge=1, le=2000)


class WorkspaceTreeInput(BaseModel):
    workspace_id: str | None = None
    path: str | None = Field(default=None, max_length=1000)
    relative: str = Field(default="", max_length=1000)
    query: str = Field(default="", max_length=200)
    max_entries: int = Field(default=200, ge=1, le=500)


class WorkspacePreviewInput(BaseModel):
    workspace_id: str | None = None
    path: str | None = Field(default=None, max_length=1000)
    relative: str = Field(min_length=1, max_length=1000)
    max_chars: int = Field(default=20_000, ge=100, le=200_000)


class WorkspaceOpenInput(BaseModel):
    workspace_id: str | None = None
    path: str | None = Field(default=None, max_length=1000)
    relative: str = Field(min_length=1, max_length=1000)


class WorkspaceGitStatusInput(BaseModel):
    workspace_id: str | None = None
    path: str | None = Field(default=None, max_length=1000)


class WorkspaceGitCommitInput(BaseModel):
    workspace_id: str | None = None
    path: str | None = Field(default=None, max_length=1000)
    message: str = Field(min_length=1, max_length=2000)
    approved: bool = False


class LspQueryInput(BaseModel):
    workspace_id: str | None = None
    path: str | None = Field(default=None, max_length=1000)
    symbol: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=60, ge=1, le=200)


class VoiceTaskInput(BaseModel):
    transcript: str = Field(min_length=1, max_length=20_000)
    create: bool = False
    auto_start: bool = False
    agent: str = Field(default="auto", max_length=80)


class DebugDiagnoseInput(BaseModel):
    logs: str = Field(default="", max_length=200_000)
    failing_test: str = Field(default="", max_length=500)
    context_files: list[dict[str, str]] = Field(default_factory=list, max_length=20)


class ReleaseConfidenceInput(BaseModel):
    run_smoke: bool = False
    module: str = Field(default="tests.test_world_class_capabilities", max_length=200)
    approved_subprocess: bool = False


class ToolCardsInput(BaseModel):
    observations: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class BranchInput(BaseModel):
    fork_message_id: str
    title: str = Field(default="Vertakking", max_length=120)


class DraftInput(BaseModel):
    content: str = Field(default="", max_length=100_000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=20)


class ProjectCreateInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)


class ProjectItemInput(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(default="", max_length=8000)
    provenance: str = Field(default="user_explicit", max_length=40)
    status: str = Field(default="active", max_length=40)
    scope: str = Field(default="project", max_length=40)
    source_message_id: str | None = None
    source_conversation_id: str | None = None
    replace_overlapping: bool = True


class ProjectCorrectInput(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, max_length=8000)
    status: str | None = Field(default=None, max_length=40)


class ProactiveTriggerInput(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=200)
    scope: str = Field(default="", max_length=500)
    permission: str = Field(default="suggest", max_length=40)
    frequency_seconds: int = Field(default=3600, ge=60, le=86400 * 30)
    project_id: str | None = None
    enabled: bool = True


def mount_capability_routes(ctx: dict[str, Any]) -> APIRouter:
    class _Svc:
        def __getattr__(self, name: str) -> Any:
            return ctx[name]

        def get(self, name: str, default: Any = None) -> Any:
            return ctx.get(name, default)

    s = _Svc()

    def _policy(name: str, default: str = "ask") -> str:
        try:
            return str(s.database.get_settings().get(name) or default).lower()
        except Exception:
            return default

    def enforce_subprocess_policy(approved: bool, action: str) -> None:
        current = _policy("subprocess_policy", "allow")
        if current == "block":
            raise HTTPException(status_code=403, detail=f"{action} is geblokkeerd door subprocess_policy.")
        if current == "ask" and not approved:
            raise HTTPException(
                status_code=409,
                detail=f"Expliciete subprocess-toestemming vereist voor {action} (subprocess_policy=ask).",
            )

    @router.get("/artifacts")
    async def list_artifacts(
        conversation_id: str | None = None,
        task_id: str | None = None,
        project_id: str | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        return s.artifact_service.list(
            conversation_id=conversation_id,
            task_id=task_id,
            project_id=project_id,
            kind=kind,
        )

    @router.post("/artifacts/generate", status_code=status.HTTP_201_CREATED)
    async def generate_artifact(values: ArtifactGenerateInput) -> dict[str, Any]:
        try:
            return s.artifact_service.create_text_result(
                name=values.name,
                text=values.content,
                kind=values.kind,
                mime_type=values.mime_type,
                conversation_id=values.conversation_id,
                task_id=values.task_id,
                project_id=values.project_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/artifacts/{artifact_id}")
    async def get_artifact(artifact_id: str) -> dict[str, Any]:
        item = s.artifact_service.get(artifact_id)
        if not item:
            raise HTTPException(status_code=404, detail="Artifact niet gevonden.")
        return item

    @router.get("/artifacts/{artifact_id}/preview")
    async def preview_artifact(artifact_id: str) -> dict[str, Any]:
        try:
            return s.artifact_service.preview(artifact_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Artifact niet gevonden.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/artifacts/{artifact_id}/download")
    async def download_artifact(artifact_id: str) -> FileResponse:
        try:
            item, _data = s.artifact_service.read_bytes(artifact_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Artifact niet gevonden.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (FileNotFoundError, RuntimeError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(
            path=item["storage_path"],
            filename=item["name"],
            media_type=item["mime_type"],
        )

    @router.get("/artifacts/{artifact_id}/verify")
    async def verify_artifact(artifact_id: str) -> dict[str, Any]:
        try:
            return s.artifact_service.verify_ready(artifact_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Artifact niet gevonden.") from exc

    @router.delete("/artifacts/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_artifact(artifact_id: str) -> Response:
        if not s.artifact_service.soft_delete(artifact_id):
            raise HTTPException(status_code=404, detail="Artifact niet gevonden.")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/approvals")
    async def list_approvals(task_id: str | None = None, conversation_id: str | None = None) -> list[dict[str, Any]]:
        return s.approval_service.list_pending(task_id=task_id, conversation_id=conversation_id)

    @router.get("/approvals/{request_id}")
    async def get_approval(request_id: str) -> dict[str, Any]:
        item = s.approval_service.get(request_id)
        if not item:
            raise HTTPException(status_code=404, detail="Aanvraag niet gevonden.")
        return item

    @router.post("/approvals/{request_id}/decide")
    async def decide_approval(request_id: str, values: ApprovalDecisionInput) -> dict[str, Any]:
        try:
            settings = s.database.get_settings()
            decided = s.approval_service.decide(
                request_id,
                approve=values.approve,
                note=values.note,
                response_payload=values.response_payload,
                current_permissions={
                    "file_write_policy": settings.get("file_write_policy"),
                    "network_policy": settings.get("network_policy"),
                    "file_read_policy": settings.get("file_read_policy"),
                },
            )
            resume = ctx.get("resume_after_approval")
            if resume and decided.get("status") == "approved" and decided.get("task_id"):
                try:
                    resume(str(decided["task_id"]), decided)
                    decided = {**decided, "resume_ok": True}
                except Exception as resume_exc:
                    # Approval is persisted, but do not claim the task resumed.
                    decided = {
                        **decided,
                        "resume_ok": False,
                        "resume_error": str(resume_exc),
                    }
                    try:
                        s.database.add_task_event(
                            str(decided["task_id"]),
                            "error",
                            f"Goedkeuring opgeslagen, hervatten mislukt: {resume_exc}",
                        )
                    except Exception:
                        pass
            elif decided.get("status") == "rejected" and decided.get("task_id"):
                try:
                    s.database.add_task_event(str(decided["task_id"]), "warning", "Goedkeuring afgewezen; taak hervat niet blind.")
                except Exception:
                    pass
            return decided
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Aanvraag niet gevonden.") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/inbox")
    async def list_inbox(status_filter: str | None = Query(default=None, alias="status"), kind: str | None = None) -> list[dict[str, Any]]:
        return s.inbox_service.list(status=status_filter, kind=kind)

    @router.post("/inbox/{item_id}/read")
    async def read_inbox(item_id: str) -> dict[str, Any]:
        item = s.inbox_service.mark_read(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Inbox-item niet gevonden.")
        return item

    @router.post("/inbox/{item_id}/archive")
    async def archive_inbox(item_id: str) -> dict[str, Any]:
        item = s.inbox_service.archive(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Inbox-item niet gevonden.")
        return item

    @router.post("/tasks/{task_id}/schedule")
    async def schedule_task(task_id: str, values: ScheduleInput) -> dict[str, Any]:
        if not s.database.get_task(task_id):
            raise HTTPException(status_code=404, detail="Taak niet gevonden.")
        from schedules import preview_occurrences

        try:
            preview = preview_occurrences(
                frequency=values.frequency,
                timezone=values.timezone,
                run_at=values.run_at,
                time_of_day=values.time_of_day,
                weekday=values.weekday,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if values.preview_only:
            return {"preview": preview, "note": "Lokale planning voert alleen uit terwijl de HADES-backend draait."}
        try:
            saved = s.schedule_service.attach_schedule(
                task_id,
                frequency=values.frequency,
                timezone=values.timezone,
                run_at=values.run_at,
                time_of_day=values.time_of_day,
                weekday=values.weekday,
                enabled=values.enabled,
                catch_up=values.catch_up,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        saved["note"] = "Lokale planning voert alleen uit terwijl de HADES-backend draait. Een schema is geen algemene goedkeuring voor side effects."
        return saved

    @router.post("/schedules/{schedule_id}/pause")
    async def pause_schedule(schedule_id: str) -> dict[str, Any]:
        try:
            return s.schedule_service.pause(schedule_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Schema niet gevonden.") from exc

    @router.post("/schedules/{schedule_id}/resume")
    async def resume_schedule(schedule_id: str) -> dict[str, Any]:
        try:
            return s.schedule_service.resume(schedule_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Schema niet gevonden.") from exc

    @router.post("/schedules/{schedule_id}/disable")
    async def disable_schedule(schedule_id: str) -> dict[str, Any]:
        try:
            return s.schedule_service.disable(schedule_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Schema niet gevonden.") from exc

    @router.get("/schedules/{schedule_id}")
    async def get_schedule(schedule_id: str) -> dict[str, Any]:
        item = s.platform_db.get_task_schedule(schedule_id)
        if not item:
            raise HTTPException(status_code=404, detail="Schema niet gevonden.")
        return item

    @router.post("/search")
    async def global_search(values: SearchInput) -> dict[str, Any]:
        return s.search_service.search(
            values.query,
            limit_per_type=values.limit_per_type,
            project_id=values.project_id,
        )

    @router.get("/memory/proposals")
    async def memory_proposals() -> list[dict[str, Any]]:
        return s.database.list_memory_proposals("pending")

    @router.post("/memory/proposals/scan")
    async def memory_proposals_scan() -> dict[str, Any]:
        from memory_sleep_scan import scan_memory_candidates

        created = scan_memory_candidates(s.database)
        return {"created": len(created), "proposals": created, "auto_written": False}

    @router.post("/memory/proposals/{proposal_id}/decide")
    async def decide_proposal(proposal_id: str, values: MemoryProposalDecision) -> dict[str, Any]:
        try:
            return s.database.decide_memory_proposal(proposal_id, action=values.action, edited=values.edited or None)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Voorstel niet gevonden.") from exc

    @router.post("/memory/forget")
    async def forget(values: ForgetInput) -> dict[str, Any]:
        preview = s.database.preview_forget_scope(conversation_id=values.conversation_id, memory_id=values.memory_id)
        if values.preview_only:
            return {"preview": preview, "applied": False}
        forgotten: dict[str, Any] = {"preview": preview, "applied": True, "actions": []}
        if values.memory_id:
            try:
                s.database.forget_memory(values.memory_id)
                forgotten["actions"].append({"memory": values.memory_id, "status": "forgotten"})
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="Memory niet gevonden.") from exc
        if values.conversation_id and values.include_derived:
            uri = f"conversation:{values.conversation_id}"
            s.platform_db.mark_knowledge_forgotten(uri)
            forgotten["actions"].append({"knowledge_uri": uri, "status": "forgotten"})
            deleted = s.database.delete_conversation(values.conversation_id)
            if not deleted:
                forgotten["actions"].append(
                    {"conversation": values.conversation_id, "status": "not_found", "ok": False}
                )
                forgotten["ok"] = False
                forgotten["error"] = "conversation_not_deleted"
            else:
                forgotten["actions"].append({"conversation": values.conversation_id, "status": "deleted"})
        return forgotten
    @router.post("/conversations/{conversation_id}/branch")
    async def branch_conversation(conversation_id: str, values: BranchInput) -> dict[str, Any]:
        try:
            branch = s.database.create_branch(conversation_id, values.fork_message_id, title=values.title)
            # Keep fork message active; deactivate later alternatives on previous line.
            s.database.deactivate_messages_after(conversation_id, values.fork_message_id)
            # Re-activate the fork message as the branch root remains part of context.
            with s.database.connection() as db:
                db.execute("UPDATE messages SET is_active=1, branch_id=? WHERE id=?", (branch["id"], values.fork_message_id))
            return branch
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Gesprek of bericht niet gevonden.") from exc

    @router.get("/conversations/{conversation_id}/branches")
    async def conversation_branches(conversation_id: str) -> list[dict[str, Any]]:
        return s.database.list_branches(conversation_id)

    @router.post("/conversations/{conversation_id}/branches/{branch_id}/activate")
    async def activate_conversation_branch(conversation_id: str, branch_id: str) -> dict[str, Any]:
        if not s.database.get_conversation(conversation_id):
            raise HTTPException(status_code=404, detail="Gesprek niet gevonden.")
        try:
            return s.database.activate_branch(conversation_id, branch_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Vertakking niet gevonden.") from exc

    @router.put("/conversations/{conversation_id}/draft")
    async def save_draft(conversation_id: str, values: DraftInput) -> dict[str, Any]:
        if not s.database.get_conversation(conversation_id):
            raise HTTPException(status_code=404, detail="Gesprek niet gevonden.")
        return s.database.save_draft(conversation_id, values.content, values.attachment_ids)

    @router.get("/conversations/{conversation_id}/draft")
    async def get_draft(conversation_id: str) -> dict[str, Any]:
        draft = s.database.get_draft(conversation_id)
        return draft or {"conversation_id": conversation_id, "content": "", "attachment_ids": []}

    @router.post("/conversations/{conversation_id}/attachments")
    async def upload_chat_attachment(
        conversation_id: str,
        file: UploadFile = File(...),
    ) -> dict[str, Any]:
        if not s.database.get_conversation(conversation_id):
            raise HTTPException(status_code=404, detail="Gesprek niet gevonden.")
        data = await file.read()
        max_bytes = 20 * 1024 * 1024
        if len(data) > max_bytes:
            raise HTTPException(status_code=400, detail="Bijlage is groter dan 20 MB.")
        filename = Path(file.filename or "upload.bin").name
        try:
            artifact = s.artifact_service.create(
                name=filename,
                kind="attachment",
                data=data,
                mime_type=file.content_type,
                conversation_id=conversation_id,
                status="ready",
                verify_format=False,
                metadata={"chat_attachment": True},
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "artifact": artifact,
            "filename": filename,
            "size_bytes": len(data),
            "extract_status": "pending",
        }

    @router.post("/terminal/run")
    async def terminal_run(values: TerminalRunInput) -> dict[str, Any]:
        from terminal_tool import PolicyTerminalService, TerminalPolicyError

        settings = s.database.get_settings()
        write_policy = str(settings.get("file_write_policy", "ask"))
        if write_policy == "block":
            raise HTTPException(status_code=403, detail="file_write_policy=block blokkeert terminal-uitvoer (transcript).")
        if write_policy == "ask" and not values.approved:
            raise HTTPException(status_code=428, detail="Expliciete approval vereist voor terminal-run.")
        enforce_subprocess_policy(values.approved_subprocess, "terminal subprocess")
        data_root = Path(s.database.storage_info()["path"]).expanduser().resolve().parent
        service = PolicyTerminalService(s.artifact_service, data_root)
        try:
            return service.run(
                values.argv,
                cwd=values.cwd,
                timeout_seconds=values.timeout_seconds,
                settings=settings,
                conversation_id=values.conversation_id,
                task_id=values.task_id,
            )
        except TerminalPolicyError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/practice/scenarios")
    async def practice_scenarios() -> dict[str, Any]:
        from practice_api import list_scenarios

        return {"scenarios": list_scenarios()}

    @router.post("/practice/scenarios/{scenario_id}/run")
    async def practice_run(scenario_id: str) -> dict[str, Any]:
        from practice_api import run_scenario

        enabled = {item["id"] for item in s.platform_db.list_agents() if item.get("enabled")}
        try:
            return run_scenario(scenario_id, enabled_agents=enabled or None)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/practice/run-all")
    async def practice_run_all() -> dict[str, Any]:
        from practice_api import run_all

        enabled = {item["id"] for item in s.platform_db.list_agents() if item.get("enabled")}
        return run_all(enabled_agents=enabled or None)

    @router.get("/onboarding")
    async def onboarding_status() -> dict[str, Any]:
        settings = s.database.get_settings()
        completed = str(settings.get("onboarding_completed_at") or "").strip()
        health_connected = False
        models_count = 0
        try:
            from lm_studio import LmStudioClient, LmStudioError

            client = LmStudioClient(
                str(settings.get("lm_studio_base_url") or "http://127.0.0.1:1234/v1"),
                str(settings.get("lm_studio_api_key") or "lm-studio"),
                float(settings.get("request_timeout_seconds") or 30),
            )
            payload = await client.models()
            models_count = len(payload.get("data") or payload.get("models") or [])
            health_connected = True
        except Exception:
            health_connected = False
        active = s.database.active_profile().get("model_id")
        conversations = s.database.list_conversations() if hasattr(s.database, "list_conversations") else []
        first_chat_done = bool(completed) or any(
            True for _ in (conversations or [])[:1]
        )
        return {
            "completed": bool(completed),
            "completed_at": completed or None,
            "steps": [
                {"id": "chat", "title": "Chat is HADES — praat met je lokale model", "done": first_chat_done or bool(active)},
                {"id": "pins", "title": "@ en pins brengen projectkennis/context", "done": bool(completed)},
                {"id": "advanced", "title": "Geavanceerd bevat specialistconsoles", "done": bool(completed)},
            ],
            "active_model": active,
            "models_available": models_count,
            "lm_connected": health_connected,
            "suggested_first_prompt": "/help",
        }

    @router.post("/onboarding/complete")
    async def onboarding_complete(values: OnboardingCompleteInput) -> dict[str, Any]:
        from platform_db import utc_now

        now = utc_now()
        s.database.update_settings({"onboarding_completed_at": now})
        return {"completed": True, "completed_at": now, "step": values.step}

    def _resolve_workspace_root(workspace_id: str | None, path: str | None) -> Path:
        if workspace_id:
            workspaces = s.platform_db.list_workspaces()
            match = next((item for item in workspaces if item.get("id") == workspace_id), None)
            if not match:
                raise HTTPException(status_code=404, detail="Workspace niet gevonden.")
            return Path(str(match.get("path")))
        if path:
            return Path(path)
        raise HTTPException(status_code=400, detail="Geef workspace_id of path op.")

    def _symbol_cache_path(root: Path) -> Path:
        data_root = Path(s.get("data_root") or Path(__file__).resolve().parents[1] / "data")
        # Process-stable digest: Python's hash() is randomized per process and must
        # not identify persistent on-disk workspace symbol caches.
        digest = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:24]
        cache_dir = data_root / "symbol_index"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"{digest}.json"

    @router.post("/files/symbols")
    async def file_symbols(values: SymbolSearchInput) -> dict[str, Any]:
        from workspace_symbols import index_workspace_symbols

        root = _resolve_workspace_root(values.workspace_id, values.path)
        try:
            return index_workspace_symbols(
                root,
                query=values.query,
                limit=values.limit,
                refresh=values.refresh,
                use_cache=values.use_cache,
                cache_path=_symbol_cache_path(root),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/files/symbols/refresh")
    async def file_symbols_refresh(values: SymbolRefreshInput) -> dict[str, Any]:
        from workspace_symbols import refresh_workspace_index

        root = _resolve_workspace_root(values.workspace_id, values.path)
        try:
            return refresh_workspace_index(
                root,
                cache_path=_symbol_cache_path(root),
                max_files=values.max_files,
                force=values.force,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/files/tree")
    async def files_tree(values: WorkspaceTreeInput) -> dict[str, Any]:
        from workspace_symbols import list_workspace_tree

        root = _resolve_workspace_root(values.workspace_id, values.path)
        try:
            return list_workspace_tree(
                root,
                relative=values.relative,
                query=values.query,
                max_entries=values.max_entries,
                cache_path=_symbol_cache_path(root),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (NotADirectoryError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/files/preview")
    async def files_preview(values: WorkspacePreviewInput) -> dict[str, Any]:
        from workspace_symbols import preview_workspace_file

        root = _resolve_workspace_root(values.workspace_id, values.path)
        try:
            return preview_workspace_file(
                root,
                relative=values.relative,
                max_chars=values.max_chars,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/files/open-external")
    async def files_open_external(values: WorkspaceOpenInput) -> dict[str, Any]:
        from workspace_open import open_in_external_editor

        root = _resolve_workspace_root(values.workspace_id, values.path)
        try:
            result = open_in_external_editor(root, relative=values.relative)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not result.get("opened"):
            raise HTTPException(status_code=503, detail=str(result.get("message") or result.get("error") or "Editor niet beschikbaar"))
        return result

    @router.post("/workspace/git/status")
    async def workspace_git_status_route(values: WorkspaceGitStatusInput) -> dict[str, Any]:
        from workspace_git import workspace_git_status

        root = _resolve_workspace_root(values.workspace_id, values.path)
        try:
            return workspace_git_status(root)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/workspace/git/commit")
    async def workspace_git_commit_route(values: WorkspaceGitCommitInput) -> dict[str, Any]:
        from workspace_git import workspace_git_commit

        if not values.approved:
            raise HTTPException(status_code=403, detail="Commit vereist expliciete goedkeuring.")
        root = _resolve_workspace_root(values.workspace_id, values.path)
        try:
            return workspace_git_commit(root, message=values.message, approved=True)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/code/definition")
    async def code_definition(values: LspQueryInput) -> dict[str, Any]:
        from lsp_light import find_definition

        root = _resolve_workspace_root(values.workspace_id, values.path)
        try:
            return find_definition(root, values.symbol, limit=values.limit)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/code/references")
    async def code_references(values: LspQueryInput) -> dict[str, Any]:
        from lsp_light import find_references

        root = _resolve_workspace_root(values.workspace_id, values.path)
        try:
            return find_references(root, values.symbol, limit=values.limit)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/code/outline")
    async def code_outline(values: SymbolSearchInput) -> dict[str, Any]:
        from lsp_light import outline_file

        if not values.path:
            raise HTTPException(status_code=400, detail="Geef path op voor outline.")
        try:
            return outline_file(Path(values.path))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/voice/to-task")
    async def voice_to_task(values: VoiceTaskInput) -> dict[str, Any]:
        from voice_tasks import transcript_to_task

        try:
            proposal = transcript_to_task(values.transcript, default_agent=values.agent)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not values.create:
            return {"created": False, "proposal": proposal}
        task = s.database.create_task(
            title=proposal["title"],
            prompt=proposal["prompt"],
            agent=proposal["agent"],
            priority=proposal["priority"],
            model_id=None,
        )
        started = False
        if values.auto_start:
            schedule = ctx.get("schedule_task_run")
            if callable(schedule):
                schedule(str(task["id"]))
                started = True
            else:
                s.database.update_task(task["id"], status="queued")
            refreshed = s.database.get_task(str(task["id"]))
            if refreshed:
                task = refreshed
        return {"created": True, "started": started, "proposal": proposal, "task": task}

    @router.post("/debug/diagnose")
    async def debug_diagnose(values: DebugDiagnoseInput) -> dict[str, Any]:
        from debug_agent import diagnose_failure

        try:
            return diagnose_failure(
                logs=values.logs,
                failing_test=values.failing_test,
                context_files=values.context_files,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/release/confidence")
    async def release_confidence() -> dict[str, Any]:
        from release_confidence import inventory_gates

        repo = Path(__file__).resolve().parents[1]
        return inventory_gates(repo)

    @router.post("/release/confidence/smoke")
    async def release_confidence_smoke(values: ReleaseConfidenceInput) -> dict[str, Any]:
        from release_confidence import inventory_gates, run_focused_unittest

        repo = Path(__file__).resolve().parents[1]
        report = inventory_gates(repo)
        if values.run_smoke:
            enforce_subprocess_policy(values.approved_subprocess, "release smoke unittest")
            smoke = run_focused_unittest(repo, module=values.module)
            report["smoke"] = smoke
            # Surface smoke failures in top-level what_broke for UI clarity.
            broke = list(report.get("what_broke") or [])
            for item in smoke.get("what_broke") or []:
                broke.append(item if isinstance(item, dict) else {"kind": "smoke", "label": str(item)})
            if smoke.get("ok") is False and not any(i.get("kind") == "smoke" for i in broke if isinstance(i, dict)):
                broke.append({"kind": "smoke", "label": f"Smoke mislukt (exit {smoke.get('exit_code')})"})
            report["what_broke"] = broke
            if smoke.get("ok") is False and report.get("overall") == "ok":
                report["overall"] = "error"
            elif smoke.get("ok") is False and report.get("overall") == "warn":
                report["overall"] = "error"
        return report

    @router.post("/tools/cards")
    async def tool_cards(values: ToolCardsInput) -> dict[str, Any]:
        from tool_result_cards import build_tool_result_cards

        cards = build_tool_result_cards(values.observations)
        return {"cards": cards, "count": len(cards)}

    @router.get("/mcp/catalog")
    async def mcp_catalog(mcp_only: bool = Query(default=True)) -> dict[str, Any]:
        """List MCP-capable plugins as first-class tool rows with health."""
        plugins = s.platform_db.list_plugins()
        rows: list[dict[str, Any]] = []
        for plugin in plugins:
            tools = plugin.get("tools") or []
            if isinstance(tools, str):
                try:
                    tools = json.loads(tools)
                except json.JSONDecodeError:
                    tools = []
            runtime = str(plugin.get("runtime_type") or plugin.get("runtime") or "")
            labels = plugin.get("labels") or []
            permissions_list = plugin.get("permissions") or []
            is_mcp = "mcp" in runtime.lower() or any(
                "mcp" in str(tool.get("name") or "").lower() for tool in tools if isinstance(tool, dict)
            )
            # Include bridges that declare mcp in metadata/tags too.
            meta = plugin.get("metadata") if isinstance(plugin.get("metadata"), dict) else {}
            tags = plugin.get("tags") or []
            if not is_mcp and ("mcp" in str(meta).lower() or any("mcp" in str(t).lower() for t in tags)):
                is_mcp = True
            if not is_mcp and any("mcp" in str(label).lower() for label in labels):
                is_mcp = True
            if mcp_only and not is_mcp:
                continue
            if not tools:
                continue
            declared = [str(p) for p in permissions_list] if isinstance(permissions_list, list) else []
            permission_map = {
                "network": bool(plugin.get("requires_network")) or any("network" in p.lower() for p in declared),
                "file_read": bool(plugin.get("requires_file_read"))
                or any(token in " ".join(declared).lower() for token in ("filesystem", "file_read", "read")),
                "file_write": bool(plugin.get("requires_file_write"))
                or any(token in " ".join(declared).lower() for token in ("file_write", "write")),
                "subprocess": any("subprocess" in p.lower() for p in declared),
                "declared": declared,
            }
            ready = str(plugin.get("status") or "").lower() == "ready"
            health = plugin.get("health") or plugin.get("status") or "unknown"
            for tool in tools if isinstance(tools, list) else []:
                if not isinstance(tool, dict):
                    continue
                tool_is_mcp = is_mcp or "mcp" in str(tool.get("name") or "").lower()
                if mcp_only and not tool_is_mcp and not is_mcp:
                    continue
                rows.append(
                    {
                        "plugin_id": plugin.get("id"),
                        "plugin_name": plugin.get("name"),
                        "tool_name": tool.get("name"),
                        "description": tool.get("description") or "",
                        "enabled": bool(plugin.get("enabled")),
                        "ready": ready,
                        "health": health,
                        "permissions": permission_map,
                        "mcp": tool_is_mcp,
                        "autonomous": bool(plugin.get("autonomous")),
                    }
                )
        return {
            "items": rows,
            "count": len(rows),
            "plugins": len({row["plugin_id"] for row in rows}),
            "mcp_only": mcp_only,
            "max_connections": _mcp_max_connections(),
            "note": "MCP-tools blijven achter Permission Engine + Ready-status; catalogus is geen goedkeuring.",
        }

    @router.get("/plugins/marketplace")
    async def plugin_marketplace() -> dict[str, Any]:
        from plugin_marketplace import scan_local_marketplace

        repo = Path(__file__).resolve().parents[1]
        installed = s.platform_db.list_plugins()
        return scan_local_marketplace(repo / "plugins", installed=installed)

    @router.post("/plugins/marketplace/{plugin_id}/install")
    async def plugin_marketplace_install(plugin_id: str, install_dependencies: bool = True) -> dict[str, Any]:
        from plugin_marketplace import scan_local_marketplace

        ensure = s.get("ensure_platform_services")
        if callable(ensure):
            ensure()
        plugin_manager = s.get("plugin_manager")
        if plugin_manager is None:
            raise HTTPException(status_code=503, detail="PluginManager niet beschikbaar.")
        repo = Path(__file__).resolve().parents[1]
        catalog = scan_local_marketplace(repo / "plugins", installed=s.platform_db.list_plugins())
        match = next((item for item in catalog["items"] if item["id"] == plugin_id), None)
        if not match:
            raise HTTPException(status_code=404, detail="Plugin niet gevonden in lokale marketplace.")
        source = Path(str(match["source_path"]))
        if not source.is_dir():
            raise HTTPException(status_code=404, detail="Marketplace-bronmap ontbreekt.")
        try:
            result = await asyncio.to_thread(
                plugin_manager.import_local_folder,
                source,
                install_dependencies,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        plugin = result.get("plugin") or {}
        health = plugin.get("health") or plugin.get("status") or "unknown"
        ready = str(plugin.get("status") or "").lower() == "ready"
        return {
            **result,
            "marketplace": {
                "id": plugin_id,
                "installed": True,
                "ready": ready,
                "health": health,
                "health_proof": ready or str(health).lower() in {"healthy", "ok", "ready"},
                "note": (
                    "Installatie voltooid met Ready-status."
                    if ready
                    else "Geïnstalleerd maar niet Ready — gebruik Repair dependencies of review permissions."
                ),
            },
        }

    @router.get("/host/capabilities")
    async def host_capabilities() -> dict[str, Any]:
        from host_capability import check_host_capabilities

        data_root = Path(s.get("data_root") or Path(__file__).resolve().parents[1] / "data")
        return check_host_capabilities(workspace=data_root)

    @router.post("/host/verify")
    async def host_verify() -> dict[str, Any]:
        """Run host verify simulation (Windows bat parity; labeled simulated on non-Windows)."""
        from host_verify_sim import run_host_verify_simulation

        data_root = Path(s.get("data_root") or Path(__file__).resolve().parents[1] / "data")
        return run_host_verify_simulation(workspace=data_root)

    @router.post("/project/map")
    async def project_map(values: dict[str, Any]) -> dict[str, Any]:
        from project_map import build_project_map

        root = Path(str(values.get("path") or "")).expanduser()
        if not root.is_dir():
            raise HTTPException(status_code=400, detail="path must be an existing directory")
        return build_project_map(root, refresh_symbols=bool(values.get("refresh_symbols", True)))

    @router.post("/project/impact")
    async def project_impact(values: dict[str, Any]) -> dict[str, Any]:
        from project_map import find_change_impact

        root = Path(str(values.get("path") or "")).expanduser()
        if not root.is_dir():
            raise HTTPException(status_code=400, detail="path must be an existing directory")
        return find_change_impact(
            root,
            symbol=values.get("symbol"),
            path=values.get("file"),
            limit=int(values.get("limit") or 40),
        )

    @router.post("/project/analyze-file")
    async def project_analyze_file(values: dict[str, Any]) -> dict[str, Any]:
        from code_intel import analyze_file

        root = Path(str(values.get("path") or "")).expanduser()
        rel = str(values.get("file") or "")
        if not root.is_dir() or not rel:
            raise HTTPException(status_code=400, detail="path and file required")
        try:
            return analyze_file(root, rel)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/preview/plan")
    async def preview_plan(values: dict[str, Any]) -> dict[str, Any]:
        from preview_runtime import PreviewManager

        root = Path(str(values.get("path") or ".")).expanduser()
        return PreviewManager().plan_preview(root, kind=str(values.get("kind") or "auto"))

    @router.post("/preview/start")
    async def preview_start(values: dict[str, Any]) -> dict[str, Any]:
        from preview_runtime import get_preview_manager

        approved = bool(values.get("approved_subprocess"))
        enforce_subprocess_policy(approved, "preview starten")
        root = Path(str(values.get("path") or ".")).expanduser()
        run_id = str(values.get("run_id") or values.get("coding_run_id") or "manual")
        return get_preview_manager().start_preview(run_id, root, kind=str(values.get("kind") or "auto"))

    @router.post("/preview/stop")
    async def preview_stop(values: dict[str, Any]) -> dict[str, Any]:
        from preview_runtime import get_preview_manager

        run_id = str(values.get("run_id") or values.get("coding_run_id") or "")
        if not run_id:
            raise HTTPException(status_code=400, detail="run_id required")
        return get_preview_manager().stop_preview(run_id)

    @router.get("/preview/{run_id}/status")
    async def preview_status(run_id: str) -> dict[str, Any]:
        from preview_runtime import get_preview_manager

        return get_preview_manager().status(run_id)

    @router.get("/browser/capabilities")
    async def browser_capabilities() -> dict[str, Any]:
        from preview_runtime import BrowserAdapter

        adapter = BrowserAdapter(plugin_manager=s.get("plugin_manager"))
        return adapter.capabilities()

    @router.post("/browser/open")
    async def browser_open(values: dict[str, Any]) -> dict[str, Any]:
        from preview_runtime import BrowserAdapter

        adapter = BrowserAdapter(plugin_manager=s.get("plugin_manager"))
        return adapter.open_page(str(values.get("url") or ""))

    @router.post("/browser/screenshot")
    async def browser_screenshot(values: dict[str, Any]) -> dict[str, Any]:
        from preview_runtime import BrowserAdapter

        adapter = BrowserAdapter(plugin_manager=s.get("plugin_manager"))
        return adapter.screenshot(str(values.get("url") or ""), out_path=values.get("out_path"))

    @router.post("/browser/flow")
    async def browser_flow(values: dict[str, Any]) -> dict[str, Any]:
        from preview_runtime import BrowserAdapter

        adapter = BrowserAdapter(plugin_manager=s.get("plugin_manager"))
        return adapter.run_user_flow(
            url=str(values.get("url") or ""),
            steps=list(values.get("steps") or []),
            out_dir=values.get("out_dir"),
            change_hash=values.get("change_hash"),
            run_id=values.get("run_id"),
            work_root=values.get("work_root"),
            config=values.get("config"),
        )

    @router.get("/compute/local/capabilities")
    async def compute_local_capabilities() -> dict[str, Any]:
        from compute_fabric import get_local_executor

        return get_local_executor().capabilities()

    @router.post("/compute/local/submit")
    async def compute_local_submit(values: dict[str, Any]) -> dict[str, Any]:
        from compute_fabric import get_local_executor

        return get_local_executor().submit(dict(values or {}))

    @router.get("/compute/local/jobs/{job_id}")
    async def compute_local_status(job_id: str) -> dict[str, Any]:
        from compute_fabric import get_local_executor

        return get_local_executor().status(job_id)

    @router.post("/compute/local/jobs/{job_id}/cancel")
    async def compute_local_cancel(job_id: str) -> dict[str, Any]:
        from compute_fabric import get_local_executor

        return get_local_executor().cancel(job_id)

    @router.post("/project/retrieval-compare")
    async def project_retrieval_compare(values: dict[str, Any]) -> dict[str, Any]:
        from retrieval_compare import compare_retrieval_methods

        root = Path(str(values.get("path") or "")).expanduser()
        if not root.is_dir():
            raise HTTPException(status_code=400, detail="path must be an existing directory")
        return compare_retrieval_methods(
            root,
            query=str(values.get("query") or ""),
            symbol=values.get("symbol"),
            limit=int(values.get("limit") or 20),
        )

    @router.post("/claims")
    async def claims_add(values: dict[str, Any]) -> dict[str, Any]:
        from claim_register import default_claim_register

        cid = default_claim_register.add_claim(
            text=str(values.get("text") or ""),
            provenance=str(values.get("provenance") or "user"),
            verification_status=str(values.get("verification_status") or "unverified"),
            source_kind=str(values.get("source_kind") or "primary"),
            task_id=values.get("task_id"),
            supports=list(values.get("supports") or []),
            contradicts=list(values.get("contradicts") or []),
            valid_until=values.get("valid_until"),
            valid_from=values.get("valid_from"),
        )
        return {"id": cid, "claim": default_claim_register.get(cid)}

    @router.get("/claims")
    async def claims_list(task_id: str | None = None) -> dict[str, Any]:
        from claim_register import default_claim_register

        items = default_claim_register.list_for_task(task_id) if task_id else default_claim_register.list_all()
        return {"claims": items, "count": len(items)}

    @router.post("/claims/{claim_id}/evidence")
    async def claims_attach_evidence(claim_id: str, values: dict[str, Any]) -> dict[str, Any]:
        from claim_register import default_claim_register

        claim = default_claim_register.attach_evidence(
            claim_id,
            evidence_id=str(values.get("evidence_id") or ""),
            relation=str(values.get("relation") or "supports"),
            independent=values.get("independent"),
            note=str(values.get("note") or ""),
        )
        return {"claim": claim}

    @router.post("/claims/{claim_id}/reassess")
    async def claims_reassess(claim_id: str) -> dict[str, Any]:
        from claim_register import default_claim_register

        return {"claim": default_claim_register.reassess(claim_id)}

    @router.get("/lifecycle/owners")
    async def lifecycle_owners() -> dict[str, Any]:
        """A12 ownership map — pure typed contract; no SQLite I/O on this path."""
        from run_lifecycle import ownership_snapshot

        # Keep off-event-loop habit for any future expansion; snapshot is CPU-cheap.
        return await asyncio.to_thread(ownership_snapshot)

    # --- WP1 Project continuity -------------------------------------------------
    def _project_service():
        from project_continuity import ProjectContinuityService

        existing = ctx.get("project_continuity")
        if existing is not None:
            return existing
        svc = ProjectContinuityService(s.database)
        ctx["project_continuity"] = svc
        return svc

    from coding_build_routes import register_coding_build_routes

    register_coding_build_routes(
        router,
        s=s,
        models={
            "BuildPlanInput": BuildPlanInput,
            "BuildRunInput": BuildRunInput,
            "BuildEdit": BuildEdit,
            "CodingGoalInput": CodingGoalInput,
            "CodingJobStartInput": CodingJobStartInput,
            "CodingJobRedirectInput": CodingJobRedirectInput,
            "BuildApplyInput": BuildApplyInput,
        },
        enforce_subprocess_policy=enforce_subprocess_policy,
        project_service_factory=_project_service,
    )

    @router.get("/projects")
    async def list_projects(status_filter: str | None = Query(default="active", alias="status")) -> dict[str, Any]:
        items = await asyncio.to_thread(_project_service().list_projects, status=status_filter)
        return {"projects": items, "count": len(items)}

    @router.post("/projects", status_code=status.HTTP_201_CREATED)
    async def create_project(values: ProjectCreateInput) -> dict[str, Any]:
        project = await asyncio.to_thread(
            _project_service().create_project,
            values.name,
            description=values.description,
        )
        return {"project": project}

    @router.get("/projects/{project_id}")
    async def get_project(project_id: str) -> dict[str, Any]:
        project = await asyncio.to_thread(_project_service().get_project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project niet gevonden.")
        return {"project": project}

    @router.get("/projects/{project_id}/context")
    async def project_context(project_id: str, include_proposals: bool = False) -> dict[str, Any]:
        try:
            package = await asyncio.to_thread(
                _project_service().context_package,
                project_id,
                include_proposals=include_proposals,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Project niet gevonden.") from exc
        return package

    @router.post("/projects/{project_id}/items", status_code=status.HTTP_201_CREATED)
    async def add_project_item(project_id: str, values: ProjectItemInput) -> dict[str, Any]:
        try:
            item = await asyncio.to_thread(
                _project_service().add_item,
                project_id,
                kind=values.kind,
                title=values.title,
                body=values.body,
                provenance=values.provenance,
                status=values.status,
                scope=values.scope,
                source_message_id=values.source_message_id,
                source_conversation_id=values.source_conversation_id,
                replace_overlapping=values.replace_overlapping,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Project niet gevonden.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"item": item}

    @router.post("/projects/{project_id}/items/{item_id}/correct")
    async def correct_project_item(project_id: str, item_id: str, values: ProjectCorrectInput) -> dict[str, Any]:
        try:
            item = await asyncio.to_thread(
                _project_service().correct_item,
                item_id,
                title=values.title,
                body=values.body,
                status=values.status,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Item niet gevonden.") from exc
        if item.get("project_id") != project_id:
            raise HTTPException(status_code=404, detail="Item hoort niet bij dit project.")
        return {"item": item}

    @router.post("/projects/{project_id}/items/{item_id}/exclude")
    async def exclude_project_item(project_id: str, item_id: str) -> dict[str, Any]:
        try:
            item = await asyncio.to_thread(_project_service().exclude_item, item_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Item niet gevonden.") from exc
        if item.get("project_id") != project_id:
            raise HTTPException(status_code=404, detail="Item hoort niet bij dit project.")
        return {"item": item}

    @router.post("/projects/{project_id}/link-conversation")
    async def link_project_conversation(project_id: str, values: dict[str, Any]) -> dict[str, Any]:
        conversation_id = str(values.get("conversation_id") or "")
        if not conversation_id:
            raise HTTPException(status_code=400, detail="conversation_id vereist")
        try:
            result = await asyncio.to_thread(_project_service().link_conversation, project_id, conversation_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Project niet gevonden.") from exc
        return result

    @router.post("/projects/{project_id}/ingest-working-state")
    async def ingest_working_state(project_id: str, values: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(
                _project_service().ingest_working_state,
                project_id,
                values.get("working_state") if isinstance(values.get("working_state"), dict) else values,
                conversation_id=values.get("conversation_id"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Project niet gevonden.") from exc
        return result

    # --- WP2 result contracts / WP10 artifact summary ---------------------------
    @router.get("/artifacts/{artifact_id}/result-summary")
    async def artifact_result_summary(artifact_id: str) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(s.artifact_service.summarize_result, artifact_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Artifact niet gevonden.") from exc

    @router.post("/result-contracts/evaluate")
    async def evaluate_contract(values: dict[str, Any]) -> dict[str, Any]:
        from result_contracts import evaluate_result_contract

        return await asyncio.to_thread(
            evaluate_result_contract,
            values.get("contract"),
            status=str(values.get("status") or "completed"),
            verification=values.get("verification"),
            step_summary=values.get("step_summary"),
            mission=values.get("mission"),
            artifact_service=s.artifact_service,
            extras=values.get("extras"),
        )

    # --- WP4 research conflicts -------------------------------------------------
    @router.get("/research/conflicts/fixture")
    async def research_conflicts_fixture() -> dict[str, Any]:
        from research_conflicts import fixture_conflicting_research

        return await asyncio.to_thread(fixture_conflicting_research)

    @router.post("/research/conflicts/present")
    async def research_conflicts_present(values: dict[str, Any]) -> dict[str, Any]:
        from research_conflicts import build_conflict_report

        claims = values.get("claims") if isinstance(values.get("claims"), list) else []
        return await asyncio.to_thread(build_conflict_report, claims)

    # --- WP6 tool contracts / effect decisions ----------------------------------
    @router.post("/plugins/tools/contract-test")
    async def plugin_tool_contract_test(values: dict[str, Any]) -> dict[str, Any]:
        from runtime.tool_contracts import run_tool_contract_tests

        tool = values.get("tool") if isinstance(values.get("tool"), dict) else {}
        cases = values.get("cases") if isinstance(values.get("cases"), list) else []
        return await asyncio.to_thread(run_tool_contract_tests, tool, cases=cases)

    @router.get("/effects/{effect_id}/restart-class")
    async def effect_restart_class(effect_id: str) -> dict[str, Any]:
        pm = s.plugin_manager
        if hasattr(pm, "restart_effect_decision"):
            return await asyncio.to_thread(pm.restart_effect_decision, effect_id)
        from runtime.effect_ledger import EffectLedger

        ledger = EffectLedger(Path(s.data_root) / "effect_ledger.db")
        decision = await asyncio.to_thread(ledger.classify_on_restart, effect_id)
        decision["blind_retry_allowed"] = decision.get("class") == "SAFE_TO_RETRY"
        decision["human_review_required"] = decision.get("class") in {
            "REQUIRES_RECONCILIATION",
            "UNKNOWN_EXTERNAL_STATE",
        }
        return decision

    # --- WP9 proactive triggers -------------------------------------------------
    def _proactive_service():
        from proactive_triggers import ProactiveTriggerService

        existing = ctx.get("proactive_triggers")
        if existing is not None:
            return existing
        svc = ProactiveTriggerService(s.database)
        ctx["proactive_triggers"] = svc
        return svc

    @router.get("/proactive/triggers")
    async def list_proactive_triggers() -> dict[str, Any]:
        items = await asyncio.to_thread(_proactive_service().list_triggers)
        return {"triggers": items, "count": len(items)}

    @router.post("/proactive/triggers", status_code=status.HTTP_201_CREATED)
    async def create_proactive_trigger(values: ProactiveTriggerInput) -> dict[str, Any]:
        try:
            item = await asyncio.to_thread(
                _proactive_service().register_trigger,
                kind=values.kind,
                title=values.title,
                scope=values.scope,
                permission=values.permission,
                frequency_seconds=values.frequency_seconds,
                project_id=values.project_id,
                enabled=values.enabled,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"trigger": item}

    @router.post("/proactive/triggers/{trigger_id}/disable")
    async def disable_proactive_trigger(trigger_id: str) -> dict[str, Any]:
        try:
            item = await asyncio.to_thread(_proactive_service().set_enabled, trigger_id, False)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trigger niet gevonden.") from exc
        return {"trigger": item}

    @router.post("/proactive/triggers/{trigger_id}/consider")
    async def consider_proactive_event(trigger_id: str, values: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(
                _proactive_service().consider_event,
                trigger_id,
                reason=str(values.get("reason") or ""),
                payload=values.get("payload") if isinstance(values.get("payload"), dict) else {},
                authorize_mutate=bool(values.get("authorize_mutate")),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trigger niet gevonden.") from exc
        return result

    @router.get("/proactive/suggestions")
    async def list_proactive_suggestions(status_filter: str | None = Query(default="open", alias="status")) -> dict[str, Any]:
        items = await asyncio.to_thread(_proactive_service().list_suggestions, status=status_filter)
        return {"suggestions": items, "count": len(items)}

    # --- WP3 input invalidation helper ----------------------------------------
    @router.post("/work/invalidate-by-input")
    async def invalidate_by_input(values: dict[str, Any]) -> dict[str, Any]:
        from reasoning.plan_scheduler import choose_recovery_strategy, steps_invalidated_by_input_change

        steps = values.get("steps") if isinstance(values.get("steps"), list) else []
        changed = set(values.get("changed_input_refs") or [])
        completed = set(values.get("completed_ids") or [])
        plan = await asyncio.to_thread(
            steps_invalidated_by_input_change,
            steps,
            completed_ids=completed,
            changed_input_refs=changed,
        )
        recovery = choose_recovery_strategy(
            cause=str(values.get("cause") or "input_changed"),
            attempts=int(values.get("attempts") or 0),
            max_retries=int(values.get("max_retries") or 2),
            alternate_tool_available=bool(values.get("alternate_tool_available")),
            params_adjustable=bool(values.get("params_adjustable")),
            subplan_replaceable=bool(values.get("subplan_replaceable")),
            user_choice_required=bool(values.get("user_choice_required")),
        )
        return {"invalidation": plan, "recovery": recovery}

    # --- WP8 resource awareness -----------------------------------------------
    @router.post("/resources/classify-task")
    async def classify_task_resources(values: dict[str, Any]) -> dict[str, Any]:
        from reasoning.resource_awareness import backpressure_decision, classify_task_complexity

        complexity = classify_task_complexity(
            str(values.get("prompt") or ""),
            has_tools=bool(values.get("has_tools")),
            has_files=bool(values.get("has_files")),
        )
        pressure = backpressure_decision(
            active_inference=int(values.get("active_inference") or 0),
            max_concurrent_inference=int(values.get("max_concurrent_inference") or 1),
            queue_depth=int(values.get("queue_depth") or 0),
            memory_pressure=values.get("memory_pressure"),
        )
        return {"complexity": complexity, "backpressure": pressure}

    return router
