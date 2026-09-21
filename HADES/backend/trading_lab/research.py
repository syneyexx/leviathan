"""Experiment registry and bounded strategy search.

Two rules make search results mean something:

1. **Every trial is recorded**, including the ones that failed and the ones that were worse
   than the baseline. A search that only keeps its winner cannot be corrected for selection,
   because nobody knows how many attempts produced it.
2. **The budget is finite and declared up front.** ``search_budget`` caps the number of
   configurations, the seed makes the sample reproducible, and the trial count travels with
   the candidate into evaluation as ``search_trials_considered``.

Search runs on the development split only. Validation is a separate step; the sealed test
split is reachable only through the registry's one-shot holdout gate.
"""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Callable, Sequence

from trading_lab.catalog import MarketDataCatalog, SplitWindow, walk_forward_folds
from trading_lab.clock import DataAccessPolicy, DatasetBinding
from trading_lab.contracts import (
    CostModel,
    ExperimentSpec,
    PeriodMetrics,
    RiskLimits,
    SplitName,
    StrategySpec,
    StressResult,
    utc_iso,
)
from trading_lab.engine import EngineConfig, NullSink, RunResult, SimulationEngine
from trading_lab.evaluation import (
    EvaluationInput,
    PromotionCriteria,
    RunSummaryInput,
    build_report,
    parameter_sensitivity,
    returns_from_curve,
    stress_scenarios,
    summarise,
)
from trading_lab.strategies import default_param_space, resolve_family

MAX_GRID_COMBINATIONS = 20000


