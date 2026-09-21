"""Trading Lab service facade.

The HTTP layer talks only to this class. It owns construction order, keeps the long-running
work on the job queue instead of in request handlers, and is the single place where a run's
reproducibility record is assembled.

Nothing here invents data. When something cannot be done — no dataset, no model loaded, a
provider without credentials, a sealed split already used — the method returns a structured
refusal with the reason, and the UI shows that reason verbatim.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from trading_lab.accounting import Portfolio
from trading_lab.agents import ROLES, AgentContext, AgentTeam, default_pipeline, roles_manifest
from trading_lab.bar_store import BarPartitionStore
from trading_lab.capabilities import capability_matrix
from trading_lab.catalog import MarketDataCatalog, dataset_manifest_digest
from trading_lab.champions import evaluate_challenger, scope_key
from trading_lab.contracts import (
    CostModel,
    DecisionRecord,
    EvaluationReport,
    ExperimentSpec,
    FillEvent,
    InstrumentSpec,
    OrderEvent,
    OrderIntent,
    PortfolioSnapshot,
    RiskLimits,
    StrategySpec,
    stable_hash,
    to_decimal,
    utc_iso,
)
from trading_lab.engine import EngineConfig, SimulationEngine, select_checkpoint_for_rewind, thin_curve
from trading_lab.evaluation import (
    PromotionCriteria,
    RunSummaryInput,
    SIMULATOR_LIMITATIONS,
    compare_runs,
    summarise,
)
from trading_lab.evolution import DEFAULT_BUDGETS
from trading_lab.experience import ingest_resolved_decisions
from trading_lab.instruments import InstrumentRegistry
from trading_lab.jobs import JobHandle, JobQueue
from trading_lab.learning import compact_findings, retrieve_beliefs
from trading_lab.learning_cycle import AUTONOMY_LEVELS, LearningCycleEngine, normalize_autonomy
from trading_lab.models import TrainedModel, train_model
from trading_lab.providers import KNOWN_DATA_GAPS, provider_statuses
from trading_lab.registry import PromotionRequest, StrategyRegistry
from trading_lab.research import ExperimentRunner, experiment_defaults, preregistration_record
from trading_lab.risk import RiskContext, RiskEngine, correlation_groups_from_specs, sanitize_model_risk_payload
from trading_lab.store import TradingLabStore
from trading_lab.strategies import STRATEGY_CLASSES, default_param_space, resolve_family

MODE_LABEL = "SIMULATION / PAPER — no real money, no broker account, no live order"


class StoreSink:
    """Persists everything one run produces, in the order the engine produced it."""

    def __init__(self, store: TradingLabStore, run_id: str, *, progress: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.store = store
        self.run_id = run_id
        self._progress = progress
        self.orders_seen: set[str] = set()

    def on_order(self, record: dict[str, Any]) -> None:
        self.store.persist_order(self.run_id, record)
        self.orders_seen.add(record["order_id"])

    def on_order_event(self, event: OrderEvent) -> None:
        self.store.append_order_event(self.run_id, event)

    def on_fill(self, fill: FillEvent) -> None:
        self.store.append_fill(self.run_id, fill)

    def on_ledger(self, rows: Sequence[dict[str, Any]]) -> None:
        self.store.append_ledger_entries(self.run_id, rows)

    def on_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        self.store.save_snapshot(self.run_id, snapshot)

    def on_checkpoint(self, event_time: str, checkpoint: dict[str, Any]) -> None:
        self.store.save_engine_checkpoint(self.run_id, event_time, checkpoint)

    def on_decision(self, record: DecisionRecord) -> None:
        self.store.save_decision(record)

    def on_decision_outcome(self, decision_id: str, outcome: dict[str, Any]) -> None:
        self.store.attach_decision_outcome(decision_id, outcome)

    def on_progress(self, progress: dict[str, Any]) -> None:
        self.store.update_run(
            self.run_id,
            simulation_time=progress.get("simulation_time"),
            events_processed=progress.get("events_processed", 0),
        )
        if self._progress:
            self._progress(progress)


@dataclass
class LabPaths:
    root: Path

    @property
    def bars(self) -> Path:
        return self.root / "bars"

    @property
    def exports(self) -> Path:
        return self.root / "exports"


class TradingLabService:
    def __init__(
        self,
        database: Any,
        *,
        data_root: str | os.PathLike[str] | None = None,
        chat: Callable[..., Any] | None = None,
        settings_provider: Callable[[], dict[str, Any]] | None = None,
        max_workers: int = 2,
    ) -> None:
        base = Path(data_root) if data_root else Path(__file__).resolve().parent.parent / "data" / "trading_lab"
        self.paths = LabPaths(root=base)
        self.paths.bars.mkdir(parents=True, exist_ok=True)
        self.store = TradingLabStore(database)
        self.store.initialize()
        self.bars = BarPartitionStore(self.paths.bars)
        self.instruments = InstrumentRegistry(self.store)
        self.catalog = MarketDataCatalog(self.store, self.bars, self.instruments)
        self.runner = ExperimentRunner(store=self.store, catalog=self.catalog, registry=self.instruments, bar_store=self.bars)
        self.strategies = StrategyRegistry(self.store)
        self.jobs = JobQueue(self.store, max_workers=max_workers)
        self.chat = chat
        self.settings_provider = settings_provider
        self._register_handlers()
        self.jobs.start()

    # --- overview ----------------------------------------------------------------

    def overview(self) -> dict[str, Any]:
        datasets = self.store.list_datasets(limit=500)
        strategies = self.store.list_strategies(limit=500)
        runs = self.store.list_runs(limit=25)
        experiments = self.store.list_experiments(limit=25)
        evaluations = self.store.list_evaluations(limit=25)
        accounts = self.store.list_paper_accounts()
        settings = self.settings()
        synthetic = [item for item in datasets if item.get("is_synthetic")]
        learning_counts = self.store.learning_overview_counts()
        return {
            "mode": MODE_LABEL,
            "counts": {
                "instruments": len(self.instruments.list()),
                "datasets": len(datasets),
                "frozen_datasets": len([item for item in datasets if item.get("frozen")]),
                "synthetic_datasets": len(synthetic),
                "strategies": len(strategies),
                "experiments": len(experiments),
                "runs": len(self.store.list_runs(limit=500)),
                "evaluations": len(evaluations),
                "experiences": learning_counts.get("experiences", 0),
                "beliefs": learning_counts.get("beliefs", 0),
                "active_learning_cycles": learning_counts.get("active_cycles", 0),
            },
            "learning": {
                "autonomy_level": (settings.get("learning") or {}).get("autonomy_level") or "off",
                **learning_counts,
            },
            "lifecycle": self.strategies.summary(),
            "recent_runs": runs,
            "recent_experiments": experiments,
            "recent_evaluations": evaluations,
            "paper_accounts": accounts,
            "queue": self.jobs.snapshot(),
            "coverage": self._coverage_summary(datasets),
            "known_data_gaps": KNOWN_DATA_GAPS,
            "simulator_limitations": SIMULATOR_LIMITATIONS,
            "providers": provider_statuses(settings.get("providers")),
            "warnings": self._warnings(datasets),
        }

    def _coverage_summary(self, datasets: Sequence[dict[str, Any]]) -> dict[str, Any]:
        if not datasets:
            return {"first_event_time": None, "last_event_time": None, "instruments": 0, "rows": 0}
        firsts = [item["first_event_time"] for item in datasets if item.get("first_event_time")]
        lasts = [item["last_event_time"] for item in datasets if item.get("last_event_time")]
        return {
            "first_event_time": min(firsts) if firsts else None,
            "last_event_time": max(lasts) if lasts else None,
            "instruments": len({item["instrument_id"] for item in datasets}),
            "rows": sum(int(item.get("row_count", 0)) for item in datasets),
        }

    def _warnings(self, datasets: Sequence[dict[str, Any]]) -> list[str]:
        warnings: list[str] = []
        if not datasets:
            warnings.append(
                "No market data has been imported yet. Every simulation feature stays inert until a dataset exists; "
                "HADES ships no bundled price history."
            )
        synthetic_only = datasets and all(item.get("is_synthetic") for item in datasets)
        if synthetic_only:
            warnings.append("All datasets are SYNTHETIC. Results describe generated data, not markets.")
        unfrozen = [item for item in datasets if not item.get("frozen")]
        if unfrozen:
            warnings.append(f"{len(unfrozen)} dataset revision(s) are not frozen, so their contents can still change.")
        return warnings

    def capabilities(self) -> dict[str, Any]:
        return capability_matrix()

    def data_gaps(self) -> dict[str, Any]:
        return {"gaps": KNOWN_DATA_GAPS, "simulator_limitations": SIMULATOR_LIMITATIONS}

    # --- instruments -------------------------------------------------------------

    def list_instruments(self, *, family: str | None = None, venue: str | None = None) -> list[dict[str, Any]]:
        return self.instruments.as_json(self.instruments.list(family=family, venue=venue))  # type: ignore[arg-type]

    def create_instrument(self, payload: dict[str, Any]) -> dict[str, Any]:
        spec = InstrumentSpec.model_validate(payload)
        stored = self.instruments.register(spec)
        return stored.as_json()

    def delete_instrument(self, instrument_id: str) -> dict[str, Any]:
        datasets = [item for item in self.store.list_datasets(instrument_id=instrument_id, limit=5)]
        if datasets:
            return {
                "deleted": False,
                "reason": f"{len(datasets)} dataset(s) still reference this instrument; delete or re-point them first",
            }
        return {"deleted": self.instruments.remove(instrument_id)}

    # --- data --------------------------------------------------------------------

    def list_datasets(self, **filters: Any) -> list[dict[str, Any]]:
        return self.store.list_datasets(**filters)

    def import_dataset_text(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.catalog.import_text(
            instrument_id=payload["instrument_id"],
            timeframe=payload.get("timeframe", "1h"),
            text=payload["text"],
            name=payload.get("name", ""),
            source_reference=payload.get("source_reference", ""),
            licence=payload.get("licence", "operator supplied"),
            availability_delay_seconds=int(payload.get("availability_delay_seconds", 0) or 0),
            assume_timezone=payload.get("assume_timezone", "UTC"),
        )

    def download_dataset(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = self.settings()
        return self.catalog.download(
            provider_id=payload["provider_id"],
            instrument_id=payload["instrument_id"],
            timeframe=payload.get("timeframe", "1h"),
            start=payload.get("start"),
            end=payload.get("end"),
            limit=int(payload.get("limit", 5000)),
            settings=settings.get("providers") or {},
        )

    def generate_synthetic_dataset(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.catalog.generate_synthetic(
            instrument_id=payload["instrument_id"],
            timeframe=payload.get("timeframe", "1h"),
            start=payload["start"],
            end=payload["end"],
            seed=int(payload.get("seed", 20240101)),
            regime=payload.get("regime", "mixed"),
            start_price=float(payload.get("start_price", 100.0)),
        )

    def freeze_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        return self.catalog.freeze(dataset_id)

    def dataset_detail(self, dataset_id: str) -> dict[str, Any] | None:
        dataset = self.catalog.get(dataset_id)
        if dataset is None:
            return None
        coverage = self.catalog.coverage(dataset["instrument_id"], dataset["timeframe"])
        return {
            "dataset": dataset,
            "coverage": coverage,
            "splits": [window.as_json() for window in self.catalog.splits(dataset)],
            "latest_close": self.catalog.latest_close(dataset["instrument_id"], dataset["timeframe"]),
        }

    def dataset_gaps(self, dataset_id: str) -> dict[str, Any]:
        dataset = self.catalog.get(dataset_id)
        if dataset is None:
            return {"error": f"unknown_dataset:{dataset_id}"}
        return self.catalog.gaps(dataset["instrument_id"], dataset["timeframe"])

    def dataset_preview(self, dataset_id: str, *, limit: int = 300) -> dict[str, Any]:
        dataset = self.catalog.get(dataset_id)
        if dataset is None:
            return {"error": f"unknown_dataset:{dataset_id}"}
        return {
            "dataset_id": dataset_id,
            "rows": self.catalog.preview(dataset["instrument_id"], dataset["timeframe"], limit=limit),
            "is_synthetic": bool(dataset.get("is_synthetic")),
            "provider": dataset.get("provider"),
            "licence": dataset.get("licence"),
        }

    def set_dataset_splits(self, dataset_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self.catalog.set_splits(
            dataset_id,
            development=float(payload.get("development", 0.6)),
            validation=float(payload.get("validation", 0.2)),
            embargo_seconds=int(payload.get("embargo_seconds", 0) or 0),
        )

    def add_corporate_actions(self, dataset_id: str, actions: Sequence[dict[str, Any]]) -> dict[str, Any]:
        added = self.catalog.add_corporate_actions(dataset_id, actions)
        return {"added": added, "dataset_id": dataset_id}

    def providers(self) -> dict[str, Any]:
        settings = self.settings()
        return {"providers": provider_statuses(settings.get("providers")), "known_gaps": KNOWN_DATA_GAPS}

    # --- strategies --------------------------------------------------------------

    def list_strategies(self, **filters: Any) -> list[dict[str, Any]]:
        return self.store.list_strategies(**filters)

    def strategy_detail(self, strategy_id: str) -> dict[str, Any]:
        return self.strategies.evidence(strategy_id)

    def create_strategy(self, payload: dict[str, Any]) -> dict[str, Any]:
        spec = StrategySpec.model_validate(payload)
        family = resolve_family(spec.family)
        if family not in STRATEGY_CLASSES:
            return {"created": False, "reason": f"unknown_strategy_family:{spec.family}", "supported": sorted(STRATEGY_CLASSES)}
        problems = self._validate_strategy_instruments(spec)
        if problems:
            return {"created": False, "reason": "; ".join(problems)}
        record = self.strategies.create(spec, created_by=payload.get("created_by", "operator"))
        return {"created": True, "strategy": record}

    def add_strategy_version(self, strategy_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        spec = StrategySpec.model_validate({**payload, "strategy_id": strategy_id})
        problems = self._validate_strategy_instruments(spec)
        if problems:
            return {"created": False, "reason": "; ".join(problems)}
        version = self.strategies.add_version(strategy_id, spec, created_by=payload.get("created_by", "operator"))
        return {"created": True, "version": version, "strategy": self.store.get_strategy(strategy_id)}

    def _validate_strategy_instruments(self, spec: StrategySpec) -> list[str]:
        from trading_lab.capabilities import validate_strategy_capability

        problems: list[str] = []
        for instrument_id in spec.instruments:
            instrument = self.instruments.find(instrument_id)
            if instrument is None:
                problems.append(f"unknown_instrument:{instrument_id}")
                continue
            dataset = self.catalog.resolve(instrument_id, spec.timeframe)
            levels = [dataset.get("data_level", "ohlcv")] if dataset else ["ohlcv"]
            ok, reason = validate_strategy_capability(spec.family, instrument, available_data_levels=levels)
            if not ok:
                problems.append(reason)
        return problems

    def promote_strategy(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = PromotionRequest(
            strategy_id=payload["strategy_id"],
            version=int(payload.get("version", 1)),
            target_state=payload["target_state"],
            requested_by=payload.get("requested_by", "operator"),
            evaluation_report_id=payload.get("evaluation_report_id"),
            justification=payload.get("justification", ""),
        )
        try:
            record = self.strategies.transition(request)
        except Exception as exc:  # noqa: BLE001 - a refused promotion is an answer
            return {"promoted": False, "reason": f"{type(exc).__name__}: {exc}"}
        if request.evaluation_report_id:
            self.store.mark_evaluation_consumed(request.evaluation_report_id)
        return {"promoted": True, "strategy": record}

    def strategy_families(self) -> dict[str, Any]:
        return {
            "families": [
                {
                    "family": family,
                    "param_space": default_param_space(family),
                    "required_data_level": getattr(cls, "required_data_level", "ohlcv"),
                    "min_instruments": getattr(cls, "min_instruments", 1),
                }
                for family, cls in sorted(STRATEGY_CLASSES.items())
            ]
        }

    # --- experiments -------------------------------------------------------------

    def create_experiment(self, payload: dict[str, Any]) -> dict[str, Any]:
        merged = {**experiment_defaults(payload.get("strategy_family", "trend_following")), **payload}
        merged.pop("promotion_criteria", None)
        spec = ExperimentSpec.model_validate(merged)
        criteria = PromotionCriteria(**(payload.get("promotion_criteria") or {}))
        _bindings, datasets, problems = self.runner.bindings_for(spec.instruments, spec.timeframe, dataset_ids=spec.dataset_ids, split=spec.split)
        if problems:
            return {"created": False, "reason": "; ".join(problems)}
        experiment_id = self.store.create_experiment(
            spec,
            dataset_hash=dataset_manifest_digest(datasets),
            code_hash=stable_hash({"family": spec.strategy_family, "space": spec.param_space}),
            base_commit=self._base_commit(),
            strategy_id=payload.get("strategy_id"),
            preregistration=preregistration_record(spec, criteria),
        )
        return {"created": True, "experiment_id": experiment_id, "experiment": self.store.get_experiment(experiment_id)}

    def start_experiment(self, experiment_id: str, *, strategy_id: str | None = None) -> dict[str, Any]:
        experiment = self.store.get_experiment(experiment_id)
        if experiment is None:
            return {"started": False, "reason": f"unknown_experiment:{experiment_id}"}
        job = self.jobs.submit(
            "experiment",
            {"experiment_id": experiment_id, "strategy_id": strategy_id},
            job_key=f"experiment:{experiment_id}",
            ref_type="experiment",
            ref_id=experiment_id,
        )
        self.store.update_experiment(experiment_id, status="queued", job_id=job["job_id"])
        return {"started": True, "job": job}

    def experiment_detail(self, experiment_id: str) -> dict[str, Any]:
        experiment = self.store.get_experiment(experiment_id)
        if experiment is None:
            return {"error": f"unknown_experiment:{experiment_id}"}
        return {
            "experiment": experiment,
            "trials": self.store.list_trials(experiment_id),
            "job": self.store.get_job(experiment.get("job_id")) if experiment.get("job_id") else None,
        }

    # --- runs --------------------------------------------------------------------

    def start_backtest(self, payload: dict[str, Any]) -> dict[str, Any]:
        strategy_id = payload.get("strategy_id")
        version = payload.get("version")
        record = self.store.get_strategy_version(strategy_id, version) if strategy_id else None
        if record is None and "strategy" not in payload:
            return {"started": False, "reason": "provide strategy_id (with optional version) or an inline strategy"}
        spec = StrategySpec.model_validate(record["spec"] if record else payload["strategy"])
        bindings, datasets, problems = self.runner.bindings_for(
            spec.instruments, spec.timeframe, dataset_ids=payload.get("dataset_ids", []), split=payload.get("split", "development")
        )
        if problems:
            return {"started": False, "reason": "; ".join(problems)}
        window = self.runner.split_window(datasets, payload.get("split", "development"))
        if window is None:
            return {"started": False, "reason": f"no usable window for split {payload.get('split', 'development')}"}
        start = payload.get("start") or window.start
        end = payload.get("end") or window.end
        run_id = self.store.create_run(
            {
                "mode": payload.get("mode", "historical_simulation"),
                "label": payload.get("label", spec.name),
                "status": "queued",
                "strategy_id": strategy_id,
                "strategy_version": spec.version,
                "strategy_hash": spec.content_hash(),
                "split": payload.get("split", "development"),
                "dataset_ids": [item["dataset_id"] for item in datasets],
                "dataset_hash": dataset_manifest_digest(datasets),
                "config": {
                    "start": start,
                    "end": end,
                    "starting_cash": str(payload.get("starting_cash", "100000")),
                    "base_currency": payload.get("base_currency", "USD"),
                    "lookback": int(payload.get("lookback", 300)),
                    "strategy": spec.as_json(),
                },
                "cost_model": self._cost_model(payload).as_json(),
                "risk_limits": self._risk_limits(payload).as_json(),
                "seeds": {"engine": int(payload.get("seed", 7))},
                "base_commit": self._base_commit(),
                "engine_version": "trading-lab-engine-1",
                "branch_of_run_id": payload.get("branch_of_run_id"),
                "branch_from_event_time": payload.get("branch_from_event_time"),
            }
        )
        if payload.get("checkpoint"):
            self.store.update_run(run_id, checkpoint=payload["checkpoint"])
        job = self.jobs.submit(
            "backtest",
            {"run_id": run_id},
            job_key=f"run:{run_id}",
            ref_type="run",
            ref_id=run_id,
        )
        return {"started": True, "run_id": run_id, "job": job, "window": {"start": start, "end": end}}

    def run_detail(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run is None:
            return {"error": f"unknown_run:{run_id}"}
        result = run.get("result") or {}
        return {
            "run": run,
            "equity_curve": thin_curve([(item[0], item[1]) for item in result.get("equity_curve", [])]),
            "benchmark_curve": thin_curve([(item[0], item[1]) for item in result.get("benchmark_curve", [])]),
            "snapshot": self.store.latest_snapshot(run_id),
            "events": self.store.list_run_events(run_id, limit=100),
            "reproducibility": self.reproducibility(run_id),
            "job": self._job_for_run(run_id),
            "progress": self._progress_for_run(run_id),
        }

    def run_orders(self, run_id: str, **filters: Any) -> list[dict[str, Any]]:
        return self.store.list_orders(run_id, **filters)

    def run_fills(self, run_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        return self.store.list_fills(run_id, limit=limit)

    def run_ledger(self, run_id: str, *, limit: int = 1000) -> dict[str, Any]:
        return {
            "entries": self.store.list_ledger_entries(run_id, limit=limit),
            "totals": self.store.ledger_totals(run_id),
        }

    def run_decisions(self, run_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        return self.store.list_decisions(run_id, limit=limit)

    def run_snapshots(self, run_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        return self.store.list_snapshots(run_id, limit=limit)

    def control_run(self, run_id: str, action: str, *, value: float | None = None) -> dict[str, Any]:
        job = self._job_for_run(run_id)
        if job is None:
            return {"ok": False, "reason": "no_job_for_run"}
        job_id = job["job_id"]
        if action == "pause":
            return {"ok": True, "job": self.jobs.pause(job_id)}
        if action == "resume":
            return {"ok": True, "job": self.jobs.resume(job_id, speed=value)}
        if action == "step":
            return {"ok": True, "job": self.jobs.step(job_id, int(value or 1))}
        if action == "cancel":
            return {"ok": True, "job": self.jobs.cancel(job_id)}
        if action == "speed":
            return {"ok": True, "job": self.jobs.set_speed(job_id, float(value or 1.0))}
        return {"ok": False, "reason": f"unknown_action:{action}"}

    def rewind_run(self, run_id: str, event_time: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Rewinding never rewrites history: it forks a new run branch from a checkpoint.

        The parent keeps every event after ``event_time``. The branch restores the nearest
        engine checkpoint at or before that instant and continues to the parent's original
        end, so the clock is not moved backwards on the original run.
        """
        run = self.store.get_run(run_id)
        if run is None:
            return {"branched": False, "reason": f"unknown_run:{run_id}"}
        checkpoint = select_checkpoint_for_rewind(
            event_time,
            self.store.engine_checkpoints(run_id),
            latest=run.get("checkpoint") or {},
        )
        if not checkpoint:
            return {
                "branched": False,
                "reason": (
                    f"no_checkpoint_at_or_before:{event_time}. "
                    "Pick a listed checkpoint, or wait until the engine has written one."
                ),
            }
        config = run.get("config") or {}
        branch_payload = {
            **(payload or {}),
            "strategy_id": run.get("strategy_id"),
            "version": run.get("strategy_version"),
            "strategy": config.get("strategy"),
            "split": run.get("split", "development"),
            "dataset_ids": run.get("dataset_ids", []),
            "start": config.get("start"),
            "end": config.get("end"),
            "starting_cash": config.get("starting_cash", "100000"),
            "base_currency": config.get("base_currency", "USD"),
            "lookback": config.get("lookback", 300),
            "seed": int((run.get("seeds") or {}).get("engine", 7)),
            "cost_model": run.get("cost_model") or {},
            "risk_limits": run.get("risk_limits") or {},
            "branch_of_run_id": run_id,
            "branch_from_event_time": event_time,
            "label": f"{run.get('label', 'run')} (branch @ {event_time})",
            "checkpoint": checkpoint,
        }
        started = self.start_backtest(branch_payload)
        if not started.get("started"):
            return {"branched": False, "reason": started.get("reason", "branch_failed")}
        return {"branched": True, "run_id": started["run_id"], "job": started.get("job"), "from_event_time": event_time}

    def compare(self, left_run_id: str, right_run_id: str) -> dict[str, Any]:
        left = self.store.get_run(left_run_id) or {}
        right = self.store.get_run(right_run_id) or {}
        return {
            "left": {"run_id": left_run_id, "run": left},
            "right": {"run_id": right_run_id, "run": right},
            "comparison": compare_runs(
                (left.get("result") or {}).get("metrics", {}),
                (right.get("result") or {}).get("metrics", {}),
            ),
        }

    def reproducibility(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run is None:
            return {}
        return {
            "run_id": run_id,
            "base_commit": run.get("base_commit"),
            "engine_version": run.get("engine_version"),
            "strategy_hash": run.get("strategy_hash"),
            "dataset_ids": run.get("dataset_ids"),
            "dataset_hash": run.get("dataset_hash"),
            "seeds": run.get("seeds"),
            "cost_model": run.get("cost_model"),
            "risk_limits": run.get("risk_limits"),
            "model_versions": run.get("model_versions"),
            "split": run.get("split"),
            "branch_of_run_id": run.get("branch_of_run_id"),
            "branch_from_event_time": run.get("branch_from_event_time"),
            "note": (
                "Re-running with this record reproduces the run exactly: the engine is deterministic and every "
                "input above is pinned, including dataset checksums."
            ),
        }

    # --- evaluation --------------------------------------------------------------

    def start_evaluation(self, payload: dict[str, Any]) -> dict[str, Any]:
        strategy_id = payload.get("strategy_id")
        record = self.store.get_strategy_version(strategy_id, payload.get("version"))
        if record is None:
            return {"started": False, "reason": f"unknown_strategy_version:{strategy_id}"}
        split = payload.get("split", "validation")
        if split == "sealed_test":
            available, reason = self.strategies.holdout_available(strategy_id, int(record["version"]))
            if not available:
                return {"started": False, "reason": reason}
        job = self.jobs.submit(
            "evaluation",
            {
                "strategy_id": strategy_id,
                "version": int(record["version"]),
                "split": split,
                "folds": int(payload.get("folds", 4)),
                "scheme": payload.get("scheme", "expanding"),
                "evaluated_by": payload.get("evaluated_by", "independent_validator"),
                "criteria": payload.get("promotion_criteria") or {},
                "starting_cash": str(payload.get("starting_cash", "100000")),
                "seed": int(payload.get("seed", 7)),
                "include_stress": bool(payload.get("include_stress", True)),
            },
            job_key=f"evaluation:{strategy_id}:{record['version']}:{split}:{payload.get('seed', 7)}",
            ref_type="strategy",
            ref_id=str(strategy_id),
        )
        return {"started": True, "job": job}

    def list_evaluations(self, **filters: Any) -> list[dict[str, Any]]:
        return self.store.list_evaluations(**filters)

    def evaluation_detail(self, report_id: str) -> dict[str, Any] | None:
        return self.store.get_evaluation(report_id)

    # --- models ------------------------------------------------------------------

    def train_model_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        job = self.jobs.submit(
            "train_model",
            payload,
            job_key=f"train:{stable_hash(payload)}",
            ref_type="model",
            ref_id=str(payload.get("name", "")),
        )
        return {"started": True, "job": job}

    def list_models(self, **filters: Any) -> list[dict[str, Any]]:
        return self.store.list_models(**filters)

    def load_models(self, names: Sequence[str]) -> dict[str, TrainedModel]:
        loaded: dict[str, TrainedModel] = {}
        for name in names:
            record = self.store.get_model(name)
            if record is None:
                continue
            artefact = record.get("weights") or {}
            if not artefact:
                continue
            try:
                loaded[name] = TrainedModel.from_json(artefact)
            except Exception:  # noqa: BLE001 - a corrupt artefact is skipped, never guessed
                continue
        return loaded

    # --- portfolio and risk ------------------------------------------------------

    def portfolio_state(self, run_id: str | None = None) -> dict[str, Any]:
        if run_id:
            snapshot = self.store.latest_snapshot(run_id)
            return {
                "run_id": run_id,
                "snapshot": snapshot,
                "ledger_totals": self.store.ledger_totals(run_id),
                "mode": MODE_LABEL,
            }
        accounts = self.store.list_paper_accounts()
        return {"accounts": accounts, "mode": MODE_LABEL}

    def risk_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Ask the risk engine what it would do with an intent, without submitting anything."""
        instrument_id = payload["instrument_id"]
        spec = self.instruments.find(instrument_id)
        if spec is None:
            return {"error": f"unknown_instrument:{instrument_id}"}
        from trading_lab.adapters import adapter_for

        clean_metadata, stripped = sanitize_model_risk_payload(payload.get("metadata"))
        intent = OrderIntent.model_validate(
            {
                "intent_id": payload.get("intent_id", f"preview:{instrument_id}"),
                "instrument_id": instrument_id,
                "side": payload.get("side", "buy"),
                "order_type": payload.get("order_type", "market"),
                "quantity": payload.get("quantity", "1"),
                "limit_price": payload.get("limit_price"),
                "stop_price": payload.get("stop_price"),
                "time_in_force": payload.get("time_in_force", "GTC"),
                "reduce_only": bool(payload.get("reduce_only", False)),
                "post_only": bool(payload.get("post_only", False)),
                "price_source": "operator_input",
                "metadata": clean_metadata,
            }
        )
        latest = self.catalog.latest_close(instrument_id, payload.get("timeframe", "1h"))
        portfolio = Portfolio(base_currency=payload.get("base_currency", "USD"), starting_cash={payload.get("base_currency", "USD"): to_decimal(payload.get("equity", "100000"))})
        engine = RiskEngine(self._risk_limits(payload))
        decision = engine.evaluate(
            intent,
            spec=spec,
            adapter=adapter_for(spec),
            portfolio=portfolio,
            context=RiskContext(
                equity=to_decimal(payload.get("equity", "100000")),
                peak_equity=to_decimal(payload.get("equity", "100000")),
                correlation_groups=correlation_groups_from_specs(self.instruments.list()),
            ),
        )
        return {
            "decision": decision.as_json(),
            "stripped_override_keys": stripped,
            "latest_close": latest,
            "kill_switch_behaviour": engine.on_kill_switch(armed=self._risk_limits(payload).kill_switch_armed),
        }

    def order_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate an order against the capability matrix and the instrument rules."""
        from trading_lab.capabilities import validate_order_capability

        spec = self.instruments.find(payload["instrument_id"])
        if spec is None:
            return {"valid": False, "reason": f"unknown_instrument:{payload['instrument_id']}"}
        dataset = self.catalog.resolve(payload["instrument_id"], payload.get("timeframe", "1h"))
        levels = [dataset.get("data_level", "ohlcv")] if dataset else ["ohlcv"]
        intent = OrderIntent.model_validate({**payload, "intent_id": payload.get("intent_id", "preview")})
        ok, reason = validate_order_capability(spec, intent, available_data_levels=levels)
        return {"valid": ok, "reason": reason, "available_data_levels": levels}

    # --- agents ------------------------------------------------------------------

    def agent_roles(self) -> dict[str, Any]:
        settings = self.settings()
        manifest = roles_manifest()
        manifest["configured_models"] = settings.get("agent_models") or {}
        manifest["chat_available"] = self.chat is not None
        return manifest

    async def run_agent_pipeline(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.chat is None:
            return {
                "status": "unavailable",
                "reason": "no_model_gateway_bound: the Trading Lab service was constructed without a chat function",
            }
        settings = self.settings()
        agent_models = settings.get("agent_models") or {}
        default_model = str(payload.get("model") or agent_models.get("default") or "")
        if not default_model:
            return {
                "status": "unavailable",
                "reason": (
                    "no_model_selected: pick a loaded LM Studio model in Trading Lab settings. "
                    "The lab does not hardcode a model id."
                ),
            }
        team = AgentTeam(
            self.chat,
            default_model=default_model,
            role_models={key: value for key, value in agent_models.items() if key != "default"},
            max_concurrency=int((settings.get("resources") or {}).get("max_agent_concurrency", 1)),
        )
        facts = self._agent_facts(payload)
        session_id = self.store.create_agent_session(
            {
                "title": payload.get("question", "")[:160],
                "objective": payload.get("question", ""),
                "status": "running",
                "strategy_id": payload.get("strategy_id"),
                "experiment_id": payload.get("experiment_id"),
                "max_concurrency": 1,
                "budget": {"model_id": default_model, "roles": payload.get("roles") or [role for role, _ in default_pipeline("", {})]},
            }
        )
        steps = (
            default_pipeline(payload.get("question", ""), facts)
            if not payload.get("roles")
            else [
                (role, AgentContext(question=payload.get("question", ""), facts=facts))
                for role in payload["roles"]
            ]
        )
        results = await team.run_sequence(steps, run_id=session_id)
        for result in results:
            task_id = self.store.create_agent_task(
                {
                    "session_id": session_id,
                    "role": result.role_id,
                    "status": result.status,
                    "assignment": payload.get("question", "")[:400],
                    "model_id": result.model_id,
                    "model_source": "shared" if result.model_id == default_model else "role_override",
                    "permissions": {"reads": list(ROLES[result.role_id].reads)} if result.role_id in ROLES else {},
                    "input": {"prompt_hash": result.prompt_hash},
                }
            )
            self.store.update_agent_task(task_id, status=result.status, output=result.as_json(), error=result.error or None)
        self.store.update_agent_session(
            session_id,
            status="completed" if all(item.status in {"completed", "incomplete"} for item in results) else "failed",
            result={"steps": [item.as_json() for item in results]},
        )
        return {
            "status": "completed",
            "session_id": session_id,
            "steps": [item.as_json() for item in results],
            "note": "Agent output is a proposal. Nothing here executed, sized or approved a trade.",
        }

    def _agent_facts(self, payload: dict[str, Any]) -> dict[str, Any]:
        datasets = self.store.list_datasets(limit=40)
        return {
            "mode": MODE_LABEL,
            "instruments": [
                {
                    "instrument_id": spec.instrument_id,
                    "family": spec.family,
                    "symbol": spec.symbol,
                    "calendar": spec.calendar,
                    "shorting_allowed": spec.shorting_allowed,
                }
                for spec in self.instruments.list()[:60]
            ],
            "datasets": [
                {
                    "dataset_id": item["dataset_id"],
                    "instrument_id": item["instrument_id"],
                    "timeframe": item["timeframe"],
                    "rows": item.get("row_count"),
                    "first_event_time": item.get("first_event_time"),
                    "last_event_time": item.get("last_event_time"),
                    "is_synthetic": item.get("is_synthetic"),
                    "frozen": item.get("frozen"),
                }
                for item in datasets
            ],
            "supported_strategy_families": sorted(STRATEGY_CLASSES),
            "capability_matrix": capability_matrix(),
            "known_data_gaps": KNOWN_DATA_GAPS,
            "recent_experiments": self.store.list_experiments(limit=10),
            "recent_evaluations": self.store.list_evaluations(limit=10),
            "learned_beliefs": self._learned_context(payload),
            "negative_evidence": self._negative_research_context(payload),
            "tested_fingerprints": [
                {"fingerprint": row["fingerprint"][:16], "status": row.get("status")}
                for row in self.store.list_candidate_fingerprints()[:20]
            ],
            "champions": [
                {
                    "champion_id": row.get("champion_id"),
                    "strategy_id": row.get("strategy_id"),
                    "strategy_version": row.get("strategy_version"),
                    "scope": row.get("scope"),
                }
                for row in self.store.list_champions(limit=8)
            ],
            "extra": payload.get("facts") or {},
        }

    def _learned_context(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        extra = payload.get("facts") or {}
        beliefs = self.store.list_trading_beliefs(limit=80)
        return retrieve_beliefs(
            beliefs,
            instrument_id=payload.get("instrument_id") or extra.get("instrument_id"),
            strategy_family=payload.get("strategy_family") or extra.get("strategy_family"),
            timeframe=payload.get("timeframe") or extra.get("timeframe"),
            regime_key=extra.get("regime_key"),
            limit=8,
        )

    def _negative_research_context(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        beliefs = self.store.list_trading_beliefs(status="contradicted", limit=20)
        failed = [row for row in self.store.list_strategy_candidates(limit=20) if row.get("status") == "rejected"]
        compact = retrieve_beliefs(beliefs, limit=6)
        for row in failed[:6]:
            compact.append(
                {
                    "kind": "rejected_candidate",
                    "fingerprint": row.get("fingerprint"),
                    "reason": row.get("rejection_reason"),
                    "mutation_kind": row.get("mutation_kind"),
                    "evidence_refs": (row.get("evidence_refs") or [])[:4],
                }
            )
        return compact[:8]

    def agent_sessions(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.list_agent_sessions(limit=limit)

    # --- settings ----------------------------------------------------------------

    def settings(self) -> dict[str, Any]:
        values = self.store.settings()
        if not values.get("cost_model"):
            values["cost_model"] = CostModel().as_json()
        if not values.get("risk_limits"):
            values["risk_limits"] = RiskLimits().as_json()
        values.setdefault("providers", {"allow_network": False})
        values.setdefault("resources", {"max_workers": self.jobs.max_workers, "max_agent_concurrency": 1})
        values.setdefault("agent_models", {})
        values.setdefault(
            "learning",
            {
                "autonomy_level": "off",
                "allow_sealed_holdout": False,
                "budgets": dict(DEFAULT_BUDGETS),
            },
        )
        if not values["learning"]:
            values["learning"] = {
                "autonomy_level": "off",
                "allow_sealed_holdout": False,
                "budgets": dict(DEFAULT_BUDGETS),
            }
        values["learning"].setdefault("autonomy_level", "off")
        values["learning"].setdefault("budgets", dict(DEFAULT_BUDGETS))
        values["mode"] = MODE_LABEL
        return values

    def save_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        if "cost_model" in payload:
            clean["cost_model"] = CostModel.model_validate(payload["cost_model"]).as_json()
        if "risk_limits" in payload:
            clean["risk_limits"] = RiskLimits.model_validate(payload["risk_limits"]).as_json()
        for key in ("providers", "resources", "agent_models", "split_policy", "learning"):
            if key in payload:
                if key == "learning":
                    clean["learning"] = self._clean_learning_settings(payload["learning"] or {})
                else:
                    clean[key] = payload[key]
        self.store.save_settings(clean)
        return self.settings()

    def _clean_learning_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = (self.store.settings().get("learning") or {}) if hasattr(self.store, "settings") else {}
        level = normalize_autonomy(payload.get("autonomy_level"), default=str(current.get("autonomy_level") or "off"))
        budgets = {**DEFAULT_BUDGETS, **(current.get("budgets") or {}), **(payload.get("budgets") or {})}
        return {
            "autonomy_level": level,
            "allow_sealed_holdout": bool(payload.get("allow_sealed_holdout", current.get("allow_sealed_holdout", False))),
            "budgets": {
                key: max(0, int(budgets.get(key, default)))
                for key, default in DEFAULT_BUDGETS.items()
            },
        }

    def jobs_snapshot(self) -> dict[str, Any]:
        return {"queue": self.jobs.snapshot(), "jobs": self.store.list_jobs(limit=50)}

    # --- job handlers ------------------------------------------------------------

    def _register_handlers(self) -> None:
        self.jobs.register("backtest", self._handle_backtest)
        self.jobs.register("experiment", self._handle_experiment)
        self.jobs.register("evaluation", self._handle_evaluation)
        self.jobs.register("train_model", self._handle_train_model)
        self.jobs.register("learning_cycle", self._handle_learning_cycle)

    def _handle_backtest(self, handle: JobHandle) -> dict[str, Any]:
        run_id = handle.payload["run_id"]
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"unknown_run:{run_id}")
        config_payload = run.get("config") or {}
        spec = StrategySpec.model_validate(config_payload["strategy"])
        bindings, datasets, problems = self.runner.bindings_for(
            spec.instruments, spec.timeframe, dataset_ids=run.get("dataset_ids", []), split=run.get("split", "development")
        )
        if problems:
            self.store.update_run(run_id, status="failed", error="; ".join(problems))
            return {"status": "failed", "reason": "; ".join(problems)}

        self.store.update_run(run_id, status="running", started_at=utc_iso(datetime.now(tz=UTC)))
        sink = StoreSink(self.store, run_id, progress=lambda payload: handle.progress(payload))
        engine_config = EngineConfig(
            run_id=run_id,
            strategy=spec,
            bindings=bindings,
            start=config_payload["start"],
            end=config_payload.get("end"),
            mode=run.get("mode", "historical_simulation"),
            split=run.get("split", "development"),
            base_currency=config_payload.get("base_currency", "USD"),
            starting_cash=to_decimal(config_payload.get("starting_cash", "100000")),
            cost_model=CostModel.model_validate(run.get("cost_model") or {}),
            risk_limits=RiskLimits.model_validate(run.get("risk_limits") or {}),
            seed=int((run.get("seeds") or {}).get("engine", 7)),
            lookback=int(config_payload.get("lookback", 300)),
            base_commit=run.get("base_commit", ""),
            parent_run_id=run.get("branch_of_run_id"),
            branch_point=run.get("branch_from_event_time"),
            models=self.load_models(list((config_payload.get("models") or {}).keys())),
        )
        engine = SimulationEngine(
            engine_config,
            bar_store=self.bars,
            registry=self.instruments,
            event_store=self.store,
            sink=sink,
            control=handle.control,
        )
        checkpoint = handle.checkpoint or (run.get("checkpoint") or {})
        if checkpoint:
            result = engine.resume_from(checkpoint)
        else:
            result = engine.run()
        handle.save_checkpoint(engine.checkpoint())
        dataset = datasets[0] if datasets else {}
        metrics = summarise(
            RunSummaryInput(
                label=run.get("label", run_id),
                split=run.get("split", "development"),
                equity_curve=result.equity_curve,
                benchmark_curve=result.benchmark_curve,
                trades=result.fills,
                costs_paid=float(result.costs.get("fees_paid", "0") or 0),
                timeframe=spec.timeframe,
                calendar=dataset.get("calendar", "24x7"),
            )
        )
        payload = result.as_json()
        payload["metrics"] = metrics.model_dump()
        self.store.update_run(
            run_id,
            status=result.status,
            progress=100 if result.status == "completed" else 0,
            simulation_time=result.last_event_time,
            first_event_time=result.equity_curve[0][0] if result.equity_curve else None,
            last_event_time=result.last_event_time,
            events_processed=result.events_processed,
            result=payload,
            checkpoint=engine.checkpoint(),
            finished_at=utc_iso(datetime.now(tz=UTC)),
        )
        self.store.append_run_event(
            run_id,
            f"run {result.status}: {result.events_processed} events, {result.fills} fills, {result.orders_blocked} blocked by risk",
            category="engine",
            simulation_time=result.last_event_time,
            payload={"warnings": result.warnings, "reconciliation": result.reconciliation},
        )
        self._maybe_follow_up_learning(run_id=run_id, strategy_id=run.get("strategy_id"))
        return {"status": result.status, "metrics": metrics.model_dump(), "run_id": run_id}

    def _handle_experiment(self, handle: JobHandle) -> dict[str, Any]:
        experiment_id = handle.payload["experiment_id"]
        record = self.store.get_experiment(experiment_id)
        if record is None:
            raise ValueError(f"unknown_experiment:{experiment_id}")
        spec = ExperimentSpec.model_validate(record["spec"])
        strategy_id = handle.payload.get("strategy_id") or record.get("strategy_id")
        base_spec = None
        if strategy_id:
            version = self.store.get_strategy_version(strategy_id)
            if version:
                base_spec = StrategySpec.model_validate(version["spec"])
        if base_spec is None:
            base_spec = StrategySpec(
                name=f"{spec.strategy_family} search",
                family=spec.strategy_family,
                instruments=list(spec.instruments),
                timeframe=spec.timeframe,
            )
        self.store.update_experiment(experiment_id, status="running", started_at=utc_iso(datetime.now(tz=UTC)))
        outcome = self.runner.run_experiment(
            spec,
            experiment_id=experiment_id,
            base_strategy=base_spec,
            progress=lambda payload: handle.progress(
                {**payload, "percent": int(100 * payload.get("completed", 0) / max(1, payload.get("total", 1)))}
            ),
            should_stop=lambda: handle.cancelled,
        )
        self.store.update_experiment(
            experiment_id,
            status="cancelled" if handle.cancelled else outcome.get("status", "completed"),
            result=outcome,
            finished_at=utc_iso(datetime.now(tz=UTC)),
        )
        self._maybe_follow_up_learning(experiment_id=experiment_id, strategy_id=strategy_id)
        return outcome

    def _handle_evaluation(self, handle: JobHandle) -> dict[str, Any]:
        payload = handle.payload
        strategy_id = payload["strategy_id"]
        version_record = self.store.get_strategy_version(strategy_id, payload.get("version"))
        if version_record is None:
            raise ValueError(f"unknown_strategy_version:{strategy_id}")
        spec = StrategySpec.model_validate(version_record["spec"])
        split = payload.get("split", "validation")
        report_id = f"ev_{stable_hash({'s': strategy_id, 'v': spec.version, 'split': split, 'seed': payload.get('seed', 7)})[:16]}"
        if split == "sealed_test":
            self.strategies.consume_holdout(
                strategy_id=strategy_id,
                version=spec.version,
                used_by=payload.get("evaluated_by", "independent_validator"),
                report_id=report_id,
                purpose="final_confirmation",
            )
        trials_considered = max(1, self.store.count_trials(strategy_id=strategy_id) or 1)
        outcome = self.runner.evaluate(
            spec,
            report_id=report_id,
            split=split,
            folds=int(payload.get("folds", 4)),
            scheme=payload.get("scheme", "expanding"),
            starting_cash=to_decimal(payload.get("starting_cash", "100000")),
            cost_model=CostModel.model_validate(self.settings().get("cost_model") or {}),
            risk_limits=RiskLimits.model_validate(self.settings().get("risk_limits") or {}),
            seed=int(payload.get("seed", 7)),
            search_trials_considered=trials_considered,
            criteria=PromotionCriteria(**(payload.get("criteria") or {})),
            evaluated_by=payload.get("evaluated_by", "independent_validator"),
            include_stress=bool(payload.get("include_stress", True)),
            models=self.load_models([str(spec.params.get("model", ""))]) if spec.params.get("model") else None,
            reproducibility={
                "base_commit": self._base_commit(),
                "engine_version": "trading-lab-engine-1",
                "strategy_hash": spec.content_hash(),
                "seed": payload.get("seed", 7),
            },
        )
        if outcome.get("status") != "completed":
            return outcome
        report: EvaluationReport = outcome["report"]
        self.store.save_evaluation(report)
        return {"status": "completed", "report_id": report.report_id, "verdict": report.verdict, "reasons": report.verdict_reasons}

    def _handle_train_model(self, handle: JobHandle) -> dict[str, Any]:
        payload = handle.payload
        instrument_id = payload["instrument_id"]
        timeframe = payload.get("timeframe", "1h")
        dataset = self.catalog.resolve(instrument_id, timeframe)
        if dataset is None:
            return {"status": "failed", "reason": f"no_dataset_for:{instrument_id}@{timeframe}"}
        window = None
        for candidate in self.catalog.splits(dataset):
            if candidate.name == "development":
                window = candidate
        if window is None:
            return {"status": "failed", "reason": "no_development_split"}
        closes: list[float] = []
        timestamps: list[str] = []
        for event in self.bars.iter_events(instrument_id, timeframe, start=window.start, end=window.end):
            try:
                closes.append(float(event.reference_price))
            except ValueError:
                continue
            timestamps.append(event.event_time)
        model, report = train_model(
            model_id=payload.get("name", f"model_{instrument_id}"),
            name=payload.get("name", f"model_{instrument_id}"),
            kind=payload.get("kind", "ridge"),
            closes=closes,
            timestamps=timestamps,
            instrument_id=instrument_id,
            timeframe=timeframe,
            dataset_ids=[dataset["dataset_id"]],
            train_fraction=float(payload.get("train_fraction", 0.7)),
            embargo_rows=int(payload.get("embargo_rows", 5)),
            alpha=float(payload.get("alpha", 1.0)),
            seed=int(payload.get("seed", 7)),
            created_at=utc_iso(datetime.now(tz=UTC)),
        )
        if model is None:
            return {"status": "failed", "report": report}
        self.store.save_model(
            {
                "model_id": model.model_id,
                "name": model.name,
                "kind": model.kind,
                "version": model.version,
                "dataset_ids": model.dataset_ids,
                "split": "development",
                "feature_spec": {"features": model.feature_names},
                "label_spec": {"label": "next-period simple return"},
                "preprocessing": {"scaler": "standardised on the training window only"},
                "hyperparams": model.hyperparameters,
                "weights": model.as_json(),
                "training_window": report.get("training_window")
                or {
                    "start": model.train_start,
                    "end": model.train_end,
                    "cutoff": model.training_cutoff,
                    "embargo_rows": model.embargo_rows,
                },
                "baseline_comparison": report.get("baseline_comparison") or {},
                "metrics": model.metrics,
                "artefact_hash": model.artefact_hash,
            }
        )
        return {"status": "completed", "model_id": model.model_id, "report": report}

    def _handle_learning_cycle(self, handle: JobHandle) -> dict[str, Any]:
        cycle_id = handle.payload["cycle_id"]
        settings = self.settings()
        agent_models = settings.get("agent_models") or {}
        model_id = str(agent_models.get("default") or agent_models.get("learning_curator") or "")
        engine = LearningCycleEngine(
            self.store,
            runner=self.runner,
            registry=self.strategies,
            chat=self.chat if model_id else None,
            model_id=model_id,
        )
        cycle = engine.run(cycle_id, cancelled=lambda: handle.cancelled)
        handle.save_checkpoint(cycle.get("checkpoint") or {})
        return {"status": cycle.get("status"), "cycle_id": cycle_id, "stage": cycle.get("stage"), "report": cycle.get("report")}

    def _maybe_follow_up_learning(self, *, run_id: str | None = None, experiment_id: str | None = None, strategy_id: str | None = None) -> None:
        level = normalize_autonomy((self.settings().get("learning") or {}).get("autonomy_level"))
        if level == "off":
            return
        ingest_resolved_decisions(self.store, run_id=run_id, experiment_id=experiment_id, engine_version="trading-lab-engine-1")
        running = [item for item in self.store.list_learning_cycles(limit=5) if item.get("status") not in {"completed", "cancelled", "failed"}]
        if running:
            return
        parents = [strategy_id] if strategy_id else []
        self.start_learning_cycle(
            {
                "objective": f"Follow-up after {'experiment ' + experiment_id if experiment_id else 'run ' + (run_id or '')}",
                "autonomy_level": level,
                "parent_strategy_ids": parents,
            }
        )

    # --- learning / evolution ----------------------------------------------------

    def learning_overview(self) -> dict[str, Any]:
        settings = self.settings()
        counts = self.store.learning_overview_counts()
        return {
            "mode": MODE_LABEL,
            "autonomy_level": (settings.get("learning") or {}).get("autonomy_level") or "off",
            "autonomy_levels": list(AUTONOMY_LEVELS),
            "budgets": (settings.get("learning") or {}).get("budgets") or dict(DEFAULT_BUDGETS),
            "counts": counts,
            "active_cycles": [item for item in self.store.list_learning_cycles(limit=10) if item.get("status") not in {"completed", "cancelled", "failed"}],
            "recent_cycles": self.store.list_learning_cycles(limit=10),
            "champions": self.store.list_champions(limit=20),
            "note": (
                "Learning means: experiences are evidence, aggregations are statistics, beliefs are "
                "evidence-backed interpretations, and candidates still have to pass evaluation. "
                "An LLM does not compute metrics and does not train numerical models."
            ),
        }

    def ingest_experiences(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        return ingest_resolved_decisions(
            self.store,
            run_id=payload.get("run_id"),
            experiment_id=payload.get("experiment_id"),
            limit=int(payload.get("limit") or 5000),
            engine_version="trading-lab-engine-1",
        )

    def list_experiences(self, **filters: Any) -> dict[str, Any]:
        limit = int(filters.pop("limit", 100) or 100)
        offset = int(filters.pop("offset", 0) or 0)
        rows = self.store.list_experiences(limit=limit, offset=offset, **{k: v for k, v in filters.items() if v not in (None, "")})
        return {"experiences": rows, "count": self.store.count_experiences(**{k: v for k, v in filters.items() if v not in (None, "")}), "limit": limit, "offset": offset}

    def list_beliefs(self, **filters: Any) -> dict[str, Any]:
        return {"beliefs": self.store.list_trading_beliefs(**{k: v for k, v in filters.items() if v not in (None, "")})}

    def list_findings(self, *, cycle_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        rows = self.store.list_learning_findings(cycle_id=cycle_id, limit=limit)
        return {"findings": compact_findings(rows, limit=limit)}

    def list_lineage(self, *, strategy_id: str | None = None, limit: int = 200) -> dict[str, Any]:
        return {"lineage": self.store.list_strategy_lineage(strategy_id=strategy_id, limit=limit)}

    def list_candidates(self, **filters: Any) -> dict[str, Any]:
        return {"candidates": self.store.list_strategy_candidates(**{k: v for k, v in filters.items() if v not in (None, "")})}

    def list_champions(self, *, limit: int = 50) -> dict[str, Any]:
        return {"champions": self.store.list_champions(limit=limit)}

    def compare_champion(self, payload: dict[str, Any]) -> dict[str, Any]:
        strategy_id = payload["strategy_id"]
        strategy = self.store.get_strategy(strategy_id)
        if strategy is None:
            return {"ok": False, "reason": f"unknown_strategy:{strategy_id}"}
        version = self.store.get_strategy_version(strategy_id, payload.get("version"))
        spec = (version or {}).get("spec") or {}
        instrument = (spec.get("instruments") or [None])[0]
        key = scope_key(instrument_id=instrument, timeframe=spec.get("timeframe"))
        champion = self.store.get_active_champion(key)
        decision = evaluate_challenger(
            challenger={"status": strategy.get("status"), "family": spec.get("family"), "params": spec.get("params") or {}, "strategy_id": strategy_id, "strategy_version": (version or {}).get("version")},
            champion=champion,
            challenger_evaluations=self.store.list_evaluations(strategy_id=strategy_id, limit=20),
            champion_evaluations=self.store.list_evaluations(strategy_id=champion["strategy_id"], limit=20) if champion else [],
        )
        return {"ok": True, "scope_key": key, "decision": decision, "champion": champion}

    def start_learning_cycle(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = self.settings()
        learning = settings.get("learning") or {}
        requested = normalize_autonomy(payload.get("autonomy_level"), default=str(learning.get("autonomy_level") or "learn_only"))
        if requested == "off":
            requested = "learn_only"
        engine = LearningCycleEngine(self.store, runner=self.runner, registry=self.strategies)
        cycle = engine.start(
            objective=str(payload.get("objective") or "Iterate on completed simulation evidence"),
            autonomy_level=requested,
            parent_strategy_ids=list(payload.get("parent_strategy_ids") or []),
            budget={**DEFAULT_BUDGETS, **(learning.get("budgets") or {}), **(payload.get("budget") or {})},
            allow_sealed_holdout=False,
        )
        job = self.jobs.submit(
            "learning_cycle",
            {"cycle_id": cycle["cycle_id"]},
            job_key=f"learning_cycle:{cycle['cycle_id']}",
            ref_type="learning_cycle",
            ref_id=cycle["cycle_id"],
        )
        self.store.update_learning_cycle(cycle["cycle_id"], job_id=job.get("job_id"))
        return {"started": True, "cycle": self.store.get_learning_cycle(cycle["cycle_id"]), "job": job}

    def learning_cycle(self, cycle_id: str) -> dict[str, Any] | None:
        return self.store.get_learning_cycle(cycle_id)

    def list_learning_cycles(self, *, limit: int = 50) -> dict[str, Any]:
        return {"cycles": self.store.list_learning_cycles(limit=limit)}

    def run_learning_cycle_now(self, cycle_id: str) -> dict[str, Any]:
        """Synchronous path for tests and operators who do not want the job queue."""
        settings = self.settings()
        agent_models = settings.get("agent_models") or {}
        model_id = str(agent_models.get("default") or "")
        engine = LearningCycleEngine(
            self.store,
            runner=self.runner,
            registry=self.strategies,
            chat=self.chat if model_id else None,
            model_id=model_id,
        )
        return engine.run(cycle_id)

    # --- helpers -----------------------------------------------------------------

    def _cost_model(self, payload: dict[str, Any]) -> CostModel:
        base = self.settings().get("cost_model") or {}
        return CostModel.model_validate({**base, **(payload.get("cost_model") or {})})

    def _risk_limits(self, payload: dict[str, Any]) -> RiskLimits:
        base = self.settings().get("risk_limits") or {}
        return RiskLimits.model_validate({**base, **(payload.get("risk_limits") or {})})

    def _job_for_run(self, run_id: str) -> dict[str, Any] | None:
        for job in self.store.list_jobs(limit=200):
            if job.get("ref_type") == "run" and job.get("ref_id") == run_id:
                return job
        return None

    def _progress_for_run(self, run_id: str) -> dict[str, Any]:
        job = self._job_for_run(run_id)
        if job is None:
            return {}
        return self.jobs.progress(job["job_id"])

    def _base_commit(self) -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(Path(__file__).resolve().parent.parent.parent),
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return result.stdout.strip()[:40] if result.returncode == 0 else ""
        except Exception:  # noqa: BLE001 - a missing git checkout is not an error here
            return ""

    def shutdown(self) -> None:
        self.jobs.stop()


__all__ = ["MODE_LABEL", "StoreSink", "TradingLabService"]
