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
    engine: str | None = None
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


class PaperForwardStart(BaseModel):
    strategyId: str | None = None
    strategyVersion: int | None = None


class PaperForwardTick(BaseModel):
    side: str | None = None


class PaperReconcileRequest(BaseModel):
    shadowFills: list[dict[str, Any]] | None = None


class PaperDriftRequest(BaseModel):
    paperEquity: list[float]
    backtestEquity: list[float]
    bandPct: float = 5.0


class RiskResetRequest(BaseModel):
    humanToken: str
    strategyId: str | None = None


class RiskLoosenRequest(BaseModel):
    patch: dict[str, Any]
    approvalId: str | None = None


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


class StrategyPromoteRequest(BaseModel):
    toStatus: str
    reason: str | None = None
    decidedBy: str | None = "operator"
    evidence: dict[str, Any] | None = None


class CampaignCreate(BaseModel):
    strategyId: str
    hypothesis: str
    proposerAgentId: str = "human"
    sourceId: str | None = None
    seed: int = 42
    config: dict[str, Any] | None = None
    acceptanceCriteria: dict[str, Any] | None = None
    nBars: int | None = None


class CampaignAdvance(BaseModel):
    trialId: str | None = None


class GymEpisodeCreate(BaseModel):
    sourceId: str | None = None
    barsPath: str | None = None
    curriculumStage: str = "trend"
    seed: int = 42
    startIndex: int = 0
    endIndex: int | None = None
    initialCash: float = 100_000.0
    datasetId: str | None = None
    datasetVersion: str | None = None


class GymStepRequest(BaseModel):
    action: str = "HOLD"


class ScorecardCreate(BaseModel):
    agentId: str
    equity: list[float]
    agentVersion: str = "v1"
    regime: str = "all"
    year: int | None = None
    violations: dict[str, int] | None = None
    tokenCost: int = 0
    latencyMs: float = 0.0
    nEpisodes: int = 1
    timeframe: str = "1h"


class ReadinessSet(BaseModel):
    level: str
    measurement: str = "UNMEASURED"
    reason: str | None = None
    evidence: dict[str, Any] | None = None


class TrajectoryExportRequest(BaseModel):
    destPath: str | None = None
    sealedWindows: list[dict[str, Any]] | None = None


