"""HTTP surface for One Brain observability. Main GUI only."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .service import get_brain


class RouteInput(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=8, ge=1, le=32)


class RoleViewInput(BaseModel):
    mission: dict[str, Any]
    role: str = Field(min_length=1, max_length=120)
    extra: dict[str, Any] | None = None


class VerifyInput(BaseModel):
    domain: str = Field(default="generic", max_length=40)
    execution_success: bool
    evidence: dict[str, Any] | None = None
    agent_claims: list[str] | None = None
    risk_requires_critic: bool = False


class ToolBindInput(BaseModel):
    query: str = Field(default="", max_length=4000)
    tools: list[dict[str, Any]] = Field(default_factory=list)


def mount_hades_brain_routes(ctx: dict[str, Any]) -> APIRouter:
    router = APIRouter(prefix="/hades-brain", tags=["hades-brain"])

    def brain():
        return get_brain(ctx.get("platform_db"))

    @router.get("/overview")
    def overview() -> dict[str, Any]:
        return brain().overview()

    @router.post("/route")
    def route(payload: RouteInput) -> dict[str, Any]:
        return brain().route(payload.query, limit=payload.limit)

    @router.post("/role-view")
    def role_view(payload: RoleViewInput) -> dict[str, Any]:
        from capability_intel.collaboration import MissionState

        mission = MissionState.from_mapping(payload.mission)
        return brain().role_view(mission, role=payload.role, extra=payload.extra)

    @router.post("/verify")
    def verify(payload: VerifyInput) -> dict[str, Any]:
        return brain().verify(
            domain=payload.domain,
            execution_success=payload.execution_success,
            evidence=payload.evidence,
            agent_claims=payload.agent_claims,
            risk_requires_critic=payload.risk_requires_critic,
        )

    @router.post("/tools/bind")
    def bind_tools(payload: ToolBindInput) -> dict[str, Any]:
        return brain().bind_tools(payload.tools, query=payload.query)

    @router.get("/cost")
    def cost() -> dict[str, Any]:
        return brain().ledger.snapshot()

    @router.get("/domains")
    def domains() -> dict[str, Any]:
        from .domain_runtime import migration_matrix

        return {"items": migration_matrix()}

    @router.get("/self-model")
    def self_model() -> dict[str, Any]:
        """Evidence-backed runtime capability snapshot (Cognitive Pillar 1)."""
        return brain().self_model()

    return router
