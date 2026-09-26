"""TEAM quality-orchestration HTTP surface — contracts, activity, controls."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from Data.modules.cognition.team_orchestrator import TeamOrchestrator
from Data.modules.cognition.team_strategy import (
    OptionalUserCaps,
    TeamExecutionPolicy,
    USER_FACING_TEAM_DESCRIPTION,
    normalize_collaboration_strategy,
)
from Data.modules.verification.quality_contract import CompletionPolicyKind


class TeamStartRequest(BaseModel):
    message: str = Field(..., min_length=1)
    taskCategory: str = "general"
    requiresResearch: bool = False
    requiresCoding: bool = False
    requiresTools: bool = False
    conversationId: str | None = None
    maxIterations: int | None = None
    maxWallTimeSeconds: float | None = None
    allowedCapabilities: list[str] = Field(default_factory=list)


class TeamSteerRequest(BaseModel):
    instruction: str = Field(..., min_length=1)
    materialScopeChange: bool = False
    userAcceptedRelaxation: bool = False


class TeamResumeRequest(BaseModel):
    input: dict[str, Any] | None = None


def build_team_router(orchestrator: TeamOrchestrator) -> APIRouter:
    router = APIRouter(tags=["team"])

    @router.get("/api/team/capabilities")
    def team_capabilities() -> dict:
        return {
            "collaboration_strategies": ["direct", "team"],
            "description": USER_FACING_TEAM_DESCRIPTION,
            "completion_policies": [p.value for p in CompletionPolicyKind],
            "truth": {
                "team_is_not_maximum_with_more_tokens": True,
                "null_caps_mean_unbounded": True,
            },
        }

    @router.post("/api/team/runs")
    def team_start(payload: TeamStartRequest) -> dict:
        try:
            policy = TeamExecutionPolicy(
                completion_policy=CompletionPolicyKind.QUALITY_CONTRACT,
                user_caps=OptionalUserCaps(
                    max_iterations=payload.maxIterations,
                    max_wall_time_seconds=payload.maxWallTimeSeconds,
                ),
            )
            state = orchestrator.start(
                request_text=payload.message,
                request_ref=payload.conversationId or "",
                task_category=payload.taskCategory,
                requires_research=payload.requiresResearch,
                requires_coding=payload.requiresCoding,
                requires_tools=payload.requiresTools,
                policy=policy,
                parent_capabilities=payload.allowedCapabilities,
            )
            # Advance at least through planning → first work unit for responsiveness.
            state = orchestrator.advance(state.run_id, max_steps=1)
            return state.public_dict()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": "INVALID_TEAM_REQUEST", "message": str(exc)}) from exc

    @router.get("/api/team/runs/{run_id}")
    def team_status(run_id: str) -> dict:
        state = orchestrator.get(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": run_id})
        return state.public_dict()

    @router.get("/api/team/runs/{run_id}/contract")
    def team_contract(run_id: str) -> dict:
        state = orchestrator.get(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": run_id})
        return {
            "run_id": run_id,
            "contract": state.contract.public_dict(),
            "verdicts": [v.public_dict() for v in state.verdicts if v.status.value != "stale"],
            "acceptance": state.acceptance.public_dict() if state.acceptance else None,
            "progress": state.public_dict()["progress"],
        }

    @router.get("/api/team/runs/{run_id}/events")
    def team_events(run_id: str, after_seq: int = 0) -> dict:
        state = orchestrator.get(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": run_id})
        events = [e for e in state.events if int(e.get("seq") or 0) > after_seq]
        return {
            "run_id": run_id,
            "events": events,
            "latest_seq": state.event_seq,
            "status": state.status.value,
            "truth": {
                "event_is_not_second_database": True,
                "reconnect_recovers_from_state": True,
            },
        }

    @router.post("/api/team/runs/{run_id}/advance")
    def team_advance(run_id: str, steps: int = 1) -> dict:
        try:
            state = orchestrator.advance(run_id, max_steps=max(1, min(steps, 20)))
            return state.public_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"error": "ILLEGAL_TRANSITION", "message": str(exc)}) from exc

    @router.post("/api/team/runs/{run_id}/pause")
    def team_pause(run_id: str) -> dict:
        try:
            return orchestrator.pause(run_id).public_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": str(exc)}) from exc

    @router.post("/api/team/runs/{run_id}/resume")
    def team_resume(run_id: str, payload: TeamResumeRequest | None = None) -> dict:
        try:
            state = orchestrator.resume(
                run_id,
                supply_input=(payload.input if payload else None),
            )
            state = orchestrator.advance(run_id, max_steps=1)
            return state.public_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": str(exc)}) from exc

    @router.post("/api/team/runs/{run_id}/cancel")
    def team_cancel(run_id: str) -> dict:
        try:
            return orchestrator.cancel(run_id).public_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": str(exc)}) from exc

    @router.post("/api/team/runs/{run_id}/steer")
    def team_steer(run_id: str, payload: TeamSteerRequest) -> dict:
        try:
            state = orchestrator.steer(
                run_id,
                payload.instruction,
                material_scope_change=payload.materialScopeChange,
                user_accepted_relaxation=payload.userAcceptedRelaxation,
            )
            return state.public_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": "INVALID_STEER", "message": str(exc)}) from exc

    @router.get("/api/team/runs/{run_id}/export")
    def team_export(run_id: str, provisional: bool = True) -> dict:
        try:
            return orchestrator.export_artifact(run_id, provisional_ok=provisional)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": str(exc)}) from exc

    return router


def parse_collaboration_strategy(value: str | None) -> str:
    return normalize_collaboration_strategy(value).value
