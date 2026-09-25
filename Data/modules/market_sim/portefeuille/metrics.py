"""Performance / risk metrics for Paper Portefeuille — no fake values."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from ..accounting import D, ZERO, money
from .assets import asset_registry
from .ledger import PortfolioBook


MIN_OBS_SHARPE = 10
MIN_OBS_VOL = 5
MIN_OBS_BETA = 20
RISK_FREE_ANNUAL = 0.02


def _returns(equities: list[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(equities)):
        prev = equities[i - 1]
        if prev <= 0:
            continue
        out.append((equities[i] - prev) / prev)
    return out


def total_return(current_equity: float, baseline_equity: float) -> float | None:
    if baseline_equity <= 0:
        return None
    return (current_equity / baseline_equity) - 1.0


def max_drawdown(equities: list[float]) -> float | None:
    if len(equities) < 2:
        return None
    peak = equities[0]
    max_dd = 0.0
    for e in equities:
        peak = max(peak, e)
        if peak > 0:
            max_dd = max(max_dd, (peak - e) / peak)
    return -max_dd  # negative convention matching SCREEN 1


def volatility(returns: list[float], *, periods_per_year: float = 252.0) -> float | None:
    if len(returns) < MIN_OBS_VOL:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / max(1, len(returns) - 1)
    return math.sqrt(var) * math.sqrt(periods_per_year)


def sharpe(returns: list[float], *, periods_per_year: float = 252.0) -> float | None:
    if len(returns) < MIN_OBS_SHARPE:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / max(1, len(returns) - 1)
    std = math.sqrt(var)
    if std <= 0:
        return None
    rf_period = RISK_FREE_ANNUAL / periods_per_year
    return ((mean - rf_period) / std) * math.sqrt(periods_per_year)


def sortino(returns: list[float], *, periods_per_year: float = 252.0) -> float | None:
    if len(returns) < MIN_OBS_SHARPE:
        return None
    mean = sum(returns) / len(returns)
    downside = [r for r in returns if r < 0]
    if len(downside) < 3:
        return None
    dvar = sum(r ** 2 for r in downside) / len(downside)
    dstd = math.sqrt(dvar)
    if dstd <= 0:
        return None
    rf_period = RISK_FREE_ANNUAL / periods_per_year
    return ((mean - rf_period) / dstd) * math.sqrt(periods_per_year)


def beta(port_returns: list[float], bench_returns: list[float]) -> float | None:
    n = min(len(port_returns), len(bench_returns))
    if n < MIN_OBS_BETA:
        return None
    pr = port_returns[-n:]
    br = bench_returns[-n:]
    mean_p = sum(pr) / n
    mean_b = sum(br) / n
    cov = sum((pr[i] - mean_p) * (br[i] - mean_b) for i in range(n)) / max(1, n - 1)
    var_b = sum((br[i] - mean_b) ** 2 for i in range(n)) / max(1, n - 1)
    if var_b <= 0:
        return None
    return cov / var_b


def correlation(port_returns: list[float], bench_returns: list[float]) -> float | None:
    n = min(len(port_returns), len(bench_returns))
    if n < MIN_OBS_BETA:
        return None
    pr = port_returns[-n:]
    br = bench_returns[-n:]
    mean_p = sum(pr) / n
    mean_b = sum(br) / n
    cov = sum((pr[i] - mean_p) * (br[i] - mean_b) for i in range(n)) / max(1, n - 1)
    std_p = math.sqrt(sum((x - mean_p) ** 2 for x in pr) / max(1, n - 1))
    std_b = math.sqrt(sum((x - mean_b) ** 2 for x in br) / max(1, n - 1))
    if std_p <= 0 or std_b <= 0:
        return None
    return cov / (std_p * std_b)


def historical_var(returns: list[float], *, confidence: float = 0.95) -> float | None:
    """Historical 1-period VaR. Returns negative loss fraction or None if insufficient."""
    if len(returns) < MIN_OBS_SHARPE:
        return None
    ordered = sorted(returns)
    idx = max(0, int(math.floor((1.0 - confidence) * len(ordered))) - 1)
    return ordered[idx]


def health_score(
    *,
    drawdown_pct: float,
    max_drawdown_limit_pct: float,
    leverage: float,
    max_leverage: float,
    largest_position_pct: float,
    concentration_limit_pct: float,
    cash_reserve_pct: float,
    cash_reserve_target_pct: float,
    risk_limit_utilization: float,
) -> dict[str, Any]:
    """Deterministic 0–100 health score with explainable components. Not a prediction."""
    components: dict[str, float] = {}

    dd_util = min(1.0, drawdown_pct / max_drawdown_limit_pct) if max_drawdown_limit_pct > 0 else 0.0
    components["drawdown"] = max(0.0, 1.0 - dd_util) * 25.0

    lev_util = min(1.0, leverage / max_leverage) if max_leverage > 0 else 0.0
    components["leverage"] = max(0.0, 1.0 - lev_util) * 20.0

    conc_util = (
        min(1.0, largest_position_pct / concentration_limit_pct) if concentration_limit_pct > 0 else 0.0
    )
    components["concentration"] = max(0.0, 1.0 - conc_util) * 20.0

    cash_ratio = (
        min(1.0, cash_reserve_pct / cash_reserve_target_pct) if cash_reserve_target_pct > 0 else 1.0
    )
    components["cash_reserve"] = cash_ratio * 15.0

    components["risk_headroom"] = max(0.0, 1.0 - min(1.0, risk_limit_utilization)) * 20.0

    score = sum(components.values())
    label = "GOOD" if score >= 70 else ("FAIR" if score >= 45 else "POOR")
    return {
        "score": round(score),
        "label": label,
        "components": {k: round(v, 1) for k, v in components.items()},
        "truth": {"deterministic": True, "not_scientific_prediction": True},
    }


def stress_level(
    *,
    drawdown_pct: float,
    leverage: float,
    largest_position_pct: float,
    vol: float | None,
    risk_util: float,
) -> str:
    """LOW | MEDIUM | HIGH — explicit deterministic classification."""
    score = 0
    if drawdown_pct >= 15:
        score += 2
    elif drawdown_pct >= 8:
        score += 1
    if leverage >= 1.5:
        score += 2
    elif leverage >= 1.1:
        score += 1
    if largest_position_pct >= 40:
        score += 2
    elif largest_position_pct >= 25:
        score += 1
    if vol is not None and vol >= 0.4:
        score += 1
    if risk_util >= 0.85:
        score += 2
    elif risk_util >= 0.6:
        score += 1
    if score >= 5:
        return "HIGH"
    if score >= 3:
        return "MEDIUM"
    return "LOW"


def allocation_breakdown(book: PortfolioBook, marks: dict[str, Any]) -> dict[str, Any]:
    eq = book.equity(marks)
    cash = float(book.cash)
    rows: list[dict[str, Any]] = []
    by_class: dict[str, float] = {}

    if cash > 0 and eq > ZERO:
        rows.append(
            {
                "symbol": "CASH",
                "display_name": "Cash",
                "asset_class": "cash",
                "value": str(money(cash)),
                "allocation_pct": round(cash / float(eq) * 100, 2) if eq > ZERO else 0.0,
                "pnl_24h": "0",
            }
        )
        by_class["cash"] = by_class.get("cash", 0.0) + cash

    for pos in book.open_positions_public(marks, equity=eq):
        mv = abs(float(pos["market_value"]))
        ac = pos["asset_class"]
        by_class[ac] = by_class.get(ac, 0.0) + mv
        rows.append(
            {
                "symbol": pos["symbol"],
                "display_name": pos["display_name"],
                "asset_class": ac,
                "value": str(money(mv)),
                "allocation_pct": pos["allocation_pct"],
                "pnl_24h": pos["unrealized_pnl"],
                "sector": asset_registry.get(pos["symbol"]).sector,
                "geography": asset_registry.get(pos["symbol"]).geography,
            }
        )

    eq_f = float(eq) if eq > ZERO else 1.0
    class_rows = [
        {"asset_class": k, "value": str(money(v)), "allocation_pct": round(v / eq_f * 100, 2)}
        for k, v in sorted(by_class.items(), key=lambda x: -x[1])
    ]
    return {
        "total_equity": str(eq),
        "assets": rows,
        "by_asset_class": class_rows,
        "by_sector": _group_meta(rows, "sector", eq_f),
        "by_geography": _group_meta(rows, "geography", eq_f),
    }


def _group_meta(rows: list[dict[str, Any]], key: str, eq_f: float) -> list[dict[str, Any]]:
    buckets: dict[str, float] = {}
    known = False
    for r in rows:
        val = r.get(key)
        if val:
            known = True
            buckets[str(val)] = buckets.get(str(val), 0.0) + float(r.get("value") or 0)
    if not known:
        return []
    return [
        {"name": k, "value": str(money(v)), "allocation_pct": round(v / eq_f * 100, 2)}
        for k, v in sorted(buckets.items(), key=lambda x: -x[1])
    ]


def exposure_summary(book: PortfolioBook, marks: dict[str, Any]) -> dict[str, Any]:
    eq = book.equity(marks)
    gross = book.gross_exposure(marks)
    net = book.net_exposure(marks)
    eq_f = float(eq) if eq > ZERO else 0.0
    leverage = float(gross) / eq_f if eq_f > 0 else 0.0
    positions = book.open_positions_public(marks, equity=eq)
    largest = max((p["allocation_pct"] for p in positions), default=0.0)
    top3 = sorted(positions, key=lambda p: -p["allocation_pct"])[:3]
    alloc = allocation_breakdown(book, marks)
    by_class = {r["asset_class"]: r["allocation_pct"] for r in alloc["by_asset_class"]}
    return {
        "net_exposure_pct": round(float(net) / eq_f * 100, 2) if eq_f else 0.0,
        "gross_exposure_pct": round(float(gross) / eq_f * 100, 2) if eq_f else 0.0,
        "leverage": round(leverage, 2),
        "largest_position_pct": largest,
        "top3_concentration": [
            {"symbol": p["symbol"], "allocation_pct": p["allocation_pct"]} for p in top3
        ],
        "crypto_allocation_pct": by_class.get("crypto", 0.0),
        "equities_allocation_pct": by_class.get("equity", 0.0),
        "stablecoin_cash_allocation_pct": round(
            by_class.get("stablecoin", 0.0) + by_class.get("cash", 0.0), 2
        ),
        "other_allocation_pct": by_class.get("other", 0.0),
        "margin_used": str(book.margin_used(marks)),
    }


def performance_from_snapshots(
    snapshots: list[dict[str, Any]],
    *,
    baseline_equity: float,
    benchmark_series: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    equities = [float(s.get("equity") or 0) for s in snapshots]
    returns = _returns(equities)
    tr = total_return(equities[-1], baseline_equity) if equities else None
    mdd = max_drawdown(equities)
    vol = volatility(returns)
    sh = sharpe(returns)
    so = sortino(returns)
    bench_returns: list[float] = []
    if benchmark_series and len(benchmark_series) >= 2:
        be = [float(p.get("value") or p.get("equity") or 0) for p in benchmark_series]
        bench_returns = _returns(be)
    bt = beta(returns, bench_returns) if bench_returns else None
    corr = correlation(returns, bench_returns) if bench_returns else None
    var = historical_var(returns)
    return {
        "total_return": None if tr is None else round(tr * 100, 2),
        "max_drawdown": None if mdd is None else round(mdd * 100, 2),
        "volatility": None if vol is None else round(vol * 100, 2),
        "sharpe": None if sh is None else round(sh, 2),
        "sortino": None if so is None else round(so, 2),
        "beta": None if bt is None else round(bt, 2),
        "correlation": None if corr is None else round(corr, 2),
        "var_1d_95": None if var is None else round(var * 100, 2),
        "observations": len(returns),
        "insufficient": {
            "volatility": vol is None,
            "sharpe": sh is None,
            "sortino": so is None,
            "beta": bt is None,
            "var": var is None,
        },
        "series": [
            {"timestamp": s.get("timestamp"), "equity": s.get("equity"), "drawdown": s.get("drawdown")}
            for s in snapshots
        ],
    }


def downsample_snapshots(
    snapshots: list[dict[str, Any]], *, range_key: str
) -> list[dict[str, Any]]:
    """Bound series size by range. range_key: 1D|1W|1M|3M|YTD|1Y|ALL."""
    if not snapshots:
        return []
    now = datetime.now(timezone.utc)
    cut_days = {
        "1D": 1,
        "1W": 7,
        "1M": 30,
        "3M": 90,
        "YTD": max(1, now.timetuple().tm_yday),
        "1Y": 365,
        "ALL": 10_000,
    }.get(range_key.upper(), 30)
    filtered: list[dict[str, Any]] = []
    for s in snapshots:
        ts = str(s.get("timestamp") or "")
        try:
            raw = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age = (now - dt.astimezone(timezone.utc)).total_seconds() / 86400.0
            if age <= cut_days:
                filtered.append(s)
        except ValueError:
            filtered.append(s)
    if not filtered:
        filtered = snapshots[-min(len(snapshots), 50) :]
    max_points = {
        "1D": 96,
        "1W": 168,
        "1M": 180,
        "3M": 200,
        "YTD": 250,
        "1Y": 250,
        "ALL": 300,
    }.get(range_key.upper(), 200)
    if len(filtered) <= max_points:
        return filtered
    step = max(1, len(filtered) // max_points)
    out = filtered[::step]
    if out[-1] is not filtered[-1]:
        out.append(filtered[-1])
    return out[:max_points]
