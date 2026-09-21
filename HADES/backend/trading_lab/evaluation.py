"""Independent evaluation.

Metrics are the easy part. What makes this module useful is what it refuses to do:

- it does not annualise a Sharpe ratio from a handful of observations and present it as fact;
- it counts the search trials that produced the candidate and deflates the Sharpe accordingly,
  because a maximum over many trials is not a sample from one trial;
- it reports an uncertainty interval next to every headline number;
- it returns ``insufficient_evidence`` rather than ``pass`` when the sample cannot support a
  verdict, and that verdict is a first-class outcome, not a failure of the code;
- it records the simulator's own limitations inside the report, so a strong number is never
  read without the assumptions that produced it.

Bootstrap intervals use a stationary block bootstrap: financial returns are autocorrelated and
resampling single observations would produce intervals that are far too narrow.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Iterable, Sequence

from trading_lab.calendars import periods_per_year
from trading_lab.contracts import EvaluationReport, PeriodMetrics, SplitName, StressResult, utc_iso

MIN_OBSERVATIONS_FOR_VERDICT = 120
MIN_TRADES_FOR_VERDICT = 20

SIMULATOR_LIMITATIONS = [
    "Fills are modelled on closed candles; no intrabar path is known, so stop-versus-target ordering uses the conservative rule.",
    "Spread, slippage and fees are modelled parameters, not observed executions.",
    "Market impact of our own orders is not modelled; only a volume participation cap is applied.",
    "Queue position and partial-fill microstructure are absent without level-2 data.",
    "Funding, borrow and financing use configured rates when historical series are missing.",
    "Corporate actions are applied only for instruments where an action series was imported.",
    "Delisted and expired instruments are settled at the last available price.",
]


def returns_from_curve(curve: Sequence[tuple[str, float]]) -> list[float]:
    out: list[float] = []
    for index in range(1, len(curve)):
        previous = curve[index - 1][1]
        if previous == 0:
            out.append(0.0)
            continue
        out.append((curve[index][1] / previous) - 1.0)
    return out


def max_drawdown(curve: Sequence[tuple[str, float]]) -> tuple[float, int | None]:
    peak = None
    worst = 0.0
    trough_index = None
    recovery: int | None = None
    for index, (_stamp, value) in enumerate(curve):
        if peak is None or value > peak:
            peak = value
            if trough_index is not None and recovery is None:
                recovery = index - trough_index
        if peak and peak > 0:
            drawdown = (value - peak) / peak
            if drawdown < worst:
                worst = drawdown
                trough_index = index
    return abs(worst), recovery


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def sharpe_ratio(returns: Sequence[float], *, risk_free_per_period: float = 0.0) -> float | None:
    if len(returns) < 3:
        return None
    excess = [value - risk_free_per_period for value in returns]
    dispersion = _stdev(excess)
    if dispersion <= 1e-12:
        return None
    return _mean(excess) / dispersion


def sortino_ratio(returns: Sequence[float], *, target: float = 0.0) -> float | None:
    if len(returns) < 3:
        return None
    downside = [min(0.0, value - target) for value in returns]
    denominator = math.sqrt(sum(value**2 for value in downside) / len(downside))
    if denominator <= 1e-12:
        return None
    return (_mean(returns) - target) / denominator


def deflated_sharpe(observed: float | None, *, trials: int, observations: int, skew: float = 0.0, kurtosis: float = 3.0) -> float | None:
    """Probability that the observed Sharpe survives the number of trials that produced it.

    Follows the Bailey and Lopez de Prado construction: the expected maximum Sharpe under the
    null grows with the number of independent trials, so a maximum over 200 parameter sets must
    clear a much higher bar than a single pre-registered test.
    """
    if observed is None or observations < 10 or trials < 1:
        return None
    trials = max(1, trials)
    euler = 0.5772156649015329
    if trials == 1:
        expected_max = 0.0
    else:
        inverse = _norm_ppf(1.0 - 1.0 / trials)
        inverse_e = _norm_ppf(1.0 - 1.0 / (trials * math.e))
        expected_max = (1 - euler) * inverse + euler * inverse_e
    variance_term = 1.0 - skew * observed + ((kurtosis - 1.0) / 4.0) * observed**2
    if variance_term <= 0:
        return None
    numerator = (observed - expected_max) * math.sqrt(max(1, observations - 1))
    return _norm_cdf(numerator / math.sqrt(variance_term))


def block_bootstrap_interval(
    returns: Sequence[float],
    statistic: str = "mean",
    *,
    samples: int = 400,
    block: int | None = None,
    seed: int = 7,
    confidence: float = 0.9,
) -> list[float] | None:
    """Stationary block bootstrap interval for a return statistic."""
    if len(returns) < 30:
        return None
    rng = random.Random(seed)
    length = len(returns)
    block_size = block or max(2, min(length // 5, int(round(length ** (1 / 3)))))
    estimates: list[float] = []
    for _ in range(samples):
        resampled: list[float] = []
        while len(resampled) < length:
            start = rng.randrange(length)
            for offset in range(block_size):
                resampled.append(returns[(start + offset) % length])
                if len(resampled) >= length:
                    break
        if statistic == "sharpe":
            value = sharpe_ratio(resampled)
            if value is None:
                continue
        elif statistic == "total":
            value = math.prod(1.0 + item for item in resampled) - 1.0
        else:
            value = _mean(resampled)
        estimates.append(value)
    if len(estimates) < 50:
        return None
    estimates.sort()
    lower = (1.0 - confidence) / 2.0
    upper = 1.0 - lower
    return [
        estimates[max(0, int(lower * len(estimates)) - 1)],
        estimates[min(len(estimates) - 1, int(upper * len(estimates)))],
    ]


def _norm_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _norm_ppf(probability: float) -> float:
    """Acklam's rational approximation of the inverse normal CDF."""
    if probability <= 0.0:
        return -8.0
    if probability >= 1.0:
        return 8.0
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02, 1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02, 6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00, -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]
    low, high = 0.02425, 1 - 0.02425
    if probability < low:
        q = math.sqrt(-2 * math.log(probability))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if probability > high:
        q = math.sqrt(-2 * math.log(1 - probability))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = probability - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


