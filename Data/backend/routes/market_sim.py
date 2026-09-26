"""FastAPI routes for market simulation control plane."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from Data.modules.execution import CapabilityCatalog, CapabilityRequest, ExecutionGateway
from Data.modules.market_sim import MarketSimControlPlane, MarketSimError


def raise_market_sim_error(exc: MarketSimError) -> None:
    raise HTTPException(status_code=exc.http_status, detail=exc.public_dict()) from exc


class RegisterDataRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    symbol: str | None = None
    timeframe: str | None = None


class ImportDatasetRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    symbol: str | None = None
    timeframe: str | None = None
    seal: bool = False
    role: str = "RESEARCH"
    provider: str = "csv_local"


class SealDatasetRequest(BaseModel):
    role: str = "SEALED_TEST"


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
    decisionCadence: str | None = None
    stochasticSlippage: bool = False
    gameMode: str | None = None
    metadata: dict[str, Any] | None = None


class ProviderImportRequest(BaseModel):
    providerId: str
    symbol: str
    timeframe: str = "1h"
    limit: int = Field(500, ge=10, le=1000)


class PaperSessionCreate(BaseModel):
    symbol: str
    strategyId: str | None = None
    strategyVersion: int | None = None
    brokerId: str = "local_paper"
    providerId: str = "binance_public"
    initialCash: float = 100_000.0


class PaperOrderRequest(BaseModel):
    side: str
    qty: float = Field(gt=0)
    clientOrderId: str | None = None


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    initialEquity: float = Field(100_000.0, gt=0)
    baseCurrency: str = "USD"
    brokerMode: str = "local_paper"
    providerId: str = "binance_public"
    benchmarkSymbol: str = "BTCUSDT"
    orchestraId: str | None = None
    shortingEnabled: bool = False
    settings: dict[str, Any] | None = None
    agentAllocations: list[dict[str, Any]] | None = None
    strategyAllocations: list[dict[str, Any]] | None = None
    allowManualOnly: bool = True


class PortfolioPatch(BaseModel):
    name: str | None = None
    orchestraId: str | None = None
    benchmarkSymbol: str | None = None
    settings: dict[str, Any] | None = None


class PortfolioOrderRequest(BaseModel):
    symbol: str
    side: str
    qty: float = Field(gt=0)
    clientOrderId: str | None = None
    agentId: str | None = None
    orchestraId: str | None = None
    strategyId: str | None = None
    strategyVersion: int | None = None
    decisionId: str | None = None


class PortfolioCloseSelected(BaseModel):
    positionIds: list[str] = Field(min_length=1)


class PortfolioAllocationsSave(BaseModel):
    allocations: list[dict[str, Any]]


class PortfolioRebalanceRequest(BaseModel):
    orders: list[dict[str, Any]] | None = None


class FeedStartRequest(BaseModel):
    providerId: str = "binance_public"
    symbols: list[str] = Field(min_length=1)
    streamKinds: list[str] | None = None
    restartPolicy: str = "MANUAL"
    captureMode: str = "OFF"
    staleAfterSeconds: float = 30.0
    gapRecoveryEnabled: bool = True
    maxRuntimeSeconds: float = 3600.0
    feedId: str | None = None
    licenseNote: str = ""
    metadata: dict[str, Any] | None = None


class ScanBatchRequest(BaseModel):
    symbols: list[str] | None = None
    providerId: str = "binance_public"
    timeframe: str = "1m"
    limit: int = Field(100, ge=1, le=2000)


class ExperimentPropose(BaseModel):
    strategyId: str
    hypothesis: str
    proposerAgentId: str
    sourceId: str
    seed: int = 42
    acceptanceCriteria: dict[str, Any] | None = None
    config: dict[str, Any] | None = None


class ExperimentComplete(BaseModel):
    metrics: dict[str, Any]
    strategyVersion: int | None = None


class DemoRequest(BaseModel):
    family: str = Field(description="equity | crypto_spot")
    barsLimit: int = Field(120, ge=30, le=2000)


class GymEpisodeCreate(BaseModel):
    sourceId: str
    strategyId: str | None = None
    strategyVersion: int | None = None
    splitRole: str = "TRAIN"
    datasetId: str | None = None
    datasetVersion: str | None = None
    seed: int = 42
    initialCash: float = 100_000.0
    mode: str = "interactive"
    feeBps: float = 5.0
    slippageBps: float = 2.0
    metadata: dict[str, Any] | None = None


class GymStepRequest(BaseModel):
    kind: str = "HOLD"
    qty: float | None = None
    orderType: str | None = None
    limitPrice: float | None = None
    stopPrice: float | None = None
    timeInForce: str | None = None
    rationale: str = "gym_action"


def build_market_sim_router(
    service: MarketSimControlPlane,
    gateway: ExecutionGateway | None = None,
    capability_catalog: CapabilityCatalog | None = None,
) -> APIRouter:
    router = APIRouter(tags=["market-sim"])

    def _mutate_via_gateway(capability_id: str, arguments: dict[str, Any], action) -> Any:
        """Side-effect mutations record through ExecutionGateway when bound (P4B / D16)."""
        if gateway is None:
            return action()
        _ = capability_catalog  # catalog available for operator inspection
        try:
            gateway.execute(
                CapabilityRequest(
                    capability_id=capability_id,
                    arguments=dict(arguments),
                    requested_by="market_sim.api",
                )
            )
        except Exception:  # noqa: BLE001 — receipt attempted; local paper action still runs
            pass
        return action()

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

    @router.post("/api/market-sim/data/import")
    def import_dataset(payload: ImportDatasetRequest) -> dict:
        try:
            return service.import_market_dataset(
                payload.path,
                symbol=payload.symbol,
                timeframe=payload.timeframe,
                seal=payload.seal,
                role=payload.role,
                provider=payload.provider,
            )
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/datasets")
    def list_datasets(
        symbol: str | None = Query(None),
        sealed: bool | None = Query(None),
        role: str | None = Query(None),
        limit: int = Query(200, ge=1, le=2000),
    ) -> dict:
        try:
            return {
                "datasets": service.list_market_datasets(
                    symbol=symbol, sealed=sealed, role=role, limit=limit
                )
            }
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/datasets/{dataset_id}/{version}/seal")
    def seal_dataset(dataset_id: str, version: str, payload: SealDatasetRequest | None = None) -> dict:
        body = payload or SealDatasetRequest()
        try:
            return {"dataset": service.seal_market_dataset(dataset_id, version, role=body.role)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

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
                decision_cadence=payload.decisionCadence,
                stochastic_slippage=payload.stochasticSlippage,
                game_mode=payload.gameMode,
                metadata=payload.metadata,
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

    @router.get("/api/market-sim/runs/{run_id}/knowledge-snapshot")
    def get_run_knowledge_snapshot(run_id: str) -> dict:
        try:
            return {"snapshots": service.get_run_knowledge_snapshots(run_id)}
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

    # --- Providers / capabilities ---

    @router.get("/api/market-sim/providers")
    def list_providers() -> dict:
        try:
            return {"providers": service.list_providers()}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/providers/import")
    def import_provider(payload: ProviderImportRequest) -> dict:
        try:
            return service.import_provider_data(
                provider_id=payload.providerId,
                symbol=payload.symbol,
                timeframe=payload.timeframe,
                limit=payload.limit,
            )
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/capabilities")
    def capabilities() -> dict:
        return service.market_capabilities()

    # --- Paper trading ---

    @router.get("/api/market-sim/paper/sessions")
    def list_paper() -> dict:
        try:
            return {"sessions": service.list_paper_sessions()}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/paper/sessions")
    def create_paper(payload: PaperSessionCreate) -> dict:
        try:
            return {
                "session": service.start_paper_session(
                    symbol=payload.symbol,
                    strategy_id=payload.strategyId,
                    strategy_version=payload.strategyVersion,
                    broker_id=payload.brokerId,
                    provider_id=payload.providerId,
                    initial_cash=payload.initialCash,
                )
            }
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/paper/sessions/{session_id}")
    def get_paper(session_id: str) -> dict:
        try:
            return {"session": service.paper_session_state(session_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/paper/sessions/{session_id}/orders")
    def paper_order(session_id: str, payload: PaperOrderRequest) -> dict:
        try:
            return _mutate_via_gateway(
                "market_sim.paper_order",
                {
                    "session_id": session_id,
                    "side": payload.side,
                    "qty": payload.qty,
                    "client_order_id": payload.clientOrderId,
                },
                lambda: service.paper_place_order(
                    session_id,
                    side=payload.side,
                    qty=payload.qty,
                    client_order_id=payload.clientOrderId,
                ),
            )
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/paper/sessions/{session_id}/kill-switch")
    def paper_kill(session_id: str, armed: bool = True) -> dict:
        try:
            return {"session": service.paper_kill_switch(session_id, armed=armed)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    # --- Paper Portefeuille ---

    @router.get("/api/market-sim/portfolios")
    def list_portfolios(limit: int = Query(50, ge=1, le=200)) -> dict:
        try:
            return {"portfolios": service.list_portfolios(limit=limit)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/portfolios")
    def create_portfolio(payload: PortfolioCreate) -> dict:
        try:
            settings = dict(payload.settings or {})
            if payload.allowManualOnly:
                settings["allow_manual_only"] = True
            return {
                "portfolio": service.create_portfolio(
                    name=payload.name,
                    initial_equity=payload.initialEquity,
                    base_currency=payload.baseCurrency,
                    broker_mode=payload.brokerMode,
                    provider_id=payload.providerId,
                    benchmark_symbol=payload.benchmarkSymbol,
                    orchestra_id=payload.orchestraId,
                    shorting_enabled=payload.shortingEnabled,
                    settings=settings,
                    agent_allocations=payload.agentAllocations,
                    strategy_allocations=payload.strategyAllocations,
                )
            }
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/portfolios/{portfolio_id}")
    def get_portfolio(portfolio_id: str) -> dict:
        try:
            return {"portfolio": service.get_portfolio(portfolio_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.patch("/api/market-sim/portfolios/{portfolio_id}")
    def patch_portfolio(portfolio_id: str, payload: PortfolioPatch) -> dict:
        try:
            patch: dict[str, Any] = {}
            if payload.name is not None:
                patch["name"] = payload.name
            if payload.orchestraId is not None:
                patch["orchestra_id"] = payload.orchestraId
            if payload.benchmarkSymbol is not None:
                patch["benchmark_symbol"] = payload.benchmarkSymbol
            if payload.settings is not None:
                patch["settings"] = payload.settings
            return {"portfolio": service.patch_portfolio(portfolio_id, patch)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/portfolios/{portfolio_id}/start")
    def start_portfolio(portfolio_id: str) -> dict:
        try:
            return {"portfolio": service.start_portfolio(portfolio_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/portfolios/{portfolio_id}/pause")
    def pause_portfolio(portfolio_id: str) -> dict:
        try:
            return {"portfolio": service.pause_portfolio(portfolio_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/portfolios/{portfolio_id}/resume")
    def resume_portfolio(portfolio_id: str) -> dict:
        try:
            return {"portfolio": service.resume_portfolio(portfolio_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/portfolios/{portfolio_id}/stop")
    def stop_portfolio(portfolio_id: str) -> dict:
        try:
            return {"portfolio": service.stop_portfolio(portfolio_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/portfolios/{portfolio_id}/kill-switch")
    def portfolio_kill(portfolio_id: str, armed: bool = True) -> dict:
        try:
            return {"portfolio": service.portfolio_kill_switch(portfolio_id, armed=armed)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/portfolios/{portfolio_id}/dashboard")
    def portfolio_dashboard(
        portfolio_id: str,
        range: str = Query("YTD", alias="range"),
    ) -> dict:
        try:
            return service.portfolio_dashboard(portfolio_id, range_key=range)
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/portfolios/{portfolio_id}/positions")
    def portfolio_positions(portfolio_id: str) -> dict:
        try:
            dash = service.portfolio_dashboard(portfolio_id)
            return {"positions": dash.get("positions") or []}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/portfolios/{portfolio_id}/transactions")
    def portfolio_transactions(
        portfolio_id: str, limit: int = Query(50, ge=1, le=500)
    ) -> dict:
        try:
            return {
                "transactions": service.store.list_portfolio_transactions(
                    portfolio_id, limit=limit
                )
            }
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/portfolios/{portfolio_id}/orders")
    def portfolio_orders(portfolio_id: str, limit: int = Query(50, ge=1, le=500)) -> dict:
        try:
            return {
                "orders": service.store.list_portfolio_orders(portfolio_id, limit=limit)
            }
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/portfolios/{portfolio_id}/performance")
    def portfolio_performance(
        portfolio_id: str,
        range: str = Query("YTD", alias="range"),
    ) -> dict:
        try:
            return {
                "performance": service.portfolio_performance(
                    portfolio_id, range_key=range
                )
            }
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/portfolios/{portfolio_id}/risk")
    def portfolio_risk(portfolio_id: str) -> dict:
        try:
            dash = service.portfolio_dashboard(portfolio_id)
            return {"risk": dash.get("risk") or {}}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/portfolios/{portfolio_id}/allocations")
    def portfolio_allocations(portfolio_id: str) -> dict:
        try:
            return {
                "allocations": service.store.list_portfolio_allocations(portfolio_id)
            }
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/portfolios/{portfolio_id}/allocations")
    def save_portfolio_allocations(
        portfolio_id: str, payload: PortfolioAllocationsSave
    ) -> dict:
        try:
            return service.portfolio_save_allocations(portfolio_id, payload.allocations)
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/portfolios/{portfolio_id}/strategies")
    def portfolio_strategies(portfolio_id: str) -> dict:
        try:
            dash = service.portfolio_dashboard(portfolio_id)
            return {"strategies": dash.get("strategy_allocation") or []}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/portfolios/{portfolio_id}/recommendations")
    def portfolio_recommendations(portfolio_id: str) -> dict:
        try:
            dash = service.portfolio_dashboard(portfolio_id)
            return {"recommendations": dash.get("recommendations") or []}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/portfolios/{portfolio_id}/orders")
    def portfolio_order(portfolio_id: str, payload: PortfolioOrderRequest) -> dict:
        try:
            return _mutate_via_gateway(
                "market_sim.portfolio_order",
                {
                    "portfolio_id": portfolio_id,
                    "symbol": payload.symbol,
                    "side": payload.side,
                    "qty": payload.qty,
                    "client_order_id": payload.clientOrderId,
                },
                lambda: service.portfolio_place_order(
                    portfolio_id,
                    symbol=payload.symbol,
                    side=payload.side,
                    qty=payload.qty,
                    client_order_id=payload.clientOrderId,
                    agent_id=payload.agentId,
                    orchestra_id=payload.orchestraId,
                    strategy_id=payload.strategyId,
                    strategy_version=payload.strategyVersion,
                    decision_id=payload.decisionId,
                ),
            )
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/portfolios/{portfolio_id}/positions/{position_id}/close")
    def close_portfolio_position(portfolio_id: str, position_id: str) -> dict:
        try:
            return service.portfolio_close_position(portfolio_id, position_id)
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/portfolios/{portfolio_id}/positions/close-selected")
    def close_selected_positions(
        portfolio_id: str, payload: PortfolioCloseSelected
    ) -> dict:
        try:
            return service.portfolio_close_positions(portfolio_id, payload.positionIds)
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/portfolios/{portfolio_id}/rebalance/preview")
    def rebalance_preview(portfolio_id: str, payload: PortfolioRebalanceRequest) -> dict:
        try:
            return service.portfolio_rebalance_preview(portfolio_id, payload.orders)
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/portfolios/{portfolio_id}/rebalance/execute")
    def rebalance_execute(portfolio_id: str, payload: PortfolioRebalanceRequest) -> dict:
        try:
            return _mutate_via_gateway(
                "market_sim.portfolio_rebalance",
                {"portfolio_id": portfolio_id, "orders": payload.orders},
                lambda: service.portfolio_rebalance_execute(portfolio_id, payload.orders),
            )
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/portfolios/{portfolio_id}/export")
    def export_portfolio(
        portfolio_id: str, format: str = Query("json", alias="format")
    ) -> dict:
        try:
            return service.portfolio_export(portfolio_id, fmt=format)
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/portfolios/{portfolio_id}/tick")
    def portfolio_tick(portfolio_id: str) -> dict:
        try:
            return service.portfolio_tick(portfolio_id)
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    # --- Experiments ---

    @router.get("/api/market-sim/experiments")
    def list_experiments(strategy_id: str | None = Query(None, alias="strategyId")) -> dict:
        try:
            return {"experiments": service.list_experiments(strategy_id=strategy_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/experiments")
    def propose_experiment(payload: ExperimentPropose) -> dict:
        try:
            return {
                "trial": service.propose_experiment(
                    strategy_id=payload.strategyId,
                    hypothesis=payload.hypothesis,
                    proposer_agent_id=payload.proposerAgentId,
                    source_id=payload.sourceId,
                    acceptance_criteria=payload.acceptanceCriteria,
                    seed=payload.seed,
                    config=payload.config,
                )
            }
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/experiments/{trial_id}/complete")
    def complete_experiment(trial_id: str, payload: ExperimentComplete) -> dict:
        try:
            return {
                "trial": service.complete_experiment(
                    trial_id,
                    metrics=payload.metrics,
                    strategy_version=payload.strategyVersion,
                )
            }
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/demos/run")
    def run_demo(payload: DemoRequest) -> dict:
        try:
            return service.run_market_demo(family=payload.family, bars_limit=payload.barsLimit)
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    # --- TradingGym (P1B) ---

    @router.post("/api/market-sim/gym/episodes")
    def create_gym_episode(payload: GymEpisodeCreate) -> dict:
        try:
            return service.create_gym_episode(
                source_id=payload.sourceId,
                strategy_id=payload.strategyId,
                strategy_version=payload.strategyVersion,
                split_role=payload.splitRole,
                dataset_id=payload.datasetId,
                dataset_version=payload.datasetVersion,
                seed=payload.seed,
                initial_cash=payload.initialCash,
                mode=payload.mode,
                fee_bps=payload.feeBps,
                slippage_bps=payload.slippageBps,
                metadata=payload.metadata,
            )
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/gym/episodes/{run_id}/step")
    def gym_step(run_id: str, payload: GymStepRequest) -> dict:
        try:
            return service.gym_step(
                run_id,
                {
                    "kind": payload.kind,
                    "qty": payload.qty,
                    "order_type": payload.orderType,
                    "limit_price": payload.limitPrice,
                    "stop_price": payload.stopPrice,
                    "time_in_force": payload.timeInForce,
                    "rationale": payload.rationale,
                },
            )
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/gym/episodes/{run_id}/start")
    def start_gym_episode(run_id: str) -> dict:
        try:
            return {"episode": service.start_gym_episode(run_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/gym/episodes/{run_id}/export-trajectory")
    def export_gym_trajectory(run_id: str, datasetName: str | None = None) -> dict:
        try:
            return service.export_gym_trajectory(run_id, dataset_name=datasetName)
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/live-trading")
    def live_trading_status() -> dict:
        return service.live_guard.public_status()

    # --- Realtime market feeds ---

    @router.get("/api/market-sim/feeds")
    def list_feeds() -> dict:
        try:
            return {"feeds": service.list_feeds()}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/feeds")
    def start_feed(payload: FeedStartRequest) -> dict:
        try:
            return {
                "feed": service.start_feed(
                    provider_id=payload.providerId,
                    symbols=payload.symbols,
                    stream_kinds=payload.streamKinds,
                    restart_policy=payload.restartPolicy,
                    capture_mode=payload.captureMode,
                    stale_after_seconds=payload.staleAfterSeconds,
                    gap_recovery_enabled=payload.gapRecoveryEnabled,
                    max_runtime_seconds=payload.maxRuntimeSeconds,
                    feed_id=payload.feedId,
                    license_note=payload.licenseNote,
                    metadata=payload.metadata,
                )
            }
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/feeds/{feed_id}")
    def get_feed(feed_id: str) -> dict:
        try:
            return {"feed": service.get_feed(feed_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/feeds/{feed_id}/stop")
    def stop_feed(feed_id: str) -> dict:
        try:
            return {"feed": service.stop_feed(feed_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/feeds/{feed_id}/snapshot")
    def feed_snapshot(feed_id: str) -> dict:
        try:
            return service.feed_snapshot(feed_id)
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/feeds/{feed_id}/metrics")
    def feed_metrics(feed_id: str) -> dict:
        try:
            return service.feed_metrics(feed_id)
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/scan-batch")
    def scan_batch(payload: ScanBatchRequest) -> dict:
        try:
            return service.scan_batch(
                symbols=payload.symbols,
                provider_id=payload.providerId,
                timeframe=payload.timeframe,
                limit=payload.limit,
            )
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    # --- W17 Trading Lab surface (typed real endpoints; no mock KPIs) ---

    @router.get("/api/market-sim/lab/overview")
    def lab_overview() -> dict:
        """Aggregate lab capability truth for Trading Center UI."""
        from Data.modules.market_sim.agent_lab import LAB_ROLES, LabOutcome
        from Data.modules.market_sim.costs import CostModelPack
        from Data.modules.market_sim.curriculum import STAGE_ORDER
        from Data.modules.market_sim.features import FEATURE_PIPELINE_VERSION
        from Data.modules.market_sim.hpo import HPO_METHODS, bayesian_tpe_capability
        from Data.modules.market_sim.regimes import REGIME_DETECTOR_VERSION, hmm_regime_capability
        from Data.modules.market_sim.strategy_dsl import DSL_CURRENT_VERSION
        from Data.modules.market_sim.code_strategy import python_strategy_capability

        live = service.live_guard.public_status()
        trials = 0
        try:
            trials = int(service.store.count_trials())
        except Exception:
            trials = 0
        return {
            "feature_pipeline_version": FEATURE_PIPELINE_VERSION,
            "dsl_version": DSL_CURRENT_VERSION,
            "regime_detector_version": REGIME_DETECTOR_VERSION,
            "lab_roles": list(LAB_ROLES),
            "curriculum_stages": [s.value for s in STAGE_ORDER],
            "hpo_methods": sorted(HPO_METHODS),
            "hpo_bayesian_tpe": bayesian_tpe_capability(),
            "hmm_regime": hmm_regime_capability(),
            "python_strategies": python_strategy_capability(),
            "default_cost_pack": CostModelPack.from_fee_slippage_bps().public_dict(),
            "trial_ledger_count": trials,
            "valid_lab_outcomes": [LabOutcome.QUALIFIED_STRATEGY_FOUND.value, LabOutcome.NO_STRATEGY_QUALIFIED.value],
            "live_trading": live,
            "truth": {
                "no_mock_kpis": True,
                "paper_does_not_prove_live_profitability": True,
                "live_trading": "BLOCKED",
                "a5": "IMPOSSIBLE",
                "no_strategy_qualified_is_valid_pass": True,
            },
        }

    @router.get("/api/market-sim/lab/cost-pack")
    def lab_cost_pack(feeBps: float = 0.0, slippageBps: float = 0.0, seed: int | None = None) -> dict:
        from Data.modules.market_sim.costs import CostModelPack

        pack = CostModelPack.from_fee_slippage_bps(fee_bps=feeBps, slippage_bps=slippageBps, seed=seed)
        return {"cost_pack": pack.public_dict()}

    @router.post("/api/market-sim/lab/feed-health")
    def lab_feed_health(payload: dict[str, Any]) -> dict:
        from Data.modules.market_sim.paper_deployment import assess_feed_health

        health = assess_feed_health(
            feed_id=str(payload.get("feedId") or payload.get("feed_id") or "unknown"),
            last_tick_ts=payload.get("lastTickTs") or payload.get("last_tick_ts"),
            as_of=payload.get("asOf") or payload.get("as_of"),
            gap_count=int(payload.get("gapCount") or payload.get("gap_count") or 0),
            reconnect_count=int(payload.get("reconnectCount") or payload.get("reconnect_count") or 0),
            provenance=str(payload.get("provenance") or ""),
            max_staleness_seconds=float(
                payload.get("maxStalenessSeconds") or payload.get("max_staleness_seconds") or 120.0
            ),
        )
        return {"feed_health": health.public_dict()}

    @router.get("/api/market-sim/lab/trials")
    def lab_trials(strategyId: str | None = None, limit: int = Query(50, ge=1, le=500)) -> dict:
        try:
            rows = service.store.list_experiments(strategy_id=strategyId, limit=limit)
            return {
                "trials": rows,
                "count": service.store.count_trials(strategy_id=strategyId),
                "truth": {"losing_trials_retained": True, "append_only": True},
            }
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    # --- W16 autonomous lab lifecycle (create/start/pause/resume/cancel/status) ---

    @router.post("/api/market-sim/lab/runs")
    def lab_create(payload: dict[str, Any]) -> dict:
        try:
            lab = service.create_agent_lab(
                name=str(payload.get("name") or ""),
                strategy_id=str(payload.get("strategyId") or payload.get("strategy_id") or ""),
                source_id=str(payload.get("sourceId") or payload.get("source_id") or ""),
                strategy_version=payload.get("strategyVersion") or payload.get("strategy_version"),
                max_candidates=int(payload.get("maxCandidates") or payload.get("max_candidates") or 10),
                max_iterations=int(payload.get("maxIterations") or payload.get("max_iterations") or 3),
                seed=int(payload.get("seed") or 42),
                hypothesis=str(payload.get("hypothesis") or ""),
                acceptance_criteria=payload.get("acceptanceCriteria") or payload.get("acceptance_criteria"),
                autonomy_ceiling=str(payload.get("autonomyCeiling") or payload.get("autonomy_ceiling") or "A1"),
                metadata=payload.get("metadata"),
            )
            return {"lab": lab}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/lab/runs")
    def lab_list(limit: int = Query(50, ge=1, le=200)) -> dict:
        try:
            return {"labs": service.list_agent_labs(limit=limit)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/lab/runs/{lab_id}")
    def lab_get(lab_id: str) -> dict:
        try:
            return {"lab": service.get_agent_lab(lab_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/lab/runs/{lab_id}/start")
    def lab_start(lab_id: str) -> dict:
        try:
            return service.start_agent_lab(lab_id)
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/lab/runs/{lab_id}/pause")
    def lab_pause(lab_id: str) -> dict:
        try:
            return {"lab": service.pause_agent_lab(lab_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/lab/runs/{lab_id}/resume")
    def lab_resume(lab_id: str) -> dict:
        try:
            return service.resume_agent_lab(lab_id)
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/lab/runs/{lab_id}/cancel")
    def lab_cancel(lab_id: str) -> dict:
        try:
            return {"lab": service.cancel_agent_lab(lab_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    return router
