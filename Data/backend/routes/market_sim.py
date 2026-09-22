"""FastAPI routes for market simulation control plane."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from Data.modules.market_sim import MarketSimControlPlane, MarketSimError


def raise_market_sim_error(exc: MarketSimError) -> None:
    raise HTTPException(status_code=exc.http_status, detail=exc.public_dict()) from exc


class RegisterDataRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    symbol: str | None = None
    timeframe: str | None = None


class StrategyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] | None = None
    entryRules: dict[str, Any] | None = None
    exitRules: dict[str, Any] | None = None
    riskRules: dict[str, Any] | None = None
    requiredTimeframes: list[str] | None = None
    brainDependencies: list[str] | None = None
    changelog: str = "initial"


class StrategyVersionRequest(BaseModel):
    parameters: dict[str, Any] | None = None
    entryRules: dict[str, Any] | None = None
    exitRules: dict[str, Any] | None = None
    riskRules: dict[str, Any] | None = None
    requiredTimeframes: list[str] | None = None
    brainDependencies: list[str] | None = None
    changelog: str = ""
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None


class StrategyForkRequest(BaseModel):
    name: str | None = None


class RunCreate(BaseModel):
    sourceId: str
    strategyId: str | None = None
    strategyVersion: int | None = None
    startTs: str | None = None
    endTs: str | None = None
    seed: int = 42
    speed: float = 1.0
    initialCash: float = 100_000.0
    feeBps: float = 5.0
    slippageBps: float = 2.0
    maxPositionPct: float = 25.0
    maxDrawdownPct: float = 20.0
    perTradeRiskPct: float = 1.0
    agents: list[dict[str, Any]] | None = None
    deliberationEveryN: int = 5
    stochasticSlippage: bool = False


def build_market_sim_router(service: MarketSimControlPlane) -> APIRouter:
    router = APIRouter(tags=["market-sim"])

    @router.get("/api/market-sim/status")
    def status() -> dict:
        return service.status()

    @router.get("/api/market-sim/health")
    def health() -> dict:
        return {"enabled": service.enabled, **service.data.health()}

    # --- Market data ---

    @router.get("/api/market-sim/data")
    def list_data(
        status_filter: str | None = Query(None, alias="status"),
        limit: int = Query(200, ge=1, le=2000),
    ) -> dict:
        try:
            sources = service.list_market_data(status=status_filter, limit=limit)
        except MarketSimError as exc:
            raise_market_sim_error(exc)
        return {"sources": sources}

    @router.post("/api/market-sim/data/scan")
    def scan_data() -> dict:
        try:
            sources = service.scan_market_data()
        except MarketSimError as exc:
            raise_market_sim_error(exc)
        return {"sources": sources}

    @router.post("/api/market-sim/data/register")
    def register_data(payload: RegisterDataRequest) -> dict:
        try:
            source = service.register_market_data(
                payload.path,
                symbol=payload.symbol,
                timeframe=payload.timeframe,
            )
        except MarketSimError as exc:
            raise_market_sim_error(exc)
        return {"source": source}

    @router.get("/api/market-sim/data/{source_id}")
    def get_data(source_id: str) -> dict:
        try:
            return {"source": service.get_market_data(source_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    # --- Strategies ---

    @router.get("/api/market-sim/strategies")
    def list_strategies(limit: int = Query(200, ge=1, le=1000)) -> dict:
        try:
            return {"strategies": service.list_strategies(limit=limit)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/strategies")
    def create_strategy(payload: StrategyCreate) -> dict:
        try:
            return service.create_strategy(
                name=payload.name,
                description=payload.description,
                tags=payload.tags,
                parameters=payload.parameters,
                entry_rules=payload.entryRules,
                exit_rules=payload.exitRules,
                risk_rules=payload.riskRules,
                required_timeframes=payload.requiredTimeframes,
                brain_dependencies=payload.brainDependencies,
                changelog=payload.changelog,
            )
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/strategies/{strategy_id}")
    def get_strategy(strategy_id: str) -> dict:
        try:
            return service.get_strategy(strategy_id)
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/strategies/{strategy_id}/versions")
    def version_strategy(strategy_id: str, payload: StrategyVersionRequest) -> dict:
        try:
            return service.version_strategy(
                strategy_id,
                parameters=payload.parameters,
                entry_rules=payload.entryRules,
                exit_rules=payload.exitRules,
                risk_rules=payload.riskRules,
                required_timeframes=payload.requiredTimeframes,
                brain_dependencies=payload.brainDependencies,
                changelog=payload.changelog,
                name=payload.name,
                description=payload.description,
                tags=payload.tags,
            )
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/strategies/{strategy_id}/fork")
    def fork_strategy(strategy_id: str, payload: StrategyForkRequest | None = None) -> dict:
        body = payload or StrategyForkRequest()
        try:
            return service.fork_strategy(strategy_id, name=body.name)
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/strategies/{strategy_id}/archive")
    def archive_strategy(strategy_id: str) -> dict:
        try:
            return {"strategy": service.archive_strategy(strategy_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    # --- Runs ---

    @router.get("/api/market-sim/runs")
    def list_runs(
        status_filter: str | None = Query(None, alias="status"),
        limit: int = Query(100, ge=1, le=500),
    ) -> dict:
        try:
            return {"runs": service.list_runs(status=status_filter, limit=limit)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/runs")
    def create_run(payload: RunCreate) -> dict:
        try:
            run = service.create_run(
                source_id=payload.sourceId,
                strategy_id=payload.strategyId,
                strategy_version=payload.strategyVersion,
                start_ts=payload.startTs,
                end_ts=payload.endTs,
                seed=payload.seed,
                speed=payload.speed,
                initial_cash=payload.initialCash,
                fee_bps=payload.feeBps,
                slippage_bps=payload.slippageBps,
                max_position_pct=payload.maxPositionPct,
                max_drawdown_pct=payload.maxDrawdownPct,
                per_trade_risk_pct=payload.perTradeRiskPct,
                agents=payload.agents,
                deliberation_every_n=payload.deliberationEveryN,
                stochastic_slippage=payload.stochasticSlippage,
            )
        except MarketSimError as exc:
            raise_market_sim_error(exc)
        return {"run": run}

    @router.get("/api/market-sim/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        try:
            return {"run": service.get_run(run_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/runs/{run_id}/start")
    def start_run(run_id: str) -> dict:
        try:
            return {"run": service.start_run(run_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/runs/{run_id}/pause")
    def pause_run(run_id: str) -> dict:
        try:
            return {"run": service.pause_run(run_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/runs/{run_id}/step")
    def step_run(run_id: str) -> dict:
        try:
            return {"run": service.step_run(run_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/runs/{run_id}/stop")
    def stop_run(run_id: str) -> dict:
        try:
            return {"run": service.stop_run(run_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/runs/{run_id}/live")
    def live_state(
        run_id: str,
        message_limit: int = Query(100, ge=1, le=2000),
        fill_limit: int = Query(100, ge=1, le=2000),
    ) -> dict:
        try:
            return service.run_live_state(
                run_id, message_limit=message_limit, fill_limit=fill_limit
            )
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/runs/{run_id}/results")
    def results(run_id: str) -> dict:
        try:
            return service.run_results(run_id)
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    return router