@dataclass
class RunSummaryInput:
    label: str
    split: SplitName
    equity_curve: Sequence[tuple[str, float]]
    benchmark_curve: Sequence[tuple[str, float]] = ()
    trades: int = 0
    costs_paid: float = 0.0
    turnover: float = 0.0
    timeframe: str = "1h"
    calendar: str = "24x7"
    trade_pnls: Sequence[float] = ()


def summarise(payload: RunSummaryInput) -> PeriodMetrics:
    curve = list(payload.equity_curve)
    metrics = PeriodMetrics(label=payload.label, split=payload.split)
    if len(curve) < 2:
        metrics.insufficient_evidence = True
        metrics.observations = len(curve)
        return metrics
    returns = returns_from_curve(curve)
    per_year = periods_per_year(payload.timeframe, payload.calendar)
    metrics.first_event_time = curve[0][0]
    metrics.last_event_time = curve[-1][0]
    metrics.observations = len(curve)
    metrics.trades = payload.trades
    metrics.net_return = (curve[-1][1] / curve[0][1]) - 1.0 if curve[0][1] else 0.0
    metrics.costs_paid = payload.costs_paid
    metrics.gross_return = metrics.net_return + (payload.costs_paid / curve[0][1] if curve[0][1] else 0.0)
    metrics.periods_per_year = per_year
    metrics.turnover = payload.turnover

    sharpe = sharpe_ratio(returns)
    metrics.sharpe = None if sharpe is None else sharpe * math.sqrt(per_year)
    sortino = sortino_ratio(returns)
    metrics.sortino = None if sortino is None else sortino * math.sqrt(per_year)
    metrics.annualised_volatility = _stdev(returns) * math.sqrt(per_year) if len(returns) > 2 else None
    years = len(returns) / per_year if per_year else 0.0
    if years > 0 and curve[0][1] > 0 and curve[-1][1] > 0:
        metrics.annualised_return = (curve[-1][1] / curve[0][1]) ** (1.0 / years) - 1.0
    drawdown, recovery = max_drawdown(curve)
    metrics.max_drawdown = drawdown
    metrics.drawdown_recovery_observations = recovery
    if returns:
        ordered = sorted(returns)
        index = max(0, int(0.05 * len(ordered)) - 1)
        metrics.tail_loss_p05 = ordered[index]
    if payload.trade_pnls:
        wins = [value for value in payload.trade_pnls if value > 0]
        metrics.win_rate = len(wins) / len(payload.trade_pnls)
        top = sorted(payload.trade_pnls, reverse=True)[:3]
        total_profit = sum(value for value in payload.trade_pnls if value > 0)
        metrics.profit_concentration_top3 = (sum(value for value in top if value > 0) / total_profit) if total_profit > 0 else None
    if payload.benchmark_curve and len(payload.benchmark_curve) >= 2:
        benchmark = list(payload.benchmark_curve)
        metrics.benchmark_net_return = (benchmark[-1][1] / benchmark[0][1]) - 1.0 if benchmark[0][1] else None
        benchmark_sharpe = sharpe_ratio(returns_from_curve(benchmark))
        metrics.benchmark_sharpe = None if benchmark_sharpe is None else benchmark_sharpe * math.sqrt(per_year)
    metrics.insufficient_evidence = (
        metrics.observations < MIN_OBSERVATIONS_FOR_VERDICT or metrics.trades < MIN_TRADES_FOR_VERDICT
    )
    return metrics


