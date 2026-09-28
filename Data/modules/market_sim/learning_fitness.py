"""Server-side strategy fitness from measured kernel metrics — never frontend/LLM authority."""

from __future__ import annotations

import math
from typing import Any

from .learning_types import (
    FailureCategory,
    FitnessComponent,
    FitnessResult,
    LearningObjectiveSpec,
    MeasurementStatus,
)
from .strategy_dsl import parse_strategy_spec


def _finite(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        if raw.get("status") == "UNMEASURED" or raw.get("value") is None:
            return None
        raw = raw.get("value")
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(val) or math.isinf(val):
        return None
    return val


def extract_metric(metrics: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in metrics:
            val = _finite(metrics.get(key))
            if val is not None:
                return val
            # Key present but invalid → INVALID, not silent miss
            raw = metrics.get(key)
            if isinstance(raw, dict) and raw.get("status") == "UNMEASURED":
                continue
            if raw is not None:
                return None  # present but non-finite → caller treats as INVALID
    return None


def measure_strategy_complexity(
    entry_rules: dict[str, Any],
    exit_rules: dict[str, Any] | None = None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, int]:
    spec = parse_strategy_spec(entry_rules, exit_rules=exit_rules, parameters=parameters)
    params = dict(spec.parameters or {})
    n_params = len(params)
    n_filters = len(spec.filters or [])
    n_conditions = 0
    for blob in (spec.entry, spec.exit):
        if isinstance(blob, dict):
            n_conditions += sum(1 for k in blob if k not in {"kind", "version", "parameters", "filters"})
    n_indicators = 0
    for key in ("period", "fast", "slow", "fast_ma", "slow_ma", "lookback", "left", "right_feature"):
        if key in params or key in (spec.entry or {}) or key in (spec.exit or {}):
            n_indicators += 1
    n_composite = len(spec.composite_signals or [])
    n_risk = sum(
        1
        for blob in (spec.stop_loss, spec.take_profit, spec.trailing_stop, spec.time_stop)
        if blob
    ) + len(spec.risk_conditions or [])
    return {
        "number_of_conditions": n_conditions,
        "number_of_indicators": max(n_indicators, 1 if spec.kind != "hold" else 0),
        "number_of_filters": n_filters,
        "number_of_parameters": n_params,
        "number_of_composite_signals": n_composite,
        "number_of_risk_rules": n_risk,
        "total": n_conditions + n_indicators + n_filters + n_params + n_composite + n_risk,
    }


def classify_failures(
    metrics: dict[str, Any],
    *,
    objective: LearningObjectiveSpec,
    fitness: FitnessResult | None = None,
) -> list[str]:
    cats: list[str] = []
    trades = extract_metric(metrics, "trade_count", "trades")
    if trades is None and ("trade_count" in metrics or "trades" in metrics):
        cats.append(FailureCategory.EXECUTION_FAILURE.value)
    elif trades is not None and trades < objective.min_trades:
        cats.append(FailureCategory.INSUFFICIENT_TRADES.value)
    dd = extract_metric(metrics, "max_drawdown_pct")
    if dd is not None and abs(dd) > objective.max_drawdown_pct:
        cats.append(FailureCategory.EXCESSIVE_DRAWDOWN.value)
    ret = extract_metric(metrics, "total_return_pct", "total_return")
    if ret is not None and ret < 0:
        cats.append(FailureCategory.NEGATIVE_RETURN.value)
    if fitness and fitness.failure_categories:
        for c in fitness.failure_categories:
            if c not in cats:
                cats.append(c)
    return cats


def _component(name: str, value: float | None, *, present_invalid: bool = False) -> FitnessComponent:
    if present_invalid:
        return FitnessComponent(name=name, value=None, status=MeasurementStatus.INVALID.value, detail="non-finite")
    if value is None:
        return FitnessComponent(name=name, value=None, status=MeasurementStatus.UNMEASURED.value)
    return FitnessComponent(name=name, value=float(value), status=MeasurementStatus.MEASURED.value)


def derive_expectancy_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    """Derive expectancy / payoff metrics from measured trial data.

    Never infers missing costs as zero. Missing → UNMEASURED.
    High win_rate with negative expectancy is explicitly surfaced.
    """
    metrics = dict(metrics or {})
    out: dict[str, Any] = {}

    def _m(*keys: str) -> float | None:
        return extract_metric(metrics, *keys)

    win_rate = _m("win_rate", "winRate")
    loss_rate = _m("loss_rate", "lossRate")
    avg_win = _m("average_win", "avg_win", "averageWin")
    avg_loss = _m("average_loss", "avg_loss", "averageLoss")
    trade_count = _m("trade_count", "trades")
    total_pnl = _m("total_pnl", "net_pnl", "realized_pnl")
    gross_return = _m("gross_return", "gross_return_pct")
    net_return = _m("net_return", "total_return_pct", "total_return", "net_return_pct")
    fee_drag = _m("fee_drag", "fee_drag_pct", "total_fees")
    slip_drag = _m("slippage_drag", "slippage_drag_pct", "total_slippage")
    cost_drag = _m("cost_drag", "cost_drag_pct", "total_cost")
    profit_factor = _m("profit_factor", "profitFactor")
    expectancy = _m("expectancy_per_trade", "expectancy", "net_expectancy")

    if loss_rate is None and win_rate is not None:
        loss_rate = max(0.0, 1.0 - float(win_rate))

    payoff_ratio = None
    if avg_win is not None and avg_loss is not None and abs(float(avg_loss)) > 1e-12:
        payoff_ratio = abs(float(avg_win) / float(avg_loss))

    # Expectancy per trade = p(win)*avg_win - p(loss)*|avg_loss|
    if expectancy is None and win_rate is not None and avg_win is not None and avg_loss is not None:
        lr = float(loss_rate) if loss_rate is not None else max(0.0, 1.0 - float(win_rate))
        expectancy = float(win_rate) * float(avg_win) - lr * abs(float(avg_loss))

    # Prefer explicit net expectancy; else expectancy after known cost drag per trade
    net_expectancy = _m("net_expectancy", "netExpectancy")
    if net_expectancy is None and expectancy is not None:
        # Only subtract cost_drag when measured — never assume zero costs
        if cost_drag is not None and trade_count is not None and float(trade_count) > 0:
            net_expectancy = float(expectancy) - (float(cost_drag) / float(trade_count))
        elif fee_drag is not None and slip_drag is not None and trade_count is not None and float(trade_count) > 0:
            net_expectancy = float(expectancy) - ((float(fee_drag) + float(slip_drag)) / float(trade_count))
        elif cost_drag is None and fee_drag is None and slip_drag is None:
            # Costs unmeasured → net expectancy UNMEASURED (do not treat as gross)
            net_expectancy = None
        else:
            net_expectancy = float(expectancy)

    if profit_factor is None and avg_win is not None and avg_loss is not None and win_rate is not None:
        lr = float(loss_rate) if loss_rate is not None else max(0.0, 1.0 - float(win_rate))
        gross_wins = float(win_rate) * abs(float(avg_win))
        gross_losses = lr * abs(float(avg_loss))
        if gross_losses > 1e-12:
            profit_factor = gross_wins / gross_losses

    def _pack(name: str, val: float | None) -> None:
        if val is None:
            out[name] = None
            out[f"{name}_status"] = MeasurementStatus.UNMEASURED.value
        else:
            out[name] = float(val)
            out[f"{name}_status"] = MeasurementStatus.MEASURED.value

    _pack("win_rate", win_rate)
    _pack("loss_rate", loss_rate)
    _pack("average_win", avg_win)
    _pack("average_loss", avg_loss)
    _pack("win_loss_payoff_ratio", payoff_ratio)
    _pack("expectancy_per_trade", expectancy)
    _pack("net_expectancy", net_expectancy)
    _pack("profit_factor", profit_factor)
    _pack("gross_return", gross_return)
    _pack("net_return", net_return)
    _pack("total_pnl", total_pnl)
    _pack("cost_drag", cost_drag)
    _pack("fee_drag", fee_drag)
    _pack("slippage_drag", slip_drag)

    # Honesty flags for promotion language
    out["truth"] = {
        "win_rate_is_not_profitability": True,
        "missing_costs_not_assumed_zero": True,
        "net_expectancy_requires_measured_costs_or_explicit_net": True,
        "high_win_rate_negative_expectancy_is_not_profitable": bool(
            win_rate is not None
            and net_expectancy is not None
            and float(win_rate) >= 0.6
            and float(net_expectancy) < 0
        ),
    }
    return out


def ranks_by_expectancy_not_win_rate(
    case_a: dict[str, Any],
    case_b: dict[str, Any],
    *,
    objective: LearningObjectiveSpec | None = None,
) -> dict[str, Any]:
    """Compare two metric packs: negative-expectancy high win-rate must not beat positive expectancy.

    Used by Wave 12 tests (CASE 1 vs CASE 2).
    """
    obj = objective or LearningObjectiveSpec(objective_id="expectancy-rank")
    fa = compute_fitness(candidate_id="a", split_role="TRAIN", metrics=case_a, objective=obj)
    fb = compute_fitness(candidate_id="b", split_role="TRAIN", metrics=case_b, objective=obj)
    ea = derive_expectancy_metrics(case_a)
    eb = derive_expectancy_metrics(case_b)
    a_trap = bool(ea.get("truth", {}).get("high_win_rate_negative_expectancy_is_not_profitable"))
    # Prefer net expectancy when both measured; else scalar fitness
    a_exp = ea.get("net_expectancy")
    b_exp = eb.get("net_expectancy")
    if a_exp is not None and b_exp is not None:
        winner = "b" if float(b_exp) > float(a_exp) else "a"
    else:
        sa = fa.scalar_score
        sb = fb.scalar_score
        if sa is None and sb is None:
            winner = "tie_unmeasured"
        elif sa is None:
            winner = "b"
        elif sb is None:
            winner = "a"
        else:
            winner = "b" if float(sb) > float(sa) else "a"
    return {
        "winner": winner,
        "case_a_expectancy": ea,
        "case_b_expectancy": eb,
        "case_a_fitness": fa.public_dict() if hasattr(fa, "public_dict") else {"scalar": fa.scalar_score},
        "case_b_fitness": fb.public_dict() if hasattr(fb, "public_dict") else {"scalar": fb.scalar_score},
        "case_a_is_win_rate_trap": a_trap,
        "truth": {"win_rate_not_authority": True},
    }


def compute_fitness(
    *,
    candidate_id: str,
    split_role: str,
    metrics: dict[str, Any],
    objective: LearningObjectiveSpec,
    complexity: dict[str, int] | None = None,
    required_components: list[str] | None = None,
) -> FitnessResult:
    """Compute fitness vector from measured metrics. Missing ≠ 0; NaN/inf ≠ PASS."""
    metrics = dict(metrics or {})
    components: dict[str, FitnessComponent] = {}
    failures: list[str] = []
    categories: list[str] = []

    def _get(keys: tuple[str, ...]) -> tuple[float | None, bool]:
        for key in keys:
            if key not in metrics:
                continue
            val = _finite(metrics.get(key))
            if val is None:
                raw = metrics.get(key)
                if isinstance(raw, dict) and raw.get("status") == "UNMEASURED":
                    return None, False
                return None, True  # present invalid
            return val, False
        return None, False

    ret, ret_inv = _get(("total_return_pct", "total_return"))
    # Prefer percent scale for return_quality when available
    if "total_return_pct" in metrics:
        ret_pct, ret_inv = _get(("total_return_pct",))
        ret = ret_pct
    sharpe, sharpe_inv = _get(("sharpe",))
    sortino, sortino_inv = _get(("sortino",))
    dd, dd_inv = _get(("max_drawdown_pct",))
    if dd is None and "max_drawdown" in metrics and "max_drawdown_pct" not in metrics:
        failures.append("max_drawdown unit ambiguous — require max_drawdown_pct")
        categories.append(FailureCategory.EXECUTION_FAILURE.value)
        dd_inv = True
    trades, trades_inv = _get(("trade_count", "trades"))
    turnover, turn_inv = _get(("turnover", "turnover_pct"))
    costs, cost_inv = _get(("total_fees", "total_cost", "cost_drag_pct"))
    calmar, calmar_inv = _get(("calmar",))

    # return_quality: tanh-scaled return (MEASURED only)
    if ret is not None:
        components["return_quality"] = _component("return_quality", math.tanh(ret / 50.0))
    else:
        components["return_quality"] = _component("return_quality", None, present_invalid=ret_inv)

    if sharpe is not None:
        components["risk_adjusted_return"] = _component("risk_adjusted_return", math.tanh(sharpe / 3.0))
    elif sortino is not None:
        components["risk_adjusted_return"] = _component("risk_adjusted_return", math.tanh(sortino / 3.0))
    else:
        components["risk_adjusted_return"] = _component(
            "risk_adjusted_return", None, present_invalid=sharpe_inv or sortino_inv
        )

    if dd is not None:
        # Lower drawdown → higher quality
        quality = max(0.0, 1.0 - abs(dd) / max(objective.max_drawdown_pct, 1e-6))
        components["drawdown_quality"] = _component("drawdown_quality", quality)
        if abs(dd) > objective.max_drawdown_pct:
            failures.append(f"drawdown {dd} > {objective.max_drawdown_pct}")
            categories.append(FailureCategory.EXCESSIVE_DRAWDOWN.value)
    else:
        components["drawdown_quality"] = _component("drawdown_quality", None, present_invalid=dd_inv)
        failures.append("max_drawdown_pct UNMEASURED")

    if trades is not None:
        sufficiency = min(1.0, float(trades) / max(objective.min_trades, 1))
        components["trade_sufficiency"] = _component("trade_sufficiency", sufficiency)
        if trades < objective.min_trades:
            failures.append(f"trades {trades} < {objective.min_trades}")
            categories.append(FailureCategory.INSUFFICIENT_TRADES.value)
    else:
        components["trade_sufficiency"] = _component("trade_sufficiency", None, present_invalid=trades_inv)
        failures.append("trade_count UNMEASURED")

    # Stability proxy: prefer calmar / inverse dd when measured
    if calmar is not None:
        components["stability"] = _component("stability", math.tanh(calmar / 2.0))
    elif dd is not None and ret is not None:
        components["stability"] = _component("stability", math.tanh((ret / max(abs(dd), 1.0)) / 5.0))
    else:
        components["stability"] = _component("stability", None, present_invalid=calmar_inv)

    # Optional / often unmeasured components — label honestly
    for name in (
        "regime_robustness",
        "validation_stability",
        "concentration_quality",
    ):
        components[name] = _component(name, None)

    if costs is not None:
        # lower costs better; normalize loosely
        components["execution_cost_quality"] = _component(
            "execution_cost_quality", max(0.0, 1.0 - abs(costs) / 1000.0)
        )
    else:
        components["execution_cost_quality"] = _component(
            "execution_cost_quality", None, present_invalid=cost_inv
        )

    if turnover is not None:
        components["turnover_quality"] = _component(
            "turnover_quality", max(0.0, 1.0 - abs(turnover) / 100.0)
        )
    else:
        components["turnover_quality"] = _component("turnover_quality", None, present_invalid=turn_inv)

    # Complexity penalty component
    cx = dict(complexity or {})
    total_cx = int(cx.get("total") or 0)
    if complexity is not None:
        cx_quality = max(0.0, 1.0 - total_cx / 40.0)
        components["complexity_quality"] = _component("complexity_quality", cx_quality)
        if total_cx > 30:
            categories.append(FailureCategory.HIGH_COMPLEXITY.value)
    else:
        components["complexity_quality"] = _component("complexity_quality", None)

    if ret is not None and ret < 0:
        categories.append(FailureCategory.NEGATIVE_RETURN.value)

    # --- Expectancy / payoff structure (Wave 12) ---
    # Win rate alone must NEVER imply profitability.
    expectancy_pack = derive_expectancy_metrics(metrics)
    for key, mv in expectancy_pack.items():
        if key.endswith("_status"):
            continue
        status_key = f"{key}_status"
        st = expectancy_pack.get(status_key, MeasurementStatus.UNMEASURED.value)
        if st == MeasurementStatus.MEASURED.value and mv is not None:
            components[key] = _component(key, float(mv))
        elif st == MeasurementStatus.INVALID.value:
            components[key] = _component(key, None, present_invalid=True)
        else:
            components[key] = _component(key, None)

    net_exp = expectancy_pack.get("net_expectancy")
    win_rate = expectancy_pack.get("win_rate")
    if (
        net_exp is not None
        and expectancy_pack.get("net_expectancy_status") == MeasurementStatus.MEASURED.value
        and float(net_exp) < 0
    ):
        failures.append("net_expectancy_after_costs negative")
        categories.append(FailureCategory.NEGATIVE_RETURN.value)
        # High win-rate with negative expectancy is explicitly not profitable
        if win_rate is not None and float(win_rate) >= 0.6:
            failures.append("high_win_rate_negative_expectancy_trap")

    # Scalar fitness: only from MEASURED weighted components — never invent 0 for UNMEASURED
    weights = dict(objective.fitness_weights or {})
    required = list(required_components or objective.primary_objectives)
    measured_sum = 0.0
    weight_sum = 0.0
    any_invalid = False
    missing_required = False
    for name, weight in weights.items():
        comp = components.get(name)
        if comp is None:
            continue
        if comp.status == MeasurementStatus.INVALID.value:
            any_invalid = True
            continue
        if comp.status != MeasurementStatus.MEASURED.value or comp.value is None:
            if name in required:
                missing_required = True
            continue
        w = float(weight)
        measured_sum += w * float(comp.value)
        weight_sum += w

    scalar: float | None = None
    status = MeasurementStatus.UNMEASURED.value
    if any_invalid:
        status = MeasurementStatus.INVALID.value
        failures.append("INVALID metric component")
    elif weight_sum > 0 and not missing_required:
        scalar = measured_sum / weight_sum
        # Apply configured penalties only when related components measured
        if components.get("turnover_quality") and components["turnover_quality"].status == MeasurementStatus.MEASURED.value:
            scalar -= objective.turnover_penalty * (1.0 - float(components["turnover_quality"].value or 0.0))
        if components.get("execution_cost_quality") and components["execution_cost_quality"].status == MeasurementStatus.MEASURED.value:
            scalar -= objective.cost_penalty * (1.0 - float(components["execution_cost_quality"].value or 0.0))
        if components.get("complexity_quality") and components["complexity_quality"].status == MeasurementStatus.MEASURED.value:
            scalar -= objective.complexity_penalty * (1.0 - float(components["complexity_quality"].value or 0.0))
        status = MeasurementStatus.MEASURED.value
    elif missing_required:
        failures.append("required fitness components UNMEASURED")
        status = MeasurementStatus.UNMEASURED.value

    return FitnessResult(
        candidate_id=candidate_id,
        split_role=str(split_role).upper(),
        components=components,
        scalar_score=scalar,
        measurement_status=status,
        failure_reasons=failures,
        failure_categories=list(dict.fromkeys(categories)),
        metric_refs={
            "trade_count": trades,
            "total_return_pct": ret,
            "max_drawdown_pct": dd,
            "sharpe": sharpe,
            "complexity_total": total_cx if complexity is not None else None,
            "win_rate": expectancy_pack.get("win_rate"),
            "net_expectancy": expectancy_pack.get("net_expectancy"),
            "profit_factor": expectancy_pack.get("profit_factor"),
            "win_loss_payoff_ratio": expectancy_pack.get("win_loss_payoff_ratio"),
            "expectancy_per_trade": expectancy_pack.get("expectancy_per_trade"),
            "cost_drag": expectancy_pack.get("cost_drag"),
        },
    )


def rank_normalize(scores: list[float | None]) -> list[float | None]:
    """Rank-normalize measured scores in [0, 1]; None stays None."""
    indexed = [(i, s) for i, s in enumerate(scores) if s is not None and not (math.isnan(s) or math.isinf(s))]
    if not indexed:
        return list(scores)
    indexed.sort(key=lambda x: x[1])
    n = len(indexed)
    out: list[float | None] = [None] * len(scores)
    for rank, (i, _) in enumerate(indexed):
        out[i] = rank / max(n - 1, 1)
    return out


def parent_deltas(
    child_metrics: dict[str, Any],
    parent_metrics: dict[str, Any] | None,
    *,
    child_complexity: dict[str, int] | None = None,
    parent_complexity: dict[str, int] | None = None,
    child_fitness: float | None = None,
    parent_fitness: float | None = None,
) -> dict[str, float | None]:
    if not parent_metrics:
        return {
            "fitness_delta_vs_parent": None,
            "return_delta_vs_parent": None,
            "drawdown_delta_vs_parent": None,
            "complexity_delta_vs_parent": None,
            "validation_delta_vs_parent": None,
        }

    def _delta(a: float | None, b: float | None) -> float | None:
        if a is None or b is None:
            return None
        return float(a) - float(b)

    return {
        "fitness_delta_vs_parent": _delta(child_fitness, parent_fitness),
        "return_delta_vs_parent": _delta(
            extract_metric(child_metrics, "total_return_pct", "total_return"),
            extract_metric(parent_metrics, "total_return_pct", "total_return"),
        ),
        "drawdown_delta_vs_parent": _delta(
            extract_metric(child_metrics, "max_drawdown_pct"),
            extract_metric(parent_metrics, "max_drawdown_pct"),
        ),
        "complexity_delta_vs_parent": (
            float((child_complexity or {}).get("total", 0) - (parent_complexity or {}).get("total", 0))
            if child_complexity is not None and parent_complexity is not None
            else None
        ),
        "validation_delta_vs_parent": None,
    }