class SimRealGapRequest(BaseModel):
    simFills: list[dict[str, Any]]
    paperFills: list[dict[str, Any]]
    calibrationSourceIds: list[str] | None = None
    evaluationSourceIds: list[str] | None = None


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

    @router.post("/api/market-sim/strategies/{strategy_id}/promote")
    def promote_strategy(strategy_id: str, payload: StrategyPromoteRequest) -> dict:
        return _mutate(
            "market_sim.strategy.promote",
            {
                "strategy_id": strategy_id,
                "to_status": payload.toStatus,
                "reason": payload.reason,
                "decided_by": payload.decidedBy,
                "evidence": payload.evidence,
            },
            idempotency_key=f"market_sim:promote:{strategy_id}:{payload.toStatus}",
            fallback=lambda: {
                "strategy": service.promote_strategy(
                    strategy_id,
                    to_status=payload.toStatus,
                    reason=payload.reason or "",
                    decided_by=payload.decidedBy or "operator",
                    evidence=payload.evidence,
                )
            },
        )

    @router.get("/api/market-sim/strategies/{strategy_id}/memories")
    def recall_strategy_memories(
        strategy_id: str,
        as_of: str = Query(..., description="Causal recall boundary (ISO timestamp)"),
        limit: int = Query(20, ge=1, le=200),
    ) -> dict:
        try:
            return {
                "memories": service.recall_strategy_memories(
                    strategy_id=strategy_id, as_of_ts=as_of, limit=limit
                ),
                "as_of": as_of,
            }
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/strategies/{strategy_id}/lessons")
    def list_strategy_lessons(
        strategy_id: str,
        as_of: str = Query(..., description="Causal recall boundary (ISO timestamp)"),
        limit: int = Query(20, ge=1, le=200),
    ) -> dict:
        try:
            return {
                "lessons": service.list_strategy_lessons(
                    strategy_id=strategy_id, as_of_ts=as_of, limit=limit
                ),
                "as_of": as_of,
            }
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

    @router.get("/api/market-sim/run-builder")
    def run_builder() -> dict:
        try:
            return service.run_builder_options()
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/runs")
    def create_run(payload: RunCreate) -> dict:
        meta = dict(payload.metadata or {})
        if payload.engine:
            meta.setdefault("engine", payload.engine)
        game_mode = payload.gameMode
        if not game_mode and payload.engine in {"multi_agent", "multi", "individual_competition"}:
            game_mode = "individual_competition"
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
            "game_mode": game_mode,
            "metadata": meta,
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
                    game_mode=game_mode,
                    metadata=meta,
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
            # G32: GET must not refresh quotes / write session state.
            return {"session": service.get_paper_session_readonly(session_id)}
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

    # --- Paper forward / risk / reconcile / audit (T9) ---

    @router.post("/api/market-sim/paper/sessions/{session_id}/forward")
    def start_paper_forward(session_id: str, payload: PaperForwardStart | None = None) -> dict:
        body = payload or PaperForwardStart()
        return _mutate(
            "market_sim.paper.forward.start",
            {
                "session_id": session_id,
                "strategy_id": body.strategyId,
                "strategy_version": body.strategyVersion,
            },
            fallback=lambda: {
                "runner": service.start_paper_forward(
                    session_id,
                    strategy_id=body.strategyId,
                    strategy_version=body.strategyVersion,
                )
            },
        )

    @router.get("/api/market-sim/paper/forward/{runner_id}")
    def get_paper_forward(runner_id: str) -> dict:
        try:
            return {"runner": service.get_paper_forward(runner_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/paper/forward/{runner_id}/tick")
    def paper_forward_tick(runner_id: str, payload: PaperForwardTick | None = None) -> dict:
        body = payload or PaperForwardTick()
        return _mutate(
            "market_sim.paper.forward.tick",
            {"runner_id": runner_id, "side": body.side},
            fallback=lambda: service.paper_forward_tick(runner_id, side=body.side),
        )

    @router.post("/api/market-sim/paper/forward/{runner_id}/pause")
    def paper_forward_pause(runner_id: str) -> dict:
        return _mutate(
            "market_sim.paper.forward.pause",
            {"runner_id": runner_id},
            fallback=lambda: {"runner": service.paper_forward_pause(runner_id)},
        )

    @router.post("/api/market-sim/paper/forward/{runner_id}/resume")
    def paper_forward_resume(runner_id: str) -> dict:
        return _mutate(
            "market_sim.paper.forward.resume",
            {"runner_id": runner_id},
            fallback=lambda: {"runner": service.paper_forward_resume(runner_id)},
        )

    @router.post("/api/market-sim/paper/sessions/{session_id}/reconcile")
    def paper_reconcile(session_id: str, payload: PaperReconcileRequest | None = None) -> dict:
        body = payload or PaperReconcileRequest()
        return _mutate(
            "market_sim.paper.reconcile",
            {"session_id": session_id, "shadow_fills": body.shadowFills},
            fallback=lambda: {
                "report": service.reconcile_paper_session(
                    session_id, shadow_fills=body.shadowFills
                )
            },
        )

    @router.post("/api/market-sim/paper/drift")
    def paper_drift(payload: PaperDriftRequest) -> dict:
        return _mutate(
            "market_sim.paper.drift",
            {
                "paper_equity": payload.paperEquity,
                "backtest_equity": payload.backtestEquity,
                "band_pct": payload.bandPct,
            },
            fallback=lambda: {
                "drift": service.compute_paper_drift(
                    paper_equity=payload.paperEquity,
                    backtest_equity=payload.backtestEquity,
                    band_pct=payload.bandPct,
                )
            },
        )

    @router.get("/api/market-sim/risk")
    def risk_status() -> dict:
        try:
            return {"risk": service.risk_engine_status()}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/risk/reset")
    def risk_reset(payload: RiskResetRequest) -> dict:
        return _mutate(
            "market_sim.risk.reset",
            {"human_token": payload.humanToken, "strategy_id": payload.strategyId},
            fallback=lambda: {
                "kill": service.risk_human_reset(
                    human_token=payload.humanToken, strategy_id=payload.strategyId
                )
            },
        )

    @router.post("/api/market-sim/risk/loosen")
    def risk_loosen(payload: RiskLoosenRequest) -> dict:
        return _mutate(
            "market_sim.risk.loosen",
            {"patch": payload.patch, "approval_id": payload.approvalId},
            fallback=lambda: {
                "limits": service.risk_loosen_limits(
                    payload.patch, approval_id=payload.approvalId
                )
            },
        )

    @router.get("/api/market-sim/audit/verify")
    def audit_verify() -> dict:
        try:
            return service.verify_trading_audit()
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.get("/api/market-sim/security-posture")
    def security_posture() -> dict:
        try:
            return service.security_posture()
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

    # --- Research campaigns (T7 / G25) ---

    @router.get("/api/market-sim/campaigns")
    def list_campaigns(
        strategy_id: str | None = Query(None, alias="strategyId"),
        status: str | None = Query(None),
        limit: int = Query(100, ge=1, le=500),
    ) -> dict:
        try:
            return {
                "campaigns": service.list_research_campaigns(
                    strategy_id=strategy_id, status=status, limit=limit
                )
            }
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/campaigns")
    def create_campaign(payload: CampaignCreate) -> dict:
        return _mutate(
            "market_sim.campaign.create",
            {
                "strategy_id": payload.strategyId,
                "hypothesis": payload.hypothesis,
                "proposer_agent_id": payload.proposerAgentId,
                "source_id": payload.sourceId,
                "seed": payload.seed,
                "config": payload.config,
                "acceptance_criteria": payload.acceptanceCriteria,
                "n_bars": payload.nBars,
            },
            fallback=lambda: {
                "campaign": service.create_research_campaign(
                    strategy_id=payload.strategyId,
                    hypothesis=payload.hypothesis,
                    proposer_agent_id=payload.proposerAgentId,
                    source_id=payload.sourceId,
                    seed=payload.seed,
                    config=payload.config,
                    acceptance_criteria=payload.acceptanceCriteria,
                    n_bars=payload.nBars,
                )
            },
        )

    @router.get("/api/market-sim/campaigns/{campaign_id}")
    def get_campaign(campaign_id: str) -> dict:
        try:
            return {"campaign": service.get_research_campaign(campaign_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/campaigns/{campaign_id}/start")
    def start_campaign(campaign_id: str) -> dict:
        return _mutate(
            "market_sim.campaign.start",
            {"campaign_id": campaign_id},
            idempotency_key=f"market_sim:campaign.start:{campaign_id}",
            fallback=lambda: {"campaign": service.start_research_campaign(campaign_id)},
        )

    @router.post("/api/market-sim/campaigns/{campaign_id}/pause")
    def pause_campaign(campaign_id: str) -> dict:
        return _mutate(
            "market_sim.campaign.pause",
            {"campaign_id": campaign_id},
            idempotency_key=f"market_sim:campaign.pause:{campaign_id}",
            fallback=lambda: {"campaign": service.pause_research_campaign(campaign_id)},
        )

    @router.post("/api/market-sim/campaigns/{campaign_id}/resume")
    def resume_campaign(campaign_id: str) -> dict:
        return _mutate(
            "market_sim.campaign.resume",
            {"campaign_id": campaign_id},
            idempotency_key=f"market_sim:campaign.resume:{campaign_id}",
            fallback=lambda: {"campaign": service.resume_research_campaign(campaign_id)},
        )

    @router.post("/api/market-sim/campaigns/{campaign_id}/advance")
    def advance_campaign(campaign_id: str, payload: CampaignAdvance | None = None) -> dict:
        body = payload or CampaignAdvance()
        return _mutate(
            "market_sim.campaign.advance",
            {"campaign_id": campaign_id, "trial_id": body.trialId},
            fallback=lambda: {
                "campaign": service.advance_research_campaign(
                    campaign_id, trial_id=body.trialId
                )
            },
        )

    @router.post("/api/market-sim/campaigns/{campaign_id}/cancel")
    def cancel_campaign(campaign_id: str) -> dict:
        return _mutate(
            "market_sim.campaign.cancel",
            {"campaign_id": campaign_id},
            idempotency_key=f"market_sim:campaign.cancel:{campaign_id}",
            fallback=lambda: {"campaign": service.cancel_research_campaign(campaign_id)},
        )

    # --- TradingGym / scorecards / readiness / export / gap (T8) ---

    @router.get("/api/market-sim/gym/curriculum")
    def gym_curriculum() -> dict:
        try:
            return {"stages": service.list_gym_curriculum()}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/gym/episodes")
    def create_gym_episode(payload: GymEpisodeCreate) -> dict:
        return _mutate(
            "market_sim.gym.episode.create",
            {
                "source_id": payload.sourceId,
                "bars_path": payload.barsPath,
                "curriculum_stage": payload.curriculumStage,
                "seed": payload.seed,
                "start_index": payload.startIndex,
                "end_index": payload.endIndex,
                "initial_cash": payload.initialCash,
                "dataset_id": payload.datasetId,
                "dataset_version": payload.datasetVersion,
            },
            fallback=lambda: service.create_gym_episode(
                source_id=payload.sourceId,
                bars_path=payload.barsPath,
                curriculum_stage=payload.curriculumStage,
                seed=payload.seed,
                start_index=payload.startIndex,
                end_index=payload.endIndex,
                initial_cash=payload.initialCash,
                dataset_id=payload.datasetId,
                dataset_version=payload.datasetVersion,
            ),
        )

    @router.get("/api/market-sim/gym/episodes/{episode_id}")
    def get_gym_episode(episode_id: str) -> dict:
        try:
            return {"episode": service.get_gym_episode(episode_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/gym/episodes/{episode_id}/step")
    def gym_step(episode_id: str, payload: GymStepRequest) -> dict:
        return _mutate(
            "market_sim.gym.episode.step",
            {"episode_id": episode_id, "action": payload.action},
            fallback=lambda: service.gym_step(episode_id, action=payload.action),
        )

    @router.get("/api/market-sim/gym/scorecards")
    def list_scorecards(
        agent_id: str | None = Query(None, alias="agentId"),
        limit: int = Query(100, ge=1, le=500),
    ) -> dict:
        try:
            return {"scorecards": service.list_agent_scorecards(agent_id=agent_id, limit=limit)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/gym/scorecards")
    def create_scorecard(payload: ScorecardCreate) -> dict:
        return _mutate(
            "market_sim.gym.scorecard.create",
            {
                "agent_id": payload.agentId,
                "equity": payload.equity,
                "agent_version": payload.agentVersion,
                "regime": payload.regime,
                "year": payload.year,
                "violations": payload.violations,
                "token_cost": payload.tokenCost,
                "latency_ms": payload.latencyMs,
                "n_episodes": payload.nEpisodes,
                "timeframe": payload.timeframe,
            },
            fallback=lambda: {
                "scorecard": service.create_agent_scorecard(
                    agent_id=payload.agentId,
                    equity=payload.equity,
                    agent_version=payload.agentVersion,
                    regime=payload.regime,
                    year=payload.year,
                    violations=payload.violations,
                    token_cost=payload.tokenCost,
                    latency_ms=payload.latencyMs,
                    n_episodes=payload.nEpisodes,
                    timeframe=payload.timeframe,
                )
            },
        )

    @router.get("/api/market-sim/gym/readiness/{agent_id}")
    def get_readiness(agent_id: str) -> dict:
        try:
            return {"readiness": service.get_agent_readiness(agent_id)}
        except MarketSimError as exc:
            raise_market_sim_error(exc)

    @router.post("/api/market-sim/gym/readiness/{agent_id}")
    def set_readiness(agent_id: str, payload: ReadinessSet) -> dict:
        return _mutate(
            "market_sim.gym.readiness.set",
            {
                "agent_id": agent_id,
                "level": payload.level,
                "measurement": payload.measurement,
                "reason": payload.reason,
                "evidence": payload.evidence,
            },
            fallback=lambda: {
                "readiness": service.set_agent_readiness(
                    agent_id,
                    level=payload.level,
                    measurement=payload.measurement,
                    reason=payload.reason or "",
                    evidence=payload.evidence,
                )
            },
        )

    @router.post("/api/market-sim/gym/export/{episode_id}")
    def export_trajectory(episode_id: str, payload: TrajectoryExportRequest | None = None) -> dict:
        body = payload or TrajectoryExportRequest()
        return _mutate(
            "market_sim.gym.export",
            {
                "episode_id": episode_id,
                "dest_path": body.destPath,
                "sealed_windows": body.sealedWindows,
            },
            fallback=lambda: {
                "export": service.export_gym_trajectory(
                    episode_id,
                    dest_path=body.destPath,
                    sealed_windows=body.sealedWindows,
                )
            },
        )

    @router.post("/api/market-sim/gym/sim-real-gap")
    def sim_real_gap(payload: SimRealGapRequest) -> dict:
        return _mutate(
            "market_sim.gym.sim_real_gap",
            {
                "sim_fills": payload.simFills,
                "paper_fills": payload.paperFills,
                "calibration_source_ids": payload.calibrationSourceIds,
                "evaluation_source_ids": payload.evaluationSourceIds,
            },
            fallback=lambda: {
                "report": service.create_sim_real_gap_report(
                    sim_fills=payload.simFills,
                    paper_fills=payload.paperFills,
                    calibration_source_ids=payload.calibrationSourceIds,
                    evaluation_source_ids=payload.evaluationSourceIds,
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