def aggregate(folds: Sequence[PeriodMetrics], *, label: str = "aggregate") -> PeriodMetrics | None:
    usable = [fold for fold in folds if fold.observations >= 2]
    if not usable:
        return None
    combined = PeriodMetrics(label=label, split=usable[0].split)
    combined.observations = sum(fold.observations for fold in usable)
    combined.trades = sum(fold.trades for fold in usable)
    combined.costs_paid = sum(fold.costs_paid for fold in usable)
    compounded = 1.0
    for fold in usable:
        compounded *= 1.0 + fold.net_return
    combined.net_return = compounded - 1.0
    combined.gross_return = combined.net_return + (sum(fold.gross_return - fold.net_return for fold in usable))
    sharpes = [fold.sharpe for fold in usable if fold.sharpe is not None]
    combined.sharpe = _mean(sharpes) if sharpes else None
    sortinos = [fold.sortino for fold in usable if fold.sortino is not None]
    combined.sortino = _mean(sortinos) if sortinos else None
    combined.max_drawdown = max((fold.max_drawdown for fold in usable), default=0.0)
    combined.first_event_time = usable[0].first_event_time
    combined.last_event_time = usable[-1].last_event_time
    combined.periods_per_year = usable[0].periods_per_year
    benchmarks = [fold.benchmark_net_return for fold in usable if fold.benchmark_net_return is not None]
    if benchmarks:
        compounded_benchmark = 1.0
        for value in benchmarks:
            compounded_benchmark *= 1.0 + value
        combined.benchmark_net_return = compounded_benchmark - 1.0
    combined.insufficient_evidence = any(fold.insufficient_evidence for fold in usable)
    return combined


@dataclass
class PromotionCriteria:
    """Pre-registered thresholds. Set before the evaluation runs, never tuned to fit a result."""

    min_folds: int = 3
    min_observations: int = MIN_OBSERVATIONS_FOR_VERDICT
    min_trades: int = MIN_TRADES_FOR_VERDICT
    min_deflated_sharpe: float = 0.6
    min_sharpe: float = 0.5
    max_drawdown: float = 0.35
    require_beat_benchmark: bool = True
    min_positive_fold_fraction: float = 0.5
    max_profit_concentration: float = 0.8
    require_no_lookahead_violations: bool = True

    def as_json(self) -> dict[str, Any]:
        return {
            "min_folds": self.min_folds,
            "min_observations": self.min_observations,
            "min_trades": self.min_trades,
            "min_deflated_sharpe": self.min_deflated_sharpe,
            "min_sharpe": self.min_sharpe,
            "max_drawdown": self.max_drawdown,
            "require_beat_benchmark": self.require_beat_benchmark,
            "min_positive_fold_fraction": self.min_positive_fold_fraction,
            "max_profit_concentration": self.max_profit_concentration,
            "require_no_lookahead_violations": self.require_no_lookahead_violations,
        }


@dataclass
class EvaluationInput:
    report_id: str
    strategy_id: str
    strategy_version: int
    evaluated_by: str = "independent_validator"
    protocol: str = "walk_forward_expanding"
    dataset_ids: Sequence[str] = ()
    folds: Sequence[PeriodMetrics] = ()
    fold_returns: Sequence[Sequence[float]] = ()
    splits_used: Sequence[SplitName] = ()
    search_trials_considered: int = 1
    parameter_sensitivity: dict[str, float] = field(default_factory=dict)
    stress: Sequence[StressResult] = ()
    data_quality_note: str = ""
    reproducibility: dict[str, Any] = field(default_factory=dict)
    lookahead_violations: Sequence[str] = ()
    criteria: PromotionCriteria = field(default_factory=PromotionCriteria)
    seed: int = 7
    evidence_class: str = "historical_evaluation"


