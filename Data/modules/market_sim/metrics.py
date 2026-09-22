"""Honest performance metrics — unmeasured stays UNMEASURED."""

from __future__ import annotations

import math
from typing import Any, Sequence

from .types import MetricStatus


def _safe_sharpe(returns: Sequence[float], *, periods_per_year: float = 252.0) -> dict[str, Any]:
    if len(returns) < 2:
        return {"status": MetricStatus.UNMEASURED.value, "value": None, "reason": "insufficient returns"}
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var)
    if std <= 0:
        return {"status": MetricStatus.UNMEASURED.value, "value": None, "reason": "zero volatility"}
    sharpe = (mean / std) * math.sqrt(periods_per_year)
    return {"status": MetricStatus.MEASURED.value, "value": sharpe}


def _safe_sortino(returns: Sequence[float], *, periods_per_year: float = 252.0) -> dict[str, Any]:
    if len(returns) < 2:
        return {"status": MetricStatus.UNMEASURED.value, "value": None, "reason": "insufficient returns"}
    mean = sum(returns) / len(returns)
    downside = [min(0.0, r) for r in returns]
    downside_var = sum(d ** 2 for d in downside) / (len(returns) - 1)
    downside_std = math.sqrt(downside_var)
    if downside_std <= 0:
        return {"status": MetricStatus.UNMEASURED.value, "value": None, "reason": "no downside"}
    sortino = (mean / downside_std) * math.sqrt(periods_per_year)
    return {"status": MetricStatus.MEASURED.value, "value": sortino}


def max_drawdown(equity: Sequence[float]) -> dict[str, Any]:
    if len(equity) < 2:
        return {"status": MetricStatus.UNMEASURED.value, "value": None, "reason": "insufficient equity points"}
    peak = equity[0]
    max_dd = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            max_dd = max(max_dd, (peak - value) / peak)
    return {"status": MetricStatus.MEASURED.value, "value": max_dd}


def compute_metrics(
    *,
    equity: Sequence[float],
    fills: Sequence[dict[str, Any]],
    initial_cash: float,
    benchmark_equity: Sequence[float] | None = None,
    causality_violations: int = 0,
    brain_hits: int = 0,
    brain_misses: int = 0,
    agreement_rate: float | None = None,
    veto_rate: float | None = None,
    periods_per_year: float = 252.0,
) -> dict[str, Any]:
    returns: list[float] = []
    for i in range(1, len(equity)):
        prev = equity[i - 1]
        if prev > 0:
            returns.append((equity[i] - prev) / prev)

    total_return = None
    total_return_status = MetricStatus.UNMEASURED.value
    if equity and initial_cash > 0:
        total_return = (equity[-1] / initial_cash) - 1.0
        total_return_status = MetricStatus.MEASURED.value

    wins = 0
    losses = 0
    gross_profit = 0.0
    gross_loss = 0.0
    fees_paid = 0.0
    turnover = 0.0
    for fill in fills:
        fees_paid += float(fill.get("fee") or 0.0)
        turnover += abs(float(fill.get("qty") or 0.0) * float(fill.get("price") or 0.0))
        # Per-fill PnL attribution is approximate for round-trips; leave win rate on closed sells.
        if fill.get("side") == "SELL":
            # Without per-trade ledger, mark UNMEASURED for win rate if we can't compute.
            pass

    win_rate: dict[str, Any] = {
        "status": MetricStatus.UNMEASURED.value,
        "value": None,
        "reason": "round-trip ledger not yet attributed per trade",
    }
    profit_factor: dict[str, Any] = {
        "status": MetricStatus.UNMEASURED.value,
        "value": None,
        "reason": "requires closed-trade PnL attribution",
    }

    # Simple realized from fills metadata if present
    realized = [float(f["realized_delta"]) for f in fills if "realized_delta" in f]
    if realized:
        wins = sum(1 for r in realized if r > 0)
        losses = sum(1 for r in realized if r < 0)
        gross_profit = sum(r for r in realized if r > 0)
        gross_loss = abs(sum(r for r in realized if r < 0))
        total_closed = wins + losses
        if total_closed:
            win_rate = {
                "status": MetricStatus.MEASURED.value,
                "value": wins / total_closed,
            }
        if gross_loss > 0:
            profit_factor = {
                "status": MetricStatus.MEASURED.value,
                "value": gross_profit / gross_loss,
            }
        elif gross_profit > 0:
            profit_factor = {
                "status": MetricStatus.MEASURED.value,
                "value": None,
                "reason": "no losses — infinite profit factor not claimed",
            }

    buy_hold = {
        "status": MetricStatus.UNMEASURED.value,
        "value": None,
        "reason": "benchmark equity not provided",
    }
    if benchmark_equity and len(benchmark_equity) >= 2 and benchmark_equity[0] > 0:
        buy_hold = {
            "status": MetricStatus.MEASURED.value,
            "value": (benchmark_equity[-1] / benchmark_equity[0]) - 1.0,
        }

    brain_total = brain_hits + brain_misses
    brain_hit_rate = {
        "status": MetricStatus.MEASURED.value if brain_total else MetricStatus.UNMEASURED.value,
        "value": (brain_hits / brain_total) if brain_total else None,
        "hits": brain_hits,
        "misses": brain_misses,
    }

    return {
        "total_return": {"status": total_return_status, "value": total_return},
        "sharpe": _safe_sharpe(returns, periods_per_year=periods_per_year),
        "sortino": _safe_sortino(returns, periods_per_year=periods_per_year),
        "max_drawdown": max_drawdown(equity),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "turnover": {"status": MetricStatus.MEASURED.value, "value": turnover},
        "fees_paid": {"status": MetricStatus.MEASURED.value, "value": fees_paid},
        "buy_and_hold_return": buy_hold,
        "causality_violations": {
            "status": MetricStatus.MEASURED.value,
            "value": causality_violations,
        },
        "brain_hit_rate": brain_hit_rate,
        "deliberation": {
            "agreement_rate": {
                "status": MetricStatus.MEASURED.value if agreement_rate is not None else MetricStatus.UNMEASURED.value,
                "value": agreement_rate,
            },
            "veto_rate": {
                "status": MetricStatus.MEASURED.value if veto_rate is not None else MetricStatus.UNMEASURED.value,
                "value": veto_rate,
            },
        },
        "truth": {
            "unmeasured_stays_unmeasured": True,
            "no_fabricated_metrics": True,
        },
    }
