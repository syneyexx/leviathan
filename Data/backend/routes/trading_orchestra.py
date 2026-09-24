"""Trade orchestras, trading news and decision records — /api/market-sim/{orchestras,news,decisions}."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from Data.modules.market_sim.orchestra import TradingOrchestraError, TradingOrchestraService


def _raise(exc: TradingOrchestraError) -> None:
    raise HTTPException(status_code=exc.http_status, detail=exc.public_dict()) from exc


class OrchestraCreate(BaseModel):
    name: str
    description: str | None = None
    mandate: dict[str, Any] = Field(default_factory=dict)
    memberAgentIds: list[str] = Field(default_factory=list)
    seedRoles: list[str] | None = None


class MandateUpdate(BaseModel):
    mandate: dict[str, Any] = Field(default_factory=dict)
    approvalId: str | None = None


class AutonomyUpdate(BaseModel):
    level: str
    approvalId: str | None = None


class MissionLaunch(BaseModel):
    kind: str = "deliberation_round"
    asOf: str | None = None
    request: str | None = None
    priority: str = "med"
    dryRun: bool = False


class FeedCreate(BaseModel):
    name: str
    url: str
    kind: str = "rss"
    enabled: bool = True
    declaredLatencySeconds: int = 0
    licenseState: str = "UNKNOWN"
    symbolsHint: list[str] = Field(default_factory=list)


class FeedUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    declaredLatencySeconds: int | None = None
    licenseState: str | None = None
    symbolsHint: list[str] | None = None


class PollRequest(BaseModel):
    feedId: str | None = None


def build_trading_orchestra_router(service: TradingOrchestraService) -> APIRouter:
    router = APIRouter(tags=["market-sim", "trading-orchestra"])

    @router.get("/api/market-sim/orchestras/summary")
    def orchestra_summary() -> dict:
        return service.summary()

    @router.get("/api/market-sim/orchestras")
    def list_orchestras(includeArchived: bool = Query(False)) -> dict:
        try:
            return {"orchestras": service.list_orchestras(include_archived=includeArchived)}
        except TradingOrchestraError as exc:
            _raise(exc)

    @router.post("/api/market-sim/orchestras")
    def create_orchestra(payload: OrchestraCreate) -> dict:
        try:
            return {"orchestra": service.create_orchestra(payload.model_dump())}
        except TradingOrchestraError as exc:
            _raise(exc)

    @router.get("/api/market-sim/orchestras/{orchestra_id}")
    def get_orchestra(orchestra_id: str) -> dict:
        try:
            return {"orchestra": service.get_orchestra(orchestra_id)}
        except TradingOrchestraError as exc:
            _raise(exc)

    @router.put("/api/market-sim/orchestras/{orchestra_id}/mandate")
    def update_mandate(orchestra_id: str, payload: MandateUpdate) -> dict:
        try:
            return {"orchestra": service.update_mandate(orchestra_id, payload.mandate, approval_id=payload.approvalId)}
        except TradingOrchestraError as exc:
            _raise(exc)

    @router.post("/api/market-sim/orchestras/{orchestra_id}/autonomy")
    def set_autonomy(orchestra_id: str, payload: AutonomyUpdate) -> dict:
        try:
            return {"orchestra": service.set_autonomy(orchestra_id, payload.level, approval_id=payload.approvalId)}
        except TradingOrchestraError as exc:
            _raise(exc)

    @router.post("/api/market-sim/orchestras/{orchestra_id}/missions")
    def launch_mission(orchestra_id: str, payload: MissionLaunch) -> dict:
        try:
            return {
                "mission": service.launch_mission(
                    orchestra_id,
                    kind=payload.kind,
                    as_of=payload.asOf,
                    request=payload.request,
                    priority=payload.priority,
                    dry_run=payload.dryRun,
                )
            }
        except TradingOrchestraError as exc:
            _raise(exc)

    @router.get("/api/market-sim/orchestras/{orchestra_id}/missions")
    def list_missions(orchestra_id: str, limit: int = Query(50, ge=1, le=500)) -> dict:
        try:
            return {"missions": service.list_missions(orchestra_id, limit=limit)}
        except TradingOrchestraError as exc:
            _raise(exc)

    @router.get("/api/market-sim/orchestras/{orchestra_id}/decisions")
    def orchestra_decisions(
        orchestra_id: str,
        stage: str | None = Query(None),
        missionId: str | None = Query(None),
        limit: int = Query(200, ge=1, le=2000),
    ) -> dict:
        try:
            return {"decisions": service.list_decisions(orchestra_id=orchestra_id, mission_id=missionId, stage=stage, limit=limit)}
        except TradingOrchestraError as exc:
            _raise(exc)

    @router.get("/api/market-sim/decisions")
    def list_decisions(
        orchestraId: str | None = Query(None),
        missionId: str | None = Query(None),
        stage: str | None = Query(None),
        limit: int = Query(200, ge=1, le=2000),
    ) -> dict:
        try:
            return {"decisions": service.list_decisions(orchestra_id=orchestraId, mission_id=missionId, stage=stage, limit=limit)}
        except TradingOrchestraError as exc:
            _raise(exc)

    # --- News ---

    @router.get("/api/market-sim/news/feeds")
    def list_feeds() -> dict:
        try:
            return {"feeds": service.list_feeds()}
        except TradingOrchestraError as exc:
            _raise(exc)

    @router.post("/api/market-sim/news/feeds")
    def create_feed(payload: FeedCreate) -> dict:
        try:
            return {"feed": service.create_feed(payload.model_dump())}
        except TradingOrchestraError as exc:
            _raise(exc)

    @router.put("/api/market-sim/news/feeds/{feed_id}")
    def update_feed(feed_id: str, payload: FeedUpdate) -> dict:
        try:
            return {"feed": service.update_feed(feed_id, payload.model_dump(exclude_none=True))}
        except TradingOrchestraError as exc:
            _raise(exc)

    @router.delete("/api/market-sim/news/feeds/{feed_id}")
    def delete_feed(feed_id: str) -> dict:
        try:
            return service.delete_feed(feed_id)
        except TradingOrchestraError as exc:
            _raise(exc)

    @router.post("/api/market-sim/news/poll")
    def poll_feeds(payload: PollRequest | None = None) -> dict:
        try:
            return service.request_poll(feed_id=(payload.feedId if payload else None), requested_by="api.market_sim.news.poll")
        except TradingOrchestraError as exc:
            _raise(exc)

    @router.get("/api/market-sim/news/items")
    def list_news(
        asOf: str | None = Query(None),
        feedId: str | None = Query(None),
        limit: int = Query(100, ge=1, le=1000),
    ) -> dict:
        try:
            return {"items": service.list_news(as_of=asOf, feed_id=feedId, limit=limit)}
        except TradingOrchestraError as exc:
            _raise(exc)

    @router.get("/api/market-sim/news/signals")
    def list_signals(
        asOf: str | None = Query(None),
        instrument: str | None = Query(None),
        limit: int = Query(100, ge=1, le=1000),
    ) -> dict:
        try:
            return {"signals": service.list_signals(as_of=as_of_or_none(asOf), instrument=instrument, limit=limit)}
        except TradingOrchestraError as exc:
            _raise(exc)

    return router


def as_of_or_none(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None