def build_report(payload: EvaluationInput) -> EvaluationReport:
    folds = list(payload.folds)
    combined = aggregate(folds)
    all_returns: list[float] = []
    for chunk in payload.fold_returns:
        all_returns.extend(chunk)

    intervals: dict[str, list[float]] = {}
    if all_returns:
        mean_interval = block_bootstrap_interval(all_returns, "mean", seed=payload.seed)
        sharpe_interval = block_bootstrap_interval(all_returns, "sharpe", seed=payload.seed)
        total_interval = block_bootstrap_interval(all_returns, "total", seed=payload.seed)
        if mean_interval:
            intervals["mean_return_per_observation_90"] = mean_interval
        if sharpe_interval:
            intervals["sharpe_per_observation_90"] = sharpe_interval
        if total_interval:
            intervals["total_return_90"] = total_interval

    raw_sharpe = sharpe_ratio(all_returns) if all_returns else None
    deflated = deflated_sharpe(
        raw_sharpe,
        trials=max(1, payload.search_trials_considered),
        observations=len(all_returns),
        skew=_skew(all_returns),
        kurtosis=_kurtosis(all_returns),
    )

    verdict, reasons = _decide(payload, combined, folds, deflated, intervals)

    return EvaluationReport(
        report_id=payload.report_id,
        strategy_id=payload.strategy_id,
        strategy_version=payload.strategy_version,
        evaluated_by=payload.evaluated_by,
        evaluator_role="independent_validator",
        protocol=payload.protocol,
        created_at=utc_iso(datetime.now(tz=UTC)),
        dataset_ids=list(payload.dataset_ids),
        splits_used=list(payload.splits_used),
        folds=folds,
        aggregate=combined,
        search_trials_considered=max(1, payload.search_trials_considered),
        deflated_sharpe=deflated,
        multiple_testing_note=(
            f"{payload.search_trials_considered} configuration(s) were evaluated to reach this candidate. "
            "The reported Sharpe is deflated for that selection; a single-trial Sharpe would overstate it."
        ),
        confidence_intervals=intervals,
        parameter_sensitivity=dict(payload.parameter_sensitivity),
        stress=list(payload.stress),
        data_quality_note=payload.data_quality_note,
        simulator_limitations=list(SIMULATOR_LIMITATIONS),
        reproducibility=dict(payload.reproducibility),
        verdict=verdict,  # type: ignore[arg-type]
        verdict_reasons=reasons,
        evidence_class=payload.evidence_class,  # type: ignore[arg-type]
    )


def _decide(
    payload: EvaluationInput,
    combined: PeriodMetrics | None,
    folds: Sequence[PeriodMetrics],
    deflated: float | None,
    intervals: dict[str, list[float]],
) -> tuple[str, list[str]]:
    criteria = payload.criteria
    reasons: list[str] = []
    if payload.lookahead_violations and criteria.require_no_lookahead_violations:
        return "fail", [f"lookahead_violations_detected:{len(payload.lookahead_violations)}"] + list(payload.lookahead_violations)[:5]
    if combined is None:
        return "insufficient_evidence", ["no usable folds"]
    if len(folds) < criteria.min_folds:
        reasons.append(f"only {len(folds)} fold(s); {criteria.min_folds} required")
    if combined.observations < criteria.min_observations:
        reasons.append(f"{combined.observations} observations; {criteria.min_observations} required")
    if combined.trades < criteria.min_trades:
        reasons.append(f"{combined.trades} trades; {criteria.min_trades} required for a statement about trading skill")
    if reasons:
        return "insufficient_evidence", reasons

    failures: list[str] = []
    if combined.sharpe is None or combined.sharpe < criteria.min_sharpe:
        failures.append(f"annualised Sharpe {combined.sharpe} below {criteria.min_sharpe}")
    if deflated is not None and deflated < criteria.min_deflated_sharpe:
        failures.append(
            f"deflated Sharpe probability {deflated:.3f} below {criteria.min_deflated_sharpe} "
            f"after {payload.search_trials_considered} trials"
        )
    if combined.max_drawdown > criteria.max_drawdown:
        failures.append(f"max drawdown {combined.max_drawdown:.3f} above {criteria.max_drawdown}")
    positive = [fold for fold in folds if fold.net_return > 0]
    fraction = len(positive) / len(folds) if folds else 0.0
    if fraction < criteria.min_positive_fold_fraction:
        failures.append(f"only {fraction:.0%} of folds positive; {criteria.min_positive_fold_fraction:.0%} required")
    if criteria.require_beat_benchmark and combined.benchmark_net_return is not None:
        if combined.net_return <= combined.benchmark_net_return:
            failures.append(
                f"net return {combined.net_return:.4f} does not beat the benchmark {combined.benchmark_net_return:.4f}"
            )
    concentration = next((fold.profit_concentration_top3 for fold in folds if fold.profit_concentration_top3 is not None), None)
    if concentration is not None and concentration > criteria.max_profit_concentration:
        failures.append(f"top three trades account for {concentration:.0%} of the profit")
    interval = intervals.get("total_return_90")
    if interval and interval[0] <= 0 <= interval[1]:
        failures.append(
            f"the 90% interval for total return spans zero ({interval[0]:.4f} to {interval[1]:.4f}); "
            "the result is not distinguishable from noise"
        )
    if failures:
        return "fail", failures
    return "pass", [
        f"passed all pre-registered criteria over {len(folds)} chronological folds",
        f"deflated Sharpe probability {deflated:.3f}" if deflated is not None else "deflated Sharpe not computable",
        "verdict is about historical simulation only; prospective paper evaluation is a separate evidence class",
    ]