def param_combinations(
    space: dict[str, Sequence[Any]],
    *,
    method: str = "grid",
    budget: int = 50,
    seed: int = 7,
    fixed: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Bounded, reproducible parameter sample."""
    fixed = dict(fixed or {})
    if not space:
        return [dict(fixed)]
    keys = sorted(space)
    values = [list(space[key]) for key in keys]
    total = 1
    for column in values:
        total *= max(1, len(column))
    rng = random.Random(seed)

    if method == "grid" and total <= min(budget, MAX_GRID_COMBINATIONS):
        combinations = [dict(zip(keys, combo)) for combo in itertools.product(*values)]
    elif method == "random" or (method == "grid" and total > budget):
        seen: set[tuple] = set()
        combinations = []
        attempts = 0
        while len(combinations) < budget and attempts < budget * 20:
            attempts += 1
            candidate = tuple(rng.choice(column) for column in values)
            if candidate in seen:
                continue
            seen.add(candidate)
            combinations.append(dict(zip(keys, candidate)))
    elif method == "sequential_refinement":
        combinations = _sequential(keys, values, budget=budget, rng=rng)
    else:  # single
        combinations = [{key: values[index][0] for index, key in enumerate(keys)}]

    for combination in combinations:
        combination.update(fixed)
    return combinations[: max(1, budget)]


def _sequential(keys: list[str], values: list[list[Any]], *, budget: int, rng: random.Random) -> list[dict[str, Any]]:
    """Coordinate sweep: vary one parameter at a time around a centre point.

    Cheaper than a grid and, more importantly, it produces a neighbourhood around the
    candidate, which is exactly what the parameter-sensitivity check needs.
    """
    centre = {key: values[index][len(values[index]) // 2] for index, key in enumerate(keys)}
    out: list[dict[str, Any]] = [dict(centre)]
    for index, key in enumerate(keys):
        for value in values[index]:
            candidate = dict(centre)
            candidate[key] = value
            if candidate not in out:
                out.append(candidate)
            if len(out) >= budget:
                return out
    while len(out) < budget:
        candidate = {key: rng.choice(values[index]) for index, key in enumerate(keys)}
        if candidate not in out:
            out.append(candidate)
        else:
            break
    return out


@dataclass
class TrialResult:
    trial_index: int
    params: dict[str, Any]
    status: str
    metrics: PeriodMetrics | None = None
    run: RunResult | None = None
    error: str = ""
    returns: list[float] = field(default_factory=list)

    def as_row(self) -> dict[str, Any]:
        metrics = self.metrics
        return {
            "trial_index": self.trial_index,
            "params": self.params,
            "status": self.status,
            "error": self.error,
            "net_return": metrics.net_return if metrics else None,
            "sharpe": metrics.sharpe if metrics else None,
            "max_drawdown": metrics.max_drawdown if metrics else None,
            "trades": metrics.trades if metrics else 0,
            "observations": metrics.observations if metrics else 0,
            "costs_paid": metrics.costs_paid if metrics else 0.0,
            "insufficient_evidence": metrics.insufficient_evidence if metrics else True,
            "benchmark_net_return": metrics.benchmark_net_return if metrics else None,
            "warnings": self.run.warnings if self.run else [],
        }


class ExperimentRunner:
    """Runs one :class:`ExperimentSpec` as a set of trials on the development split."""

    def __init__(
        self,
        *,
        store: Any,
        catalog: MarketDataCatalog,
        registry: Any,
        bar_store: Any,
    ) -> None:
        self.store = store
        self.catalog = catalog
        self.registry = registry
        self.bar_store = bar_store

    # --- bindings ----------------------------------------------------------------

    def bindings_for(
        self,
        instruments: Sequence[str],
        timeframe: str,
        *,
        dataset_ids: Sequence[str] = (),
        split: SplitName = "development",
    ) -> tuple[dict[str, DatasetBinding], list[dict[str, Any]], list[str]]:
        bindings: dict[str, DatasetBinding] = {}
        datasets: list[dict[str, Any]] = []
        problems: list[str] = []
        wanted = {str(item) for item in dataset_ids}
        for instrument_id in instruments:
            dataset = None
            if wanted:
                for dataset_id in wanted:
                    candidate = self.catalog.get(dataset_id)
                    if candidate and candidate.get("instrument_id") == instrument_id and candidate.get("timeframe") == timeframe:
                        dataset = candidate
                        break
            if dataset is None:
                dataset = self.catalog.resolve(instrument_id, timeframe)
            if dataset is None:
                problems.append(f"no_dataset_for:{instrument_id}@{timeframe}")
                continue
            datasets.append(dataset)
            bindings[instrument_id] = DatasetBinding(
                instrument_id=instrument_id,
                dataset_id=dataset["dataset_id"],
                timeframe=timeframe,
                split=split,
                data_level=dataset.get("data_level", "ohlcv"),
                availability_delay_seconds=int(dataset.get("availability_delay_seconds", 0) or 0),
                calendar=dataset.get("calendar", "24x7"),
                is_synthetic=bool(dataset.get("is_synthetic")),
                checksum=str(dataset.get("content_checksum", "")),
            )
        return bindings, datasets, problems

    def split_window(self, datasets: Sequence[dict[str, Any]], split: SplitName) -> SplitWindow | None:
        """Intersection of the requested split across every dataset in the run."""
        windows = []
        for dataset in datasets:
            for window in self.catalog.splits(dataset):
                if window.name == split:
                    windows.append(window)
        if not windows:
            return None
        start = max(window.start for window in windows)
        end = min(window.end for window in windows)
        if start >= end:
            return None
        return SplitWindow(split, start, end)

    # --- single run --------------------------------------------------------------

    def run_once(
        self,
        strategy: StrategySpec,
        *,
        run_id: str,
        bindings: dict[str, DatasetBinding],
        start: str,
        end: str,
        starting_cash: Decimal,
        base_currency: str,
        cost_model: CostModel,
        risk_limits: RiskLimits,
        seed: int,
        split: SplitName,
        sink: Any | None = None,
        models: dict[str, Any] | None = None,
        mode: str = "backtest",
        control: Any | None = None,
        max_events: int | None = None,
        policy: DataAccessPolicy | None = None,
    ) -> tuple[RunResult, EngineConfig]:
        config = EngineConfig(
            run_id=run_id,
            strategy=strategy,
            bindings=bindings,
            start=start,
            end=end,
            mode=mode,
            split=split,
            base_currency=base_currency,
            starting_cash=starting_cash,
            cost_model=cost_model,
            risk_limits=risk_limits,
            seed=seed,
            models=models or {},
        )
        engine = SimulationEngine(
            config,
            bar_store=self.bar_store,
            registry=self.registry,
            event_store=self.store,
            sink=sink or NullSink(),
            control=control,
            policy=policy,
        )
        result = engine.run(max_events=max_events)
        return result, config

    # --- search ------------------------------------------------------------------

    def run_experiment(
        self,
        spec: ExperimentSpec,
        *,
        experiment_id: str,
        base_strategy: StrategySpec,
        progress: Callable[[dict[str, Any]], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        family = resolve_family(spec.strategy_family)
        bindings, datasets, problems = self.bindings_for(
            spec.instruments, spec.timeframe, dataset_ids=spec.dataset_ids, split=spec.split
        )
        if problems:
            return {"status": "failed", "error": "; ".join(problems), "trials": []}
        window = self.split_window(datasets, spec.split)
        if window is None:
            return {"status": "failed", "error": f"no_usable_window_for_split:{spec.split}", "trials": []}

        space = spec.param_space or default_param_space(family)
        combinations = param_combinations(
            space,
            method=spec.search_method,
            budget=spec.search_budget,
            seed=spec.seed,
            fixed=spec.fixed_params,
        )
        trials: list[TrialResult] = []
        for index, params in enumerate(combinations):
            if should_stop and should_stop():
                break
            strategy = base_strategy.model_copy(
                update={
                    "family": family,
                    "params": {**base_strategy.params, **params},
                    "instruments": list(spec.instruments),
                    "timeframe": spec.timeframe,
                }
            )
            trial = self._run_trial(
                index=index,
                strategy=strategy,
                spec=spec,
                experiment_id=experiment_id,
                bindings=bindings,
                window=window,
                datasets=datasets,
            )
            trials.append(trial)
            row = trial.as_row()
            self.store.record_trial(
                experiment_id,
                trial_index=trial.trial_index,
                params=trial.params,
                status=trial.status,
                metrics={key: value for key, value in row.items() if key not in {"params", "status", "trial_index"}},
                run_id=f"{experiment_id}:trial:{index}",
                split=spec.split,
                dataset_hash=",".join(sorted(binding.checksum for binding in bindings.values())),
                code_hash=strategy.content_hash(),
                error=trial.error or None,
            )
            if progress:
                progress(
                    {
                        "experiment_id": experiment_id,
                        "completed": len(trials),
                        "total": len(combinations),
                        "last_status": trial.status,
                    }
                )

        ranked = sorted(
            [trial for trial in trials if trial.metrics and trial.status == "completed"],
            key=lambda trial: (
                -(trial.metrics.sharpe if trial.metrics and trial.metrics.sharpe is not None else -99.0),
                -(trial.metrics.net_return if trial.metrics else -99.0),
            ),
        )
        sensitivity = parameter_sensitivity([trial.as_row() for trial in trials])
        best = ranked[0] if ranked else None
        return {
            "status": "completed",
            "experiment_id": experiment_id,
            "trials_run": len(trials),
            "trials_planned": len(combinations),
            "window": window.as_json(),
            "dataset_ids": [dataset["dataset_id"] for dataset in datasets],
            "best": None if best is None else {"params": best.params, "metrics": best.metrics.model_dump() if best.metrics else None},
            "ranking": [
                {"params": trial.params, "sharpe": trial.metrics.sharpe if trial.metrics else None, "net_return": trial.metrics.net_return if trial.metrics else None}
                for trial in ranked[:20]
            ],
            "parameter_sensitivity": sensitivity,
            "search_trials_considered": len(trials),
            "note": (
                f"{len(trials)} configurations were evaluated on the {spec.split} split. The best of "
                f"{len(trials)} is not a single-trial result and must be deflated accordingly."
            ),
        }

    def _run_trial(
        self,
        *,
        index: int,
        strategy: StrategySpec,
        spec: ExperimentSpec,
        experiment_id: str,
        bindings: dict[str, DatasetBinding],
        window: SplitWindow,
        datasets: Sequence[dict[str, Any]],
    ) -> TrialResult:
        run_id = f"{experiment_id}:trial:{index}"
        try:
            from trading_lab.experience import DecisionCaptureSink

            result, _config = self.run_once(
                strategy,
                run_id=run_id,
                bindings=bindings,
                start=window.start,
                end=window.end,
                starting_cash=spec.starting_cash,
                base_currency=spec.base_currency,
                cost_model=spec.cost_model,
                risk_limits=spec.risk_limits,
                seed=spec.seed + index,
                split=spec.split,
                sink=DecisionCaptureSink(self.store, run_id),
            )
        except Exception as exc:  # noqa: BLE001 - a failed trial is data, not a crash
            return TrialResult(trial_index=index, params=strategy.params, status="failed", error=f"{type(exc).__name__}: {exc}")

        dataset = datasets[0] if datasets else {}
        metrics = summarise(
            RunSummaryInput(
                label=f"trial_{index}",
                split=spec.split,
                equity_curve=result.equity_curve,
                benchmark_curve=result.benchmark_curve,
                trades=result.fills,
                costs_paid=float(result.costs.get("fees_paid", "0") or 0),
                timeframe=spec.timeframe,
                calendar=dataset.get("calendar", "24x7"),
            )
        )
        return TrialResult(
            trial_index=index,
            params=strategy.params,
            status="completed" if result.status in {"completed", "truncated"} else result.status,
            metrics=metrics,
            run=result,
            returns=returns_from_curve(result.equity_curve),
        )

    # --- validation --------------------------------------------------------------

    def walk_forward(
        self,
        strategy: StrategySpec,
        *,
        run_prefix: str,
        split: SplitName,
        folds: int = 4,
        scheme: str = "expanding",
        starting_cash: Decimal = Decimal("100000"),
        base_currency: str = "USD",
        cost_model: CostModel | None = None,
        risk_limits: RiskLimits | None = None,
        seed: int = 7,
        dataset_ids: Sequence[str] = (),
        models: dict[str, Any] | None = None,
        policy: DataAccessPolicy | None = None,
    ) -> dict[str, Any]:
        """Chronological out-of-sample folds. The training half is not re-optimised here.

        Re-fitting per fold is only meaningful for the model-driven family; for parameter
        strategies the parameters are already fixed by the search, and re-optimising inside the
        evaluation would put the selection back into the number being reported.
        """
        bindings, datasets, problems = self.bindings_for(
            strategy.instruments, strategy.timeframe, dataset_ids=dataset_ids, split=split
        )
        if problems:
            return {"status": "failed", "error": "; ".join(problems)}
        window = self.split_window(datasets, split)
        if window is None:
            return {"status": "failed", "error": f"no_usable_window_for_split:{split}"}
        fold_windows = walk_forward_folds(window.start, window.end, folds=folds, scheme=scheme)
        if not fold_windows:
            return {"status": "failed", "error": "window_too_short_for_folds"}

        fold_metrics: list[PeriodMetrics] = []
        fold_returns: list[list[float]] = []
        runs: list[dict[str, Any]] = []
        violations: list[str] = []
        dataset = datasets[0] if datasets else {}
        for fold in fold_windows:
            result, _config = self.run_once(
                strategy,
                run_id=f"{run_prefix}:fold{fold['fold']}",
                bindings=bindings,
                start=fold["test_start"],
                end=fold["test_end"],
                starting_cash=starting_cash,
                base_currency=base_currency,
                cost_model=cost_model or CostModel(),
                risk_limits=risk_limits or RiskLimits(),
                seed=seed,
                split=split,
                models=models,
                policy=policy,
            )
            violations.extend(result.lookahead_violations)
            metrics = summarise(
                RunSummaryInput(
                    label=f"fold_{fold['fold']}",
                    split=split,
                    equity_curve=result.equity_curve,
                    benchmark_curve=result.benchmark_curve,
                    trades=result.fills,
                    costs_paid=float(result.costs.get("fees_paid", "0") or 0),
                    timeframe=strategy.timeframe,
                    calendar=dataset.get("calendar", "24x7"),
                )
            )
            fold_metrics.append(metrics)
            fold_returns.append(returns_from_curve(result.equity_curve))
            runs.append({"fold": fold, "result": result.as_json()})
        return {
            "status": "completed",
            "folds": [metrics.model_dump() for metrics in fold_metrics],
            "fold_metrics": fold_metrics,
            "fold_returns": fold_returns,
            "runs": runs,
            "dataset_ids": [item["dataset_id"] for item in datasets],
            "window": window.as_json(),
            "lookahead_violations": violations,
        }

    # --- stress ------------------------------------------------------------------

    def stress(
        self,
        strategy: StrategySpec,
        *,
        run_prefix: str,
        split: SplitName,
        start: str,
        end: str,
        bindings: dict[str, DatasetBinding],
        starting_cash: Decimal,
        base_currency: str,
        cost_model: CostModel,
        risk_limits: RiskLimits,
        seed: int,
        calendar: str = "24x7",
    ) -> list[StressResult]:
        out: list[StressResult] = []
        for scenario in stress_scenarios():
            adjusted = cost_model.model_copy(update=_stress_overrides(cost_model, scenario["cost_overrides"]))
            try:
                result, _config = self.run_once(
                    strategy,
                    run_id=f"{run_prefix}:stress:{scenario['scenario']}",
                    bindings=bindings,
                    start=start,
                    end=end,
                    starting_cash=starting_cash,
                    base_currency=base_currency,
                    cost_model=adjusted,
                    risk_limits=risk_limits,
                    seed=seed,
                    split=split,
                )
            except Exception as exc:  # noqa: BLE001
                out.append(
                    StressResult(
                        scenario=scenario["scenario"],
                        description=scenario["description"],
                        net_return=0.0,
                        max_drawdown=0.0,
                        note=f"scenario_failed:{type(exc).__name__}: {exc}",
                    )
                )
                continue
            metrics = summarise(
                RunSummaryInput(
                    label=scenario["scenario"],
                    split=split,
                    equity_curve=result.equity_curve,
                    trades=result.fills,
                    timeframe=strategy.timeframe,
                    calendar=calendar,
                )
            )
            out.append(
                StressResult(
                    scenario=scenario["scenario"],
                    description=scenario["description"],
                    net_return=metrics.net_return,
                    max_drawdown=metrics.max_drawdown,
                    rejected_orders=result.rejected_orders,
                    note=f"{result.fills} fills, {result.orders_blocked} blocked by risk",
                )
            )
        return out

    # --- full evaluation ---------------------------------------------------------

    def evaluate(
        self,
        strategy: StrategySpec,
        *,
        report_id: str,
        split: SplitName = "validation",
        folds: int = 4,
        scheme: str = "expanding",
        starting_cash: Decimal = Decimal("100000"),
        base_currency: str = "USD",
        cost_model: CostModel | None = None,
        risk_limits: RiskLimits | None = None,
        seed: int = 7,
        search_trials_considered: int = 1,
        parameter_sensitivity_map: dict[str, float] | None = None,
        criteria: PromotionCriteria | None = None,
        evaluated_by: str = "independent_validator",
        include_stress: bool = True,
        models: dict[str, Any] | None = None,
        reproducibility: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = DataAccessPolicy.for_evaluator(report_id, splits=(split,))
        walk = self.walk_forward(
            strategy,
            run_prefix=report_id,
            split=split,
            folds=folds,
            scheme=scheme,
            starting_cash=starting_cash,
            base_currency=base_currency,
            cost_model=cost_model,
            risk_limits=risk_limits,
            seed=seed,
            models=models,
            policy=policy,
        )
        if walk.get("status") != "completed":
            return walk

        stress: list[StressResult] = []
        if include_stress:
            bindings, datasets, _problems = self.bindings_for(strategy.instruments, strategy.timeframe, split=split)
            window = self.split_window(datasets, split)
            if window:
                stress = self.stress(
                    strategy,
                    run_prefix=report_id,
                    split=split,
                    start=window.start,
                    end=window.end,
                    bindings=bindings,
                    starting_cash=starting_cash,
                    base_currency=base_currency,
                    cost_model=cost_model or CostModel(),
                    risk_limits=risk_limits or RiskLimits(),
                    seed=seed,
                    calendar=(datasets[0].get("calendar", "24x7") if datasets else "24x7"),
                )

        quality_notes = []
        for dataset_id in walk.get("dataset_ids", []):
            dataset = self.catalog.get(dataset_id)
            if not dataset:
                continue
            if dataset.get("is_synthetic"):
                quality_notes.append(f"{dataset_id} is SYNTHETIC data — results say nothing about real markets")
            if not dataset.get("frozen"):
                quality_notes.append(f"{dataset_id} is not frozen, so its contents can still change")
            quality = dataset.get("quality") or {}
            if quality.get("gap_ratio"):
                quality_notes.append(f"{dataset_id} gap ratio {quality['gap_ratio']}")

        report = build_report(
            EvaluationInput(
                report_id=report_id,
                strategy_id=strategy.strategy_id or "",
                strategy_version=strategy.version,
                evaluated_by=evaluated_by,
                protocol=f"walk_forward_{scheme}",
                dataset_ids=walk.get("dataset_ids", []),
                folds=walk["fold_metrics"],
                fold_returns=walk["fold_returns"],
                splits_used=[split],
                search_trials_considered=search_trials_considered,
                parameter_sensitivity=parameter_sensitivity_map or {},
                stress=stress,
                data_quality_note="; ".join(quality_notes) or "no data-quality flags raised",
                reproducibility=reproducibility or {},
                lookahead_violations=walk.get("lookahead_violations", []),
                criteria=criteria or PromotionCriteria(),
                seed=seed,
            )
        )
        return {"status": "completed", "report": report, "walk_forward": walk}


_MULTIPLIED_COST_FIELDS = {
    "taker_fee_bps",
    "maker_fee_bps",
    "half_spread_bps",
    "slippage_bps",
    "max_volume_participation",
}


def _stress_overrides(cost_model: CostModel, overrides: dict[str, Any]) -> dict[str, Any]:
    """Cost fields scale relative to the run's own model; the rest are absolute settings."""
    resolved: dict[str, Any] = {}
    for key, value in overrides.items():
        if key in _MULTIPLIED_COST_FIELDS:
            resolved[key] = Decimal(str(value)) * getattr(cost_model, key)
        elif key == "latency_events":
            resolved[key] = int(value)
        else:
            resolved[key] = Decimal(str(value))
    return resolved


def experiment_defaults(family: str) -> dict[str, Any]:
    family = resolve_family(family)
    return {
        "strategy_family": family,
        "param_space": default_param_space(family),
        "search_method": "grid",
        "search_budget": 24,
        "seed": 7,
        "split": "development",
    }


def preregistration_record(spec: ExperimentSpec, criteria: PromotionCriteria) -> dict[str, Any]:
    """What was declared before the search ran. Stored so it cannot be edited afterwards."""
    return {
        "declared_at": utc_iso(datetime.now(tz=UTC)),
        "objective": spec.objective,
        "strategy_family": spec.strategy_family,
        "instruments": list(spec.instruments),
        "timeframe": spec.timeframe,
        "split": spec.split,
        "search_method": spec.search_method,
        "search_budget": spec.search_budget,
        "seed": spec.seed,
        "param_space": spec.param_space,
        "evaluation_protocol": spec.evaluation_protocol,
        "promotion_criteria": criteria.as_json(),
    }


__all__ = [
    "ExperimentRunner",
    "TrialResult",
    "experiment_defaults",
    "param_combinations",
    "preregistration_record",
]
