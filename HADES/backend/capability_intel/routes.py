"""Main-GUI HTTP surface for capability intelligence observability."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .service import get_service


class RoutePreviewInput(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=8, ge=1, le=32)


class ComposeInput(BaseModel):
    query: str = Field(min_length=1, max_length=4000)


def mount_capability_intel_routes(ctx: dict[str, Any]) -> APIRouter:
    router = APIRouter(prefix="/capability-intel", tags=["capability-intel"])

    def service():
        db = ctx.get("platform_db")
        return get_service(db)

    @router.get("/overview")
    def overview() -> dict[str, Any]:
        return service().overview()

    @router.get("/registry")
    def registry(kind: str | None = None) -> dict[str, Any]:
        records = service().registry.all()
        if kind:
            records = [item for item in records if item.kind == kind]
        return {"count": len(records), "items": [item.to_dict() for item in records[:400]]}

    @router.get("/plugins/{plugin_id}/groups")
    def plugin_groups(plugin_id: str) -> dict[str, Any]:
        groups = service().plugin_groups(plugin_id)
        return {"plugin_id": plugin_id, "groups": groups}

    @router.post("/route")
    def route_preview(payload: RoutePreviewInput) -> dict[str, Any]:
        plan, decision = service().route(payload.query, limit=payload.limit)
        return {"plan": plan.to_dict(), "routing": decision.to_dict()}

    @router.post("/compose")
    def compose(payload: ComposeInput) -> dict[str, Any]:
        return service().compose(payload.query)

    @router.get("/missions/{mission_id}")
    def mission(mission_id: str) -> dict[str, Any]:
        from .store import load_messages, load_mission

        db = ctx.get("platform_db")
        if db is None:
            raise HTTPException(status_code=503, detail="platform database unavailable")
        data = load_mission(db, mission_id)
        if data is None:
            raise HTTPException(status_code=404, detail="mission not found")
        return {"mission": data, "messages": load_messages(db, mission_id)}

    return router
