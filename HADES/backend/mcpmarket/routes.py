"""MCPMarket HTTP surface on the main MCP page. Discovery only."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .connector import get_connector
from .official import official_surface


class SearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="mcp_server")
    mission_id: str = Field(default="anon", max_length=80)


class PrepareInput(BaseModel):
    listing: dict[str, Any]
    operator_approved: bool = False


def mount_mcpmarket_routes() -> APIRouter:
    router = APIRouter(prefix="/mcpmarket", tags=["mcpmarket"])

    @router.get("/status")
    def status() -> dict[str, Any]:
        return get_connector().status()

    @router.get("/official")
    def official() -> dict[str, Any]:
        return official_surface()

    @router.post("/search")
    def search(payload: SearchInput) -> dict[str, Any]:
        kind = payload.kind if payload.kind in {"mcp_server", "skill"} else "mcp_server"
        return get_connector().search(payload.query, mission_id=payload.mission_id, kind=kind)

    @router.get("/servers/{slug}")
    def server(slug: str) -> dict[str, Any]:
        result = get_connector().fetch_server(slug)
        if result.get("listing") is None and result.get("status") == "unknown":
            raise HTTPException(status_code=404, detail="mcpmarket_listing_not_found")
        return result

    @router.get("/skills/{slug}")
    def skill(slug: str) -> dict[str, Any]:
        return get_connector().fetch_skill(slug)

    @router.post("/prepare-connection")
    def prepare(payload: PrepareInput) -> dict[str, Any]:
        return get_connector().prepare(payload.listing, operator_approved=payload.operator_approved)

    return router
