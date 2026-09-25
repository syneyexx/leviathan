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

    return router
