"""HTTP surface for the Trading Lab, mounted under ``/api/trading/lab``.

Every endpoint here maps to a real operation on the service. There is no endpoint that exists
only so a button has something to call: if a capability is missing, the endpoint returns the
reason instead of a plausible-looking empty result.

The legacy ``/api/trading/*`` endpoints are untouched, so the existing bot, its dashboard and
its stored data keep working exactly as before.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(tags=["trading-lab"])


class InstrumentInput(BaseModel):
    model_config = {"extra": "allow"}

    instrument_id: str | None = None
    family: str
    venue: str
    symbol: str
    base_currency: str
    quote_currency: str


class ImportTextInput(BaseModel):
    instrument_id: str
    timeframe: str = "1h"
    text: str = Field(min_length=1, max_length=80_000_000)
    name: str = ""
    source_reference: str = ""
    licence: str = "operator supplied"
    availability_delay_seconds: int = Field(default=0, ge=0, le=86_400)
    assume_timezone: str = "UTC"


class DownloadInput(BaseModel):
    provider_id: str
    instrument_id: str
    timeframe: str = "1h"
    start: str | None = None
    end: str | None = None
    limit: int = Field(default=5000, ge=1, le=200_000)


class SyntheticInput(BaseModel):
    instrument_id: str
    timeframe: str = "1h"
    start: str
    end: str
    seed: int = 20240101
    regime: str = "mixed"
    start_price: float = 100.0


class SplitInput(BaseModel):
    development: float = Field(default=0.6, gt=0.1, lt=0.9)
    validation: float = Field(default=0.2, gt=0.02, lt=0.8)
    embargo_seconds: int = Field(default=0, ge=0, le=31_536_000)


class CorporateActionsInput(BaseModel):
    actions: list[dict[str, Any]] = Field(min_length=1, max_length=5000)


class StrategyInput(BaseModel):
    model_config = {"extra": "allow"}

    name: str
    family: str
    instruments: list[str] = Field(min_length=1, max_length=40)


class PromotionInput(BaseModel):
    strategy_id: str
    version: int = 1
    target_state: str
    requested_by: str = "operator"
    evaluation_report_id: str | None = None
    justification: str = ""


class ExperimentInput(BaseModel):
    model_config = {"extra": "allow"}

    title: str
    strategy_family: str
    dataset_ids: list[str] = Field(default_factory=list)
    instruments: list[str] = Field(min_length=1, max_length=40)


class BacktestInput(BaseModel):
    model_config = {"extra": "allow"}

    strategy_id: str | None = None
    version: int | None = None
    strategy: dict[str, Any] | None = None
    split: str = "development"


class EvaluationInput(BaseModel):
    model_config = {"extra": "allow"}

    strategy_id: str
    version: int | None = None
    split: str = "validation"
    folds: int = Field(default=4, ge=2, le=20)


class ControlInput(BaseModel):
    action: str
    value: float | None = None


class RewindInput(BaseModel):
    event_time: str


class AgentRunInput(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    roles: list[str] | None = None
    model: str | None = None
    facts: dict[str, Any] | None = None
    strategy_id: str | None = None
    experiment_id: str | None = None


class TrainModelInput(BaseModel):
    name: str
    instrument_id: str
    timeframe: str = "1h"
    kind: str = "ridge"
    train_fraction: float = Field(default=0.7, gt=0.3, lt=0.95)
    embargo_rows: int = Field(default=5, ge=0, le=500)
    alpha: float = Field(default=1.0, gt=0)
    seed: int = 7


class LearningCycleInput(BaseModel):
    model_config = {"extra": "allow"}

    objective: str = ""
    autonomy_level: str | None = None
    parent_strategy_ids: list[str] = Field(default_factory=list)
    budget: dict[str, Any] | None = None


class IngestExperiencesInput(BaseModel):
    run_id: str | None = None
    experiment_id: str | None = None
    limit: int = Field(default=5000, ge=1, le=50_000)


class ChampionCompareInput(BaseModel):
    strategy_id: str
    version: int | None = None


class SettingsInput(BaseModel):
    model_config = {"extra": "allow"}

    cost_model: dict[str, Any] | None = None
    risk_limits: dict[str, Any] | None = None
    providers: dict[str, Any] | None = None
    resources: dict[str, Any] | None = None
    agent_models: dict[str, Any] | None = None
    learning: dict[str, Any] | None = None


def mount_trading_lab_routes(get_service: Callable[[], Any]) -> APIRouter:
    """Bind the routes to a lazily resolved service instance."""

    def service() -> Any:
        instance = get_service()
        if instance is None:
            raise HTTPException(status_code=503, detail="trading_lab_unavailable: the service failed to initialise")
        return instance

    # --- overview ----------------------------------------------------------------

    @router.get("/trading/lab/overview")
    async def lab_overview() -> dict[str, Any]:
        return service().overview()

    @router.get("/trading/lab/capabilities")
    async def lab_capabilities() -> dict[str, Any]:
        return service().capabilities()

    @router.get("/trading/lab/data-gaps")
    async def lab_data_gaps() -> dict[str, Any]:
        return service().data_gaps()

    @router.get("/trading/lab/jobs")
    async def lab_jobs() -> dict[str, Any]:
        return service().jobs_snapshot()

    # --- instruments -------------------------------------------------------------

    @router.get("/trading/lab/instruments")
    async def list_instruments(family: str | None = None, venue: str | None = None) -> dict[str, Any]:
        return {"instruments": service().list_instruments(family=family, venue=venue)}

    @router.post("/trading/lab/instruments")
    async def create_instrument(payload: InstrumentInput) -> dict[str, Any]:
        try:
            return service().create_instrument(payload.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.delete("/trading/lab/instruments/{instrument_id:path}")
    async def delete_instrument(instrument_id: str) -> dict[str, Any]:
        return service().delete_instrument(instrument_id)

    # --- datasets ----------------------------------------------------------------

    @router.get("/trading/lab/datasets")
    async def list_datasets(instrument_id: str | None = None, limit: int = 200) -> dict[str, Any]:
        return {"datasets": service().list_datasets(instrument_id=instrument_id, limit=limit)}

    @router.get("/trading/lab/datasets/{dataset_id}")
    async def dataset_detail(dataset_id: str) -> dict[str, Any]:
        detail = service().dataset_detail(dataset_id)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"unknown_dataset:{dataset_id}")
        return detail

    @router.get("/trading/lab/datasets/{dataset_id}/preview")
    async def dataset_preview(dataset_id: str, limit: int = 300) -> dict[str, Any]:
        return service().dataset_preview(dataset_id, limit=limit)

    @router.get("/trading/lab/datasets/{dataset_id}/gaps")
    async def dataset_gaps(dataset_id: str) -> dict[str, Any]:
        return service().dataset_gaps(dataset_id)

    @router.post("/trading/lab/datasets/import")
    async def import_dataset(payload: ImportTextInput) -> dict[str, Any]:
        try:
            return service().import_dataset_text(payload.model_dump())
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/trading/lab/datasets/download")
    async def download_dataset(payload: DownloadInput) -> dict[str, Any]:
        try:
            return service().download_dataset(payload.model_dump())
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/trading/lab/datasets/synthetic")
    async def synthetic_dataset(payload: SyntheticInput) -> dict[str, Any]:
        try:
            return service().generate_synthetic_dataset(payload.model_dump())
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/trading/lab/datasets/{dataset_id}/freeze")
    async def freeze_dataset(dataset_id: str) -> dict[str, Any]:
        record = service().freeze_dataset(dataset_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"unknown_dataset:{dataset_id}")
        return {"dataset": record}

    @router.put("/trading/lab/datasets/{dataset_id}/splits")
    async def set_splits(dataset_id: str, payload: SplitInput) -> dict[str, Any]:
        try:
            record = service().set_dataset_splits(dataset_id, payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if record is None:
            raise HTTPException(status_code=404, detail=f"unknown_dataset:{dataset_id}")
        return {"dataset": record}

    @router.post("/trading/lab/datasets/{dataset_id}/corporate-actions")
    async def corporate_actions(dataset_id: str, payload: CorporateActionsInput) -> dict[str, Any]:
        try:
            return service().add_corporate_actions(dataset_id, payload.actions)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/trading/lab/providers")
    async def providers() -> dict[str, Any]:
        return service().providers()

    # --- strategies --------------------------------------------------------------

    @router.get("/trading/lab/strategies")
    async def list_strategies(status: str | None = None, limit: int = 200) -> dict[str, Any]:
        return {"strategies": service().list_strategies(status=status, limit=limit)}

    @router.get("/trading/lab/strategy-families")
    async def strategy_families() -> dict[str, Any]:
        return service().strategy_families()

    @router.get("/trading/lab/strategies/{strategy_id}")
    async def strategy_detail(strategy_id: str) -> dict[str, Any]:
        try:
            return service().strategy_detail(strategy_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/trading/lab/strategies")
    async def create_strategy(payload: StrategyInput) -> dict[str, Any]:
        try:
            return service().create_strategy(payload.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/trading/lab/strategies/{strategy_id}/versions")
    async def add_version(strategy_id: str, payload: StrategyInput) -> dict[str, Any]:
        try:
            return service().add_strategy_version(strategy_id, payload.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/trading/lab/strategies/promote")
    async def promote(payload: PromotionInput) -> dict[str, Any]:
        return service().promote_strategy(payload.model_dump())

    # --- experiments -------------------------------------------------------------

    @router.get("/trading/lab/experiments")
    async def list_experiments(status: str | None = None, limit: int = 100) -> dict[str, Any]:
        return {"experiments": service().store.list_experiments(status=status, limit=limit)}

    @router.post("/trading/lab/experiments")
    async def create_experiment(payload: ExperimentInput) -> dict[str, Any]:
        try:
            return service().create_experiment(payload.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/trading/lab/experiments/{experiment_id}")
    async def experiment_detail(experiment_id: str) -> dict[str, Any]:
        return service().experiment_detail(experiment_id)

    @router.post("/trading/lab/experiments/{experiment_id}/start")
    async def start_experiment(experiment_id: str, strategy_id: str | None = None) -> dict[str, Any]:
        return service().start_experiment(experiment_id, strategy_id=strategy_id)

    # --- runs --------------------------------------------------------------------

    @router.get("/trading/lab/runs")
    async def list_runs(status: str | None = None, mode: str | None = None, limit: int = 100) -> dict[str, Any]:
        return {"runs": service().store.list_runs(status=status, mode=mode, limit=limit)}

    @router.post("/trading/lab/runs")
    async def start_run(payload: BacktestInput) -> dict[str, Any]:
        try:
            return service().start_backtest(payload.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/trading/lab/runs/{run_id}")
    async def run_detail(run_id: str) -> dict[str, Any]:
        detail = service().run_detail(run_id)
        if "error" in detail:
            raise HTTPException(status_code=404, detail=detail["error"])
        return detail

    @router.get("/trading/lab/runs/{run_id}/orders")
    async def run_orders(run_id: str, status: str | None = None, limit: int = 200) -> dict[str, Any]:
        return {"orders": service().run_orders(run_id, status=status, limit=limit)}

    @router.get("/trading/lab/runs/{run_id}/fills")
    async def run_fills(run_id: str, limit: int = 500) -> dict[str, Any]:
        return {"fills": service().run_fills(run_id, limit=limit)}

    @router.get("/trading/lab/runs/{run_id}/ledger")
    async def run_ledger(run_id: str, limit: int = 1000) -> dict[str, Any]:
        return service().run_ledger(run_id, limit=limit)

    @router.get("/trading/lab/runs/{run_id}/decisions")
    async def run_decisions(run_id: str, limit: int = 200) -> dict[str, Any]:
        return {"decisions": service().run_decisions(run_id, limit=limit)}

    @router.get("/trading/lab/runs/{run_id}/snapshots")
    async def run_snapshots(run_id: str, limit: int = 500) -> dict[str, Any]:
        return {"snapshots": service().run_snapshots(run_id, limit=limit)}

    @router.post("/trading/lab/runs/{run_id}/control")
    async def control_run(run_id: str, payload: ControlInput) -> dict[str, Any]:
        return service().control_run(run_id, payload.action, value=payload.value)

    @router.post("/trading/lab/runs/{run_id}/rewind")
    async def rewind_run(run_id: str, payload: RewindInput) -> dict[str, Any]:
        return service().rewind_run(run_id, payload.event_time)

    @router.get("/trading/lab/runs/{run_id}/reproducibility")
    async def reproducibility(run_id: str) -> dict[str, Any]:
        return service().reproducibility(run_id)

    @router.get("/trading/lab/compare")
    async def compare(left: str, right: str) -> dict[str, Any]:
        return service().compare(left, right)

    # --- evaluation --------------------------------------------------------------

    @router.get("/trading/lab/evaluations")
    async def list_evaluations(strategy_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        return {"evaluations": service().list_evaluations(strategy_id=strategy_id, limit=limit)}

    @router.post("/trading/lab/evaluations")
    async def start_evaluation(payload: EvaluationInput) -> dict[str, Any]:
        return service().start_evaluation(payload.model_dump(exclude_none=True))

    @router.get("/trading/lab/evaluations/{report_id}")
    async def evaluation_detail(report_id: str) -> dict[str, Any]:
        record = service().evaluation_detail(report_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"unknown_report:{report_id}")
        return record

    # --- portfolio, risk and orders ----------------------------------------------

    @router.get("/trading/lab/portfolio")
    async def portfolio(run_id: str | None = None) -> dict[str, Any]:
        return service().portfolio_state(run_id)

    @router.post("/trading/lab/risk/preview")
    async def risk_preview(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return service().risk_preview(payload)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/trading/lab/orders/preview")
    async def order_preview(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return service().order_preview(payload)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # --- models ------------------------------------------------------------------

    @router.get("/trading/lab/models")
    async def list_models(kind: str | None = None, limit: int = 100) -> dict[str, Any]:
        return {"models": service().list_models(kind=kind, limit=limit)}

    @router.post("/trading/lab/models/train")
    async def train_model(payload: TrainModelInput) -> dict[str, Any]:
        return service().train_model_job(payload.model_dump())

    # --- agents ------------------------------------------------------------------

    @router.get("/trading/lab/agents/roles")
    async def agent_roles() -> dict[str, Any]:
        return service().agent_roles()

    @router.get("/trading/lab/agents/sessions")
    async def agent_sessions(limit: int = 50) -> dict[str, Any]:
        return {"sessions": service().agent_sessions(limit=limit)}

    @router.post("/trading/lab/agents/run")
    async def run_agents(payload: AgentRunInput) -> dict[str, Any]:
        return await service().run_agent_pipeline(payload.model_dump(exclude_none=True))

    # --- learning / evolution ----------------------------------------------------

    @router.get("/trading/lab/learning/overview")
    async def learning_overview() -> dict[str, Any]:
        return service().learning_overview()

    @router.post("/trading/lab/learning/experiences/ingest")
    async def ingest_experiences(payload: IngestExperiencesInput) -> dict[str, Any]:
        return service().ingest_experiences(payload.model_dump())

    @router.get("/trading/lab/learning/experiences")
    async def list_experiences(
        strategy_id: str | None = None,
        strategy_family: str | None = None,
        instrument_id: str | None = None,
        timeframe: str | None = None,
        regime_key: str | None = None,
        split: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        return service().list_experiences(
            strategy_id=strategy_id,
            strategy_family=strategy_family,
            instrument_id=instrument_id,
            timeframe=timeframe,
            regime_key=regime_key,
            split=split,
            limit=limit,
            offset=offset,
        )

    @router.get("/trading/lab/learning/beliefs")
    async def list_beliefs(
        status: str | None = None,
        strategy_family: str | None = None,
        instrument_id: str | None = None,
        timeframe: str | None = None,
        regime_key: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return service().list_beliefs(
            status=status,
            strategy_family=strategy_family,
            instrument_id=instrument_id,
            timeframe=timeframe,
            regime_key=regime_key,
            limit=limit,
        )

    @router.get("/trading/lab/learning/findings")
    async def list_findings(cycle_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        return service().list_findings(cycle_id=cycle_id, limit=limit)

    @router.get("/trading/lab/learning/lineage")
    async def list_lineage(strategy_id: str | None = None, limit: int = 200) -> dict[str, Any]:
        return service().list_lineage(strategy_id=strategy_id, limit=limit)

    @router.get("/trading/lab/learning/candidates")
    async def list_candidates(cycle_id: str | None = None, strategy_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        return service().list_candidates(cycle_id=cycle_id, strategy_id=strategy_id, limit=limit)

    @router.get("/trading/lab/learning/champions")
    async def list_champions(limit: int = 50) -> dict[str, Any]:
        return service().list_champions(limit=limit)

    @router.post("/trading/lab/learning/champions/compare")
    async def compare_champion(payload: ChampionCompareInput) -> dict[str, Any]:
        return service().compare_champion(payload.model_dump())

    @router.get("/trading/lab/learning/cycles")
    async def list_learning_cycles(limit: int = 50) -> dict[str, Any]:
        return service().list_learning_cycles(limit=limit)

    @router.get("/trading/lab/learning/cycles/{cycle_id}")
    async def get_learning_cycle(cycle_id: str) -> dict[str, Any]:
        cycle = service().learning_cycle(cycle_id)
        if cycle is None:
            raise HTTPException(status_code=404, detail=f"unknown_learning_cycle:{cycle_id}")
        return cycle

    @router.post("/trading/lab/learning/cycles")
    async def start_learning_cycle(payload: LearningCycleInput) -> dict[str, Any]:
        return service().start_learning_cycle(payload.model_dump(exclude_none=True))

    # --- settings ----------------------------------------------------------------

    @router.get("/trading/lab/settings")
    async def get_settings() -> dict[str, Any]:
        return service().settings()

    @router.put("/trading/lab/settings")
    async def put_settings(payload: SettingsInput) -> dict[str, Any]:
        try:
            return service().save_settings(payload.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return router


__all__ = ["mount_trading_lab_routes", "router"]
