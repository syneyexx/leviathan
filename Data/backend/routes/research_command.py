"""Research Command composition routes. Owners stay on orchestra, portfolio, and lab services."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from Data.modules.market_sim.orchestra.service import TradingOrchestraError
from Data.modules.market_sim.research_command.service import ResearchCommandError, ResearchCommandService


def _raise(exc: ResearchCommandError | TradingOrchestraError) -> None:
    raise HTTPException(status_code=exc.http_status, detail=exc.public_dict()) from exc


class StartBody(BaseModel):
    orchestraId: str
    portfolioId: str
    labId: str | None = None


class PauseBody(BaseModel):
    sessionId: str | None = None
    orchestraId: str | None = None


class FlattenBody(BaseModel):
    sessionId: str
    confirm: str = ""


class KillBody(BaseModel):
    sessionId: str
    armed: bool = True
    confirm: str | None = None


class EvolveBody(BaseModel):
    labId: str


class WatchBody(BaseModel):
    sessionId: str
    symbol: str
    reason: str = ""


def build_research_command_router(service: ResearchCommandService) -> APIRouter:
    router = APIRouter(tags=["market-sim", "research-command"])

    @router.get("/api/market-sim/research-command")
    def snapshot(
        orchestraId: str | None = None,
        portfolioId: str | None = None,
        labId: str | None = None,
        sessionId: str | None = None,
        asOf: str | None = None,
    ) -> dict[str, Any]:
        try:
            return service.snapshot(
                orchestra_id=orchestraId,
                portfolio_id=portfolioId,
                lab_id=labId,
                session_id=sessionId,
                as_of=asOf,
            )
        except (ResearchCommandError, TradingOrchestraError) as exc:
            _raise(exc)

    @router.post("/api/market-sim/research-command/start")
    def start(body: StartBody) -> dict[str, Any]:
        try:
            return service.start(
                orchestra_id=body.orchestraId,
                portfolio_id=body.portfolioId,
                lab_id=body.labId,
            )
        except (ResearchCommandError, TradingOrchestraError) as exc:
            _raise(exc)

    @router.post("/api/market-sim/research-command/pause")
    def pause(body: PauseBody) -> dict[str, Any]:
        try:
            return service.pause(session_id=body.sessionId, orchestra_id=body.orchestraId)
        except (ResearchCommandError, TradingOrchestraError) as exc:
            _raise(exc)

    @router.post("/api/market-sim/research-command/flatten")
    def flatten(body: FlattenBody) -> dict[str, Any]:
        try:
            return service.flatten(session_id=body.sessionId, confirm=body.confirm)
        except (ResearchCommandError, TradingOrchestraError) as exc:
            _raise(exc)

    @router.post("/api/market-sim/research-command/kill-switch")
    def kill_switch(body: KillBody) -> dict[str, Any]:
        try:
            return service.kill_switch(session_id=body.sessionId, armed=body.armed, confirm=body.confirm)
        except (ResearchCommandError, TradingOrchestraError) as exc:
            _raise(exc)

    @router.post("/api/market-sim/research-command/evolution/start")
    def evolve(body: EvolveBody) -> dict[str, Any]:
        try:
            return service.start_evolution(lab_id=body.labId)
        except (ResearchCommandError, TradingOrchestraError) as exc:
            _raise(exc)

    @router.post("/api/market-sim/research-command/watch")
    def watch(body: WatchBody) -> dict[str, Any]:
        try:
            return service.add_watch(session_id=body.sessionId, symbol=body.symbol, reason=body.reason)
        except (ResearchCommandError, TradingOrchestraError) as exc:
            _raise(exc)

    return router