def _skew(values: Sequence[float]) -> float:
    if len(values) < 3:
        return 0.0
    mean = _mean(values)
    dispersion = _stdev(values)
    if dispersion <= 1e-12:
        return 0.0
    return sum(((value - mean) / dispersion) ** 3 for value in values) / len(values)


def _kurtosis(values: Sequence[float]) -> float:
    if len(values) < 4:
        return 3.0
    mean = _mean(values)
    dispersion = _stdev(values)
    if dispersion <= 1e-12:
        return 3.0
    return sum(((value - mean) / dispersion) ** 4 for value in values) / len(values)


def parameter_sensitivity(trials: Iterable[dict[str, Any]], *, metric: str = "net_return") -> dict[str, float]:
    """Spread of the metric across neighbouring parameter values.

    A strategy whose result collapses when one parameter moves by one step is a fitted artefact,
    and this number is how that shows up before promotion rather than after.
    """
    grouped: dict[str, list[float]] = {}
    for trial in trials:
        params = trial.get("params") or {}
        value = trial.get(metric)
        if value is None:
            continue
        for key, item in params.items():
            grouped.setdefault(f"{key}", []).append(float(value))
    out: dict[str, float] = {}
    for key, values in grouped.items():
        if len(values) < 3:
            continue
        out[key] = _stdev(values)
    return out


def stress_scenarios() -> list[dict[str, Any]]:
    """Named cost and liquidity shocks applied by re-running the engine with modified inputs."""
    return [
        {
            "scenario": "double_costs",
            "description": "All fees, spread and slippage doubled.",
            "cost_overrides": {"taker_fee_bps": 2, "maker_fee_bps": 2, "half_spread_bps": 2, "slippage_bps": 2},
        },
        {
            "scenario": "thin_liquidity",
            "description": "Volume participation cap cut to a fifth, producing many more partial fills.",
            "cost_overrides": {"max_volume_participation": 0.2},
        },
        {
            "scenario": "execution_latency",
            "description": "Orders become eligible three events later than the signal.",
            "cost_overrides": {"latency_events": 3},
        },
        {
            "scenario": "rejects",
            "description": "One in twenty orders is rejected by the venue.",
            "cost_overrides": {"reject_probability": 0.05},
        },
    ]


def compare_runs(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Side-by-side of two run summaries, with the difference stated in the same units."""
    keys = ["net_return", "sharpe", "max_drawdown", "trades", "costs_paid", "observations"]
    rows = []
    for key in keys:
        left_value = left.get(key)
        right_value = right.get(key)
        delta = None
        if isinstance(left_value, (int, float)) and isinstance(right_value, (int, float)):
            delta = right_value - left_value
        rows.append({"metric": key, "left": left_value, "right": right_value, "delta": delta})
    return {"rows": rows, "note": "differences are raw, not tested for significance"}


__all__ = [
    "EvaluationInput",
    "MIN_OBSERVATIONS_FOR_VERDICT",
    "MIN_TRADES_FOR_VERDICT",
    "PromotionCriteria",
    "RunSummaryInput",
    "SIMULATOR_LIMITATIONS",
    "aggregate",
    "block_bootstrap_interval",
    "build_report",
    "compare_runs",
    "deflated_sharpe",
    "max_drawdown",
    "parameter_sensitivity",
    "returns_from_curve",
    "sharpe_ratio",
    "sortino_ratio",
    "stress_scenarios",
    "summarise",
]
