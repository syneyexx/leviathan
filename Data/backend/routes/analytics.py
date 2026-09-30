"""LLM statistics / analytics HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from Data.modules.analytics import AnalyticsService
from Data.modules.analytics.contracts import (
    ALLOWED_RANGES,
    DEFAULT_ACTIVITY_LIMIT,
    DEFAULT_CHART_RANGE,
    DEFAULT_RANKING_RANGE,
    MAX_ACTIVITY_LIMIT,
    normalize_range,
)


def build_analytics_router(service: AnalyticsService) -> APIRouter:
    router = APIRouter(tags=["analytics"])

    def _range(range_key: str) -> str:
        return range_key if range_key in ALLOWED_RANGES else "7d"

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

    @router.get("/api/analytics/dashboard")
    def dashboard(
        chartRange: str = Query(DEFAULT_CHART_RANGE),
        rankingRange: str = Query(DEFAULT_RANKING_RANGE),
        activityLimit: int = Query(DEFAULT_ACTIVITY_LIMIT, ge=1, le=MAX_ACTIVITY_LIMIT),
    ) -> dict:
        """Statistieken V2 control-plane projection (additive; legacy routes remain)."""
        return {
            "dashboard": service.dashboard(
                chart_range=normalize_range(chartRange, default=DEFAULT_CHART_RANGE),
                ranking_range=normalize_range(rankingRange, default=DEFAULT_RANKING_RANGE),
                activity_limit=activityLimit,
            )
        }

    return router
