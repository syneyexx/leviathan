"""Brain graph HTTP surface."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from Data.modules.brain import BrainQueryFacade


def build_brain_router(facade: BrainQueryFacade) -> APIRouter:
    router = APIRouter(tags=["brain"])

    @router.get("/api/brain/graph")
    def brain_graph(
        limit: Annotated[int, Query(ge=1, le=1000)] = 200,
        q: Annotated[str | None, Query(max_length=200)] = None,
        types: Annotated[str | None, Query(description="Comma-separated type filters")] = None,
        root: Annotated[str | None, Query()] = None,
    ) -> dict[str, Any]:
        type_list = [t.strip() for t in (types or "").split(",") if t.strip()] or None
        return facade.query(types=type_list, q=q, limit=limit, root=root)

    @router.get("/api/brain/stats")
    def brain_stats() -> dict[str, Any]:
        graph = facade.query(limit=facade.max_nodes)
        return {
            "stats": graph["stats"],
            "truth": graph["truth"],
        }

    return router
