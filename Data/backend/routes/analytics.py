"""LLM statistics / analytics HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from Data.modules.analytics import AnalyticsService

_ALLOWED_RANGES = {"1h", "24h", "7d", "30d", "90d"}


def build_analytics_router(service: AnalyticsService) -> APIRouter:
    router = APIRouter(tags=["analytics"])

    def _range(range_key: str) -> str:
        return range_key if range_key in _ALLOWED_RANGES else "7d"

    @router.get("/api/analytics/overview")
    def overview(rangeKey: str = Query("7d")) -> dict:
        return {"overview": service.overview(range_key=_range(rangeKey))}

    @router.get("/api/analytics/agents")
    def agents(rangeKey: str = Query("7d")) -> dict:
        return {"agents": service.agents(range_key=_range(rangeKey))}

    @router.get("/api/analytics/training")
    def training(rangeKey: str = Query("7d")) -> dict:
        return {"training": service.training(range_key=_range(rangeKey))}

    @router.get("/api/analytics/datasets")
    def datasets(rangeKey: str = Query("7d")) -> dict:
        return {"datasets": service.datasets(range_key=_range(rangeKey))}

    @router.get("/api/analytics/tools")
    def tools(rangeKey: str = Query("7d")) -> dict:
        return {"tools": service.tools(range_key=_range(rangeKey))}

    return router
