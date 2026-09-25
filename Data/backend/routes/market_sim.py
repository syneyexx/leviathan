"""FastAPI routes for market simulation control plane.

Side-effecting mutations dispatch through ExecutionGateway + capability_catalog
(T4A / G37). Read endpoints still call the control plane directly.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from Data.modules.execution import CapabilityRequest, CapabilityStatus, ExecutionGateway
from Data.modules.execution.catalog import CapabilityCatalog
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
    dslSpec: dict[str, Any] | None = None
    family: str | None = None


class StrategyValidateRequest(BaseModel):
    dslSpec: dict[str, Any]


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
    dslSpec: dict[str, Any] | None = None


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
    metrics: dict[str, Any] | None = None
    strategyVersion: int | None = None
    runId: str | None = None
    runIds: list[str] | None = None


class DemoRequest(BaseModel):
    family: str = Field(description="equity | crypto_spot")
    barsLimit: int = Field(120, ge=30, le=2000)


def build_market_sim_router(
    service: MarketSimControlPlane,
    *,
    gateway: ExecutionGateway | None = None,
    capability_catalog: CapabilityCatalog | None = None,
) -> APIRouter:
    router = APIRouter(tags=["market-sim"])
    # Keep catalog reference for D16 / G37 evidence even when gateway carries it.
    _catalog = capability_catalog or (gateway.catalog if gateway is not None else None)

    def _mutate(
        capability_id: str,
        arguments: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        run_id: str | None = None,
        fallback: Any | None = None,
    ) -> dict:
        """Dispatch a side-effect via ExecutionGateway when bound."""
        if gateway is None:
            if fallback is not None:
                return fallback() if callable(fallback) else fallback
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "GATEWAY_UNBOUND",
                    "message": "ExecutionGateway not bound for market_sim mutations",
                },
            )
        if _catalog is not None and _catalog.get(capability_id) is None:
            raise HTTPException(
                status_code=500,
                detail={"code": "CAPABILITY_MISSING", "capability_id": capability_id},
            )
        result = gateway.execute(
            CapabilityRequest(
                capability_id=capability_id,
                arguments=arguments,
                requested_by="api.market_sim",
                run_id=run_id,
                request_id=str(uuid.uuid4()),
                idempotency_key=idempotency_key or f"market_sim:{capability_id}:{uuid.uuid4().hex[:12]}",
            )
        )
        if result.status == CapabilityStatus.REJECTED:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "GATEWAY_REJECTED",
                    "capability_id": capability_id,
                    "reason": (result.telemetry or {}).get("reason"),
                    "error": result.error,
                },
            )
        if result.status != CapabilityStatus.COMPLETED:
            # Module executor packs MarketSimError into telemetry.code
            code = (result.telemetry or {}).get("code") or "MUTATION_FAILED"
            http_status = int((result.telemetry or {}).get("http_status") or 500)
            raise HTTPException(
                status_code=http_status,
                detail={"code": code, "message": result.error or "mutation failed"},
            )
        output = result.output if isinstance(result.output, dict) else {"result": result.output}
        if isinstance(output, dict) and "output" in output and len(output) <= 4:
            # unwrap MarketSimModuleExecutor envelope
            inner = output.get("output")
            if isinstance(inner, dict):
                return inner
        return output if isinstance(output, dict) else {"result": output}

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
        return _mutate(
            "market_sim.data.scan",
            {},
            idempotency_key=f"market_sim:data.scan:{uuid.uuid4().hex[:8]}",
            fallback=lambda: {"sources": service.scan_market_data()},
        )

    @router.post("/api/market-sim/data/register")
    def register_data(payload: RegisterDataRequest) -> dict:
        args = {"path": payload.path, "symbol": payload.symbol, "timeframe": payload.timeframe}
        return _mutate(
            "market_sim.data.register",
            args,
            fallback=lambda: {
                "source": service.register_market_data(
                    payload.path, symbol=payload.symbol, timeframe=payload.timeframe
                )
            },
        )

    @router.post("/api/market-sim/data/import")
    def import_dataset(payload: ImportDatasetRequest) -> dict:
        args = {
            "path": payload.path,
            "symbol": payload.symbol,
            "timeframe": payload.timeframe,
            "seal": payload.seal,
            "role": payload.role,
            "provider": payload.provider,
        }
        return _mutate(
            "market_sim.data.import",
            args,
            fallback=lambda: service.import_market_dataset(
                payload.path,
                symbol=payload.symbol,
                timeframe=payload.timeframe,
                seal=payload.seal,
                role=payload.role,
                provider=payload.provider,
            ),
        )

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
        return _mutate(
            "market_sim.dataset.seal",
            {"dataset_id": dataset_id, "version": version, "role": body.role},
            idempotency_key=f"market_sim:seal:{dataset_id}:{version}:{body.role}",
            fallback=lambda: {
                "dataset": service.seal_market_dataset(dataset_id, version, role=body.role)
            },
        )

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
        args = {
            "name": payload.name,
            "description": payload.description,
            "tags": payload.tags,
            "parameters": payload.parameters,
            "entry_rules": payload.entryRules,
            "exit_rules": payload.exitRules,
            "risk_rules": payload.riskRules,
            "required_timeframes": payload.requiredTimeframes,
            "brain_dependencies": payload.brainDependencies,
            "changelog": payload.changelog,
            "dsl_spec": payload.dslSpec,
            "family": payload.family,
        }
        return _mutate(
            "market_sim.strategy.create",
            args,
            fallback=lambda: service.create_strategy(
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
                dsl_spec=payload.dslSpec,
                family=payload.family,
            ),
        )

    @router.post("/api/market-sim/strategies/validate")
    def validate_strategy(payload: StrategyValidateRequest) -> dict:
        return _mutate(
            "market_sim.strategy.validate",
            {"dsl_spec": payload.dslSpec},
            idempotency_key=f"market_sim:validate:{uuid.uuid4().hex[:10]}",
            fallback=lambda: service.validate_strategy_dsl(payload.dslSpec),
        )

    @router.get("/api/market-sim/strategies/families")
    def list_strategy_families() -> dict:
        try:
            return service.list_strategy_families()
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/strategies/families/{family}/template")
    def strategy_family_template(
        family: str,
        symbol: str = Query("BTCUSDT"),
        timeframe: str = Query("1h"),
    ) -> dict:
        try:
            return service.strategy_family_template(family, symbol=symbol, timeframe=timeframe)
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
        args = {
            "strategy_id": strategy_id,
            "parameters": payload.parameters,
            "entry_rules": payload.entryRules,
            "exit_rules": payload.exitRules,
            "risk_rules": payload.riskRules,
            "required_timeframes": payload.requiredTimeframes,
            "brain_dependencies": payload.brainDependencies,
            "changelog": payload.changelog,
            "name": payload.name,
            "description": payload.description,
            "tags": payload.tags,
            "dsl_spec": payload.dslSpec,
        }
        return _mutate(
            "market_sim.strategy.version",
            args,
            fallback=lambda: service.version_strategy(
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
                dsl_spec=payload.dslSpec,
            ),
        )

    @router.post("/api/market-sim/strategies/{strategy_id}/fork")
    def fork_strategy(strategy_id: str, payload: StrategyForkRequest | None = None) -> dict:
        body = payload or StrategyForkRequest()
        return _mutate(
            "market_sim.strategy.fork",
            {"strategy_id": strategy_id, "name": body.name},
            fallback=lambda: service.fork_strategy(strategy_id, name=body.name),
        )

    @router.post("/api/market-sim/strategies/{strategy_id}/archive")
    def archive_strategy(strategy_id: str) -> dict:
        return _mutate(
            "market_sim.strategy.archive",
            {"strategy_id": strategy_id},
            idempotency_key=f"market_sim:archive:{strategy_id}",
            fallback=lambda: {"strategy": service.archive_strategy(strategy_id)},
        )

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
        args = {
            "source_id": payload.sourceId,
            "strategy_id": payload.strategyId,
            "strategy_version": payload.strategyVersion,
            "start_ts": payload.startTs,
            "end_ts": payload.endTs,
            "seed": payload.seed,
            "speed": payload.speed,
            "initial_cash": payload.initialCash,
            "fee_bps": payload.feeBps,
            "slippage_bps": payload.slippageBps,
            "max_position_pct": payload.maxPositionPct,
            "max_drawdown_pct": payload.maxDrawdownPct,
            "per_trade_risk_pct": payload.perTradeRiskPct,
            "agents": payload.agents,
            "deliberation_every_n": payload.deliberationEveryN,
            "stochastic_slippage": payload.stochasticSlippage,
            "game_mode": payload.gameMode,
            "metadata": payload.metadata,
        }
        return _mutate(
            "market_sim.run.create",
            args,
            fallback=lambda: {
                "run": service.create_run(
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
                    game_mode=payload.gameMode,
                    metadata=payload.metadata,
                )
            },
        )

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
        return _mutate(
            "market_sim.run.start",
            {"run_id": run_id},
            run_id=run_id,
            idempotency_key=f"market_sim:run.start:{run_id}",
            fallback=lambda: {"run": service.start_run(run_id)},
        )

    @router.post("/api/market-sim/runs/{run_id}/pause")
    def pause_run(run_id: str) -> dict:
        return _mutate(
            "market_sim.run.pause",
            {"run_id": run_id},
            run_id=run_id,
            idempotency_key=f"market_sim:run.pause:{run_id}",
            fallback=lambda: {"run": service.pause_run(run_id)},
        )

    @router.post("/api/market-sim/runs/{run_id}/step")
    def step_run(run_id: str) -> dict:
        return _mutate(
            "market_sim.run.step",
            {"run_id": run_id},
            run_id=run_id,
            fallback=lambda: {"run": service.step_run(run_id)},
        )

    @router.post("/api/market-sim/runs/{run_id}/stop")
    def stop_run(run_id: str) -> dict:
        return _mutate(
            "market_sim.run.stop",
            {"run_id": run_id},
            run_id=run_id,
            idempotency_key=f"market_sim:run.stop:{run_id}",
            fallback=lambda: {"run": service.stop_run(run_id)},
        )

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
        args = {
            "symbol": payload.symbol,
            "strategy_id": payload.strategyId,
            "strategy_version": payload.strategyVersion,
            "broker_id": payload.brokerId,
            "provider_id": payload.providerId,
            "initial_cash": payload.initialCash,
        }
        return _mutate(
            "market_sim.paper.session.start",
            args,
            fallback=lambda: {
                "session": service.start_paper_session(
                    symbol=payload.symbol,
                    strategy_id=payload.strategyId,
                    strategy_version=payload.strategyVersion,
                    broker_id=payload.brokerId,
                    provider_id=payload.providerId,
                    initial_cash=payload.initialCash,
                )
            },
        )

    @router.get("/api/market-sim/paper/sessions/{session_id}")
    def get_paper(session_id: str) -> dict:
        try:
            return {"session": service.paper_session_state(session_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/paper/sessions/{session_id}/orders")
    def paper_order(session_id: str, payload: PaperOrderRequest) -> dict:
        args = {
            "session_id": session_id,
            "side": payload.side,
            "qty": payload.qty,
            "client_order_id": payload.clientOrderId,
        }
        idem = payload.clientOrderId or f"market_sim:paper.order:{session_id}:{uuid.uuid4().hex[:10]}"
        return _mutate(
            "market_sim.paper.order.place",
            args,
            idempotency_key=f"market_sim:paper.order:{idem}",
            fallback=lambda: service.paper_place_order(
                session_id,
                side=payload.side,
                qty=payload.qty,
                client_order_id=payload.clientOrderId,
            ),
        )

    @router.post("/api/market-sim/paper/sessions/{session_id}/kill-switch")
    def paper_kill(session_id: str, armed: bool = True) -> dict:
        return _mutate(
            "market_sim.paper.kill_switch",
            {"session_id": session_id, "armed": armed},
            idempotency_key=f"market_sim:paper.kill:{session_id}:{armed}",
            fallback=lambda: {"session": service.paper_kill_switch(session_id, armed=armed)},
        )

    # --- Experiments ---

    @router.get("/api/market-sim/experiments")
    def list_experiments(strategy_id: str | None = Query(None, alias="strategyId")) -> dict:
        try:
            return {"experiments": service.list_experiments(strategy_id=strategy_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/experiments")
    def propose_experiment(payload: ExperimentPropose) -> dict:
        args = {
            "strategy_id": payload.strategyId,
            "hypothesis": payload.hypothesis,
            "proposer_agent_id": payload.proposerAgentId,
            "source_id": payload.sourceId,
            "acceptance_criteria": payload.acceptanceCriteria,
            "seed": payload.seed,
            "config": payload.config,
        }
        return _mutate(
            "market_sim.experiment.propose",
            args,
            fallback=lambda: {
                "trial": service.propose_experiment(
                    strategy_id=payload.strategyId,
                    hypothesis=payload.hypothesis,
                    proposer_agent_id=payload.proposerAgentId,
                    source_id=payload.sourceId,
                    acceptance_criteria=payload.acceptanceCriteria,
                    seed=payload.seed,
                    config=payload.config,
                )
            },
        )

    @router.post("/api/market-sim/experiments/{trial_id}/complete")
    def complete_experiment(trial_id: str, payload: ExperimentComplete) -> dict:
        return _mutate(
            "market_sim.experiment.complete",
            {
                "trial_id": trial_id,
                "metrics": payload.metrics,
                "strategy_version": payload.strategyVersion,
                "run_id": payload.runId,
                "run_ids": payload.runIds,
            },
            idempotency_key=f"market_sim:experiment.complete:{trial_id}",
            fallback=lambda: {
                "trial": service.complete_experiment(
                    trial_id,
                    metrics=payload.metrics,
                    strategy_version=payload.strategyVersion,
                    run_id=payload.runId,
                    run_ids=payload.runIds,
                )
            },
        )

    @router.post("/api/market-sim/demos/run")
    def run_demo(payload: DemoRequest) -> dict:
        return _mutate(
            "market_sim.demo.run",
            {"family": payload.family, "bars_limit": payload.barsLimit},
            fallback=lambda: service.run_market_demo(
                family=payload.family, bars_limit=payload.barsLimit
            ),
        )

    @router.get("/api/market-sim/live-trading")
    def live_trading_status() -> dict:
        return service.live_guard.public_status()

    return router
