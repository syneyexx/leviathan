"""Honest performance metrics — unmeasured stays UNMEASURED.

T5: timeframe-aware annualization, ledger-derived win/profit factor,
and bootstrap confidence intervals (G18).
"""

from __future__ import annotations

import math
import random
from typing import Any, Sequence

from .types import MetricStatus

# Bars (return observations) per calendar/trading year by timeframe.
# Daily equity uses 252 trading sessions; intraday crypto uses 24/7 calendar.
_PERIODS_PER_YEAR: dict[str, float] = {
    "1m": 365.25 * 24 * 60,
    "5m": 365.25 * 24 * 12,
    "15m": 365.25 * 24 * 4,
    "1h": 365.25 * 24,
    "4h": 365.25 * 6,
    "1D": 252.0,
    "1d": 252.0,
}


def periods_per_year_for_timeframe(timeframe: str | None, *, default: float = 252.0) -> float:
    """Map a bar timeframe to Sharpe/Sortino annualization periods."""
    if not timeframe:
        return float(default)
    key = str(timeframe).strip()
    if key in _PERIODS_PER_YEAR:
        return float(_PERIODS_PER_YEAR[key])
    # Accept aliases like "60m" / "H1"
    aliases = {"60m": "1h", "H1": "1h", "H4": "4h", "D": "1D", "1day": "1D"}
    mapped = aliases.get(key)
    if mapped and mapped in _PERIODS_PER_YEAR:
        return float(_PERIODS_PER_YEAR[mapped])
    return float(default)


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


def bootstrap_metric_cis(
    returns: Sequence[float],
    *,
    periods_per_year: float = 252.0,
    n_boot: int = 500,
    alpha: float = 0.05,
    seed: int = 42,
) -> dict[str, Any]:
    """Resample returns to estimate CIs for Sharpe and mean return (G18)."""
    n = len(returns)
    if n < 5:
        return {
            "status": MetricStatus.UNMEASURED.value,
            "value": None,
            "reason": "insufficient returns for bootstrap",
            "n": n,
        }
    rng = random.Random(seed)
    sharpes: list[float] = []
    means: list[float] = []
    rets = list(returns)
    for _ in range(max(50, int(n_boot))):
        sample = [rets[rng.randrange(n)] for _ in range(n)]
        mean = sum(sample) / n
        var = sum((r - mean) ** 2 for r in sample) / (n - 1)
        std = math.sqrt(var) if var > 0 else 0.0
        means.append(mean)
        if std > 0:
            sharpes.append((mean / std) * math.sqrt(periods_per_year))

    def _ci(values: list[float]) -> dict[str, Any]:
        if len(values) < 10:
            return {
                "status": MetricStatus.UNMEASURED.value,
                "value": None,
                "reason": "bootstrap samples collapsed",
            }
        ordered = sorted(values)
        lo_i = int(len(ordered) * (alpha / 2.0))
        hi_i = int(len(ordered) * (1.0 - alpha / 2.0))
        hi_i = min(len(ordered) - 1, max(lo_i + 1, hi_i))
        mid = ordered[len(ordered) // 2]
        return {
            "status": MetricStatus.MEASURED.value,
            "value": mid,
            "ci_low": ordered[lo_i],
            "ci_high": ordered[hi_i],
            "alpha": alpha,
            "n_boot": len(ordered),
        }

    return {
        "status": MetricStatus.MEASURED.value,
        "sharpe": _ci(sharpes),
        "mean_return": _ci(means),
        "periods_per_year": periods_per_year,
        "truth": {"resampled_returns": True, "not_parametric": True},
    }


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
    timeframe: str | None = None,
    bootstrap: bool = True,
    bootstrap_n: int = 500,
    bootstrap_seed: int = 42,
) -> dict[str, Any]:
    if timeframe is not None:
        periods_per_year = periods_per_year_for_timeframe(timeframe, default=periods_per_year)

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

    # Ledger-derived closed-trade PnL when fills carry realized_delta (G18 / D2).
    realized = [float(f["realized_delta"]) for f in fills if "realized_delta" in f and f["realized_delta"] is not None]
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
    excess_return: dict[str, Any] = {
        "status": MetricStatus.UNMEASURED.value,
        "value": None,
        "reason": "benchmark equity not provided",
    }
    if benchmark_equity and len(benchmark_equity) >= 2 and benchmark_equity[0] > 0:
        bh = (benchmark_equity[-1] / benchmark_equity[0]) - 1.0
        buy_hold = {
            "status": MetricStatus.MEASURED.value,
            "value": bh,
        }
        if total_return is not None:
            excess_return = {
                "status": MetricStatus.MEASURED.value,
                "value": total_return - bh,
            }

    brain_total = brain_hits + brain_misses
    brain_hit_rate = {
        "status": MetricStatus.MEASURED.value if brain_total else MetricStatus.UNMEASURED.value,
        "value": (brain_hits / brain_total) if brain_total else None,
        "hits": brain_hits,
        "misses": brain_misses,
    }

    trade_count = len([f for f in fills if str(f.get("side") or "").upper() in {"BUY", "SELL"}])

    out: dict[str, Any] = {
        "total_return": {"status": total_return_status, "value": total_return},
        "sharpe": _safe_sharpe(returns, periods_per_year=periods_per_year),
        "sortino": _safe_sortino(returns, periods_per_year=periods_per_year),
        "max_drawdown": max_drawdown(equity),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "turnover": {"status": MetricStatus.MEASURED.value, "value": turnover},
        "fees_paid": {"status": MetricStatus.MEASURED.value, "value": fees_paid},
        "trade_count": {"status": MetricStatus.MEASURED.value, "value": trade_count},
        "buy_and_hold_return": buy_hold,
        "excess_return": excess_return,
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
        "annualization": {
            "periods_per_year": periods_per_year,
            "timeframe": timeframe,
        },
        "truth": {
            "unmeasured_stays_unmeasured": True,
            "no_fabricated_metrics": True,
            "ledger_derived_win_rate": bool(realized),
        },
    }
    if bootstrap:
        out["bootstrap"] = bootstrap_metric_cis(
            returns,
            periods_per_year=periods_per_year,
            n_boot=bootstrap_n,
            seed=bootstrap_seed,
        )
    return out
