"""FastAPI routes for the Coding Agent control plane."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from Data.modules.coding import CodingControlPlane, CodingError


def raise_coding_error(exc: CodingError) -> None:
    raise HTTPException(status_code=exc.http_status, detail=exc.public_dict()) from exc


class SessionCreate(BaseModel):
    """Canonical request fields are camelCase; snake_case aliases accepted for migration."""

    model_config = ConfigDict(populate_by_name=True)

    goal: str
    mission: str | None = None
    workspaceRoot: str | None = Field(
        default=None,
        validation_alias=AliasChoices("workspaceRoot", "workspace_root"),
    )
    modelId: str | None = Field(
        default=None,
        validation_alias=AliasChoices("modelId", "model_id"),
    )
    conversationId: str | None = Field(
        default=None,
        validation_alias=AliasChoices("conversationId", "conversation_id"),
    )
    title: str | None = None


class TurnRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message: str | None = None
    approvalId: str | None = Field(
        default=None,
        validation_alias=AliasChoices("approvalId", "approval_id"),
    )
    capabilityId: str | None = Field(
        default=None,
        validation_alias=AliasChoices("capabilityId", "capability_id"),
    )


class ApprovalCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sessionId: str = Field(validation_alias=AliasChoices("sessionId", "session_id"))


def build_coding_router(service: CodingControlPlane) -> APIRouter:
    router = APIRouter(tags=["coding"])

    @router.get("/api/coding/status")
    def status() -> dict:
        return service.status()

    @router.get("/api/coding/sessions")
    def list_sessions(limit: int = Query(100, ge=1, le=500)) -> dict:
        sessions = [s.public_dict() for s in service.list_sessions(limit=limit)]
        return {"sessions": sessions}

    @router.post("/api/coding/sessions")
    def create_session(payload: SessionCreate) -> dict:
        try:
            session = service.create_session(
                goal=payload.goal,
                mission=payload.mission,
                workspace_root=payload.workspaceRoot,
                model_id=payload.modelId,
                conversation_id=payload.conversationId,
                title=payload.title,
            )
        except CodingError as exc:
            raise_coding_error(exc)
        return {"session": session.public_dict()}

    @router.get("/api/coding/sessions/{session_id}")
    def get_session(session_id: str) -> dict:
        try:
            return service.session_detail(session_id)
        except CodingError as exc:
            raise_coding_error(exc)

    @router.post("/api/coding/sessions/{session_id}/turn")
    def start_turn(session_id: str, payload: TurnRequest | None = None) -> dict:
        body = payload or TurnRequest()
        try:
            session = service.start_turn(
                session_id,
                message=body.message,
                approval_id=body.approvalId,
                capability_id=body.capabilityId,
            )
        except CodingError as exc:
            raise_coding_error(exc)
        return {"session": session.public_dict()}

    @router.post("/api/coding/sessions/{session_id}/cancel")
    def cancel(session_id: str) -> dict:
        try:
            session = service.cancel(session_id)
        except CodingError as exc:
            raise_coding_error(exc)
        return {"session": session.public_dict()}

    @router.get("/api/coding/sessions/{session_id}/events")
    def events(session_id: str, limit: int = Query(200, ge=1, le=2000)) -> dict:
        try:
            steps = service.store.list_steps(session_id, limit=limit)
        except CodingError as exc:
            raise_coding_error(exc)
        return {"events": [s.public_dict() for s in steps]}

    @router.get("/api/coding/workspace/tree")
    def workspace_tree(
        path: str | None = None,
        recursive: bool = False,
        max_entries: int = Query(200, ge=1, le=2000),
        session_id: str | None = None,
    ) -> dict:
        try:
            return service.workspace_tree(
                path=path,
                recursive=recursive,
                max_entries=max_entries,
                session_id=session_id,
            )
        except CodingError as exc:
            raise_coding_error(exc)

    @router.post("/api/coding/approvals")
    def create_approval(payload: ApprovalCreate) -> dict:
        try:
            return service.request_approval_for_pending(payload.sessionId)
        except CodingError as exc:
            raise_coding_error(exc)

    @router.get("/api/coding/semantic-map")
    def semantic_map(
        workspace_root: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        try:
            return {"map": service.semantic_map(workspace_root=workspace_root, session_id=session_id)}
        except CodingError as exc:
            raise_coding_error(exc)

    class ChangePlanRequest(BaseModel):
        model_config = ConfigDict(populate_by_name=True)
        goal: str
        changes: list[dict[str, Any]]
        invariants: list[str] | None = None
        expected_tests: list[str] | None = Field(
            default=None, validation_alias=AliasChoices("expected_tests", "expectedTests")
        )
        risk: str | None = None

    @router.post("/api/coding/change-plan")
    def create_change_plan(payload: ChangePlanRequest) -> dict:
        try:
            return {
                "plan": service.build_change_plan(
                    goal=payload.goal,
                    changes=payload.changes,
                    invariants=payload.invariants,
                    expected_tests=payload.expected_tests,
                    risk=payload.risk,
                )
            }
        except CodingError as exc:
            raise_coding_error(exc)

    class ApplyPlanRequest(BaseModel):
        model_config = ConfigDict(populate_by_name=True)
        plan: dict[str, Any]
        workspaceRoot: str | None = Field(
            default=None, validation_alias=AliasChoices("workspaceRoot", "workspace_root")
        )
        sessionId: str | None = Field(
            default=None, validation_alias=AliasChoices("sessionId", "session_id")
        )

    @router.post("/api/coding/change-plan/apply")
    def apply_change_plan(payload: ApplyPlanRequest) -> dict:
        try:
            return service.apply_change_plan_transactional(
                payload.plan,
                workspace_root=payload.workspaceRoot,
                session_id=payload.sessionId,
            )
        except CodingError as exc:
            raise_coding_error(exc)

    @router.post("/api/coding/verification/plan")
    def verification_plan(payload: ApplyPlanRequest) -> dict:
        try:
            return {
                "verification": service.adaptive_verification(
                    workspace_root=payload.workspaceRoot,
                    session_id=payload.sessionId,
                    plan_payload=payload.plan,
                )
            }
        except CodingError as exc:
            raise_coding_error(exc)

    class ReviewRequest(BaseModel):
        model_config = ConfigDict(populate_by_name=True)
        plan: dict[str, Any] | None = None
        diffs: dict[str, str] | None = None
        test_evidence: list[str] | None = Field(
            default=None, validation_alias=AliasChoices("test_evidence", "testEvidence")
        )

    @router.post("/api/coding/review")
    def review_diff(payload: ReviewRequest) -> dict:
        try:
            return {
                "review": service.review_diff(
                    plan_payload=payload.plan,
                    diffs=payload.diffs,
                    test_evidence=payload.test_evidence,
                )
            }
        except CodingError as exc:
            raise_coding_error(exc)

    return router
