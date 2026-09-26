"""Deterministic AI Portefeuille Intelligence observations from real state."""

from __future__ import annotations

from typing import Any

from .ledger import PortfolioBook


def generate_insights(
    *,
    book: PortfolioBook,
    marks: dict[str, Any],
    settings: dict[str, Any],
    health: dict[str, Any],
    exposure: dict[str, Any],
    performance: dict[str, Any],
) -> list[dict[str, Any]]:
    insights: list[dict[str, Any]] = []
    eq = float(book.equity(marks))
    score = health.get("score")
    label = health.get("label")
    if score is not None:
        insights.append(
            {
                "id": "health",
                "severity": f"Portefeuille risk is {'within target' if score >= 70 else 'elevated'} ({score}/100 — {label}).",
                "severity": "info" if score >= 70 else "warn",
            }
        )

    conc = float(settings.get("asset_concentration_pct", 40.0))
    for pos in book.open_positions_public(marks):
        if pos["allocation_pct"] > conc:
            insights.append(
                {
                    "id": f"conc-{pos['symbol']}",
                    "severity": (
                        f"Consider reducing {pos['symbol']} concentration "
                        f"({pos['allocation_pct']:.1f}% > {conc:.1f}% target)."
                    ),
                    "severity": "warn",
                }
            )
            break

    cash_tgt = float(settings.get("cash_reserve_pct", 10.0))
    if eq > 0:
        cash_pct = float(book.cash) / eq * 100.0
        if cash_pct < cash_tgt:
            insights.append(
                {
                    "id": "cash",
                    "severity": f"Cash reserve {cash_pct:.1f}% is below configured threshold {cash_tgt:.1f}%.",
                    "severity": "warn",
                }
            )
        else:
            insights.append(
                {
                    "id": "cash-ok",
                    "severity": f"Cash reserve healthy at {cash_pct:.1f}% (target {cash_tgt:.1f}%).",
                    "severity": "info",
                }
            )

    positions = book.open_positions_public(marks)
    if positions:
        best = max(positions, key=lambda p: float(p["unrealized_pnl"]))
        if float(best["unrealized_pnl"]) > 0:
            insights.append(
                {
                    "id": "contrib",
                    "severity": (
                        f"{best['symbol']} has the highest unrealized contribution "
                        f"({best['unrealized_pnl']} / {best['pnl_pct']}%)."
                    ),
                    "severity": "info",
                }
            )

    by_strat: dict[str, float] = {}
    for pos in positions:
        sid = pos.get("strategy_id") or "unattributed"
        by_strat[sid] = by_strat.get(sid, 0.0) + abs(float(pos["market_value"]))
    if by_strat and eq > 0:
        top_s, top_v = max(by_strat.items(), key=lambda x: x[1])
        if top_s != "unattributed" and top_v / eq > 0.4:
            insights.append(
                {
                    "id": "strat-dom",
                    "severity": f"Strategy {top_s} dominates current risk ({top_v / eq * 100:.1f}% of equity).",
                    "severity": "warn",
                }
            )

    corr = performance.get("correlation")
    if corr is not None and abs(float(corr)) >= 0.8:
        insights.append(
            {
                "id": "corr",
                "severity": f"Correlation vs benchmark unusually high ({float(corr):.2f}).",
                "severity": "warn",
            }
        )

    dd_limit = float(settings.get("max_drawdown_pct", 20.0))
    dd = book.drawdown_pct(marks)
    if dd >= dd_limit * 0.75:
        insights.append(
            {
                "id": "dd",
                "severity": f"Drawdown {dd:.1f}% approaching limit {dd_limit:.1f}%.",
                "severity": "warn",
            }
        )

    if not any(i["severity"] == "warn" for i in insights):
        insights.append(
            {
                "id": "clear",
                "severity": "No immediate risk flags detected.",
                "severity": "info",
            }
        )

    return insights[:6]


def institutional_exposure_intelligence(
    *,
    book: PortfolioBook,
    marks: dict[str, Any],
    settings: dict[str, Any],
    allocations: dict[str, float] | None = None,
) -> dict[str, Any]:
    """W16 — structured exposure / allocation / constraint utilization facts."""
    eq = float(book.equity(marks))
    positions = book.open_positions_public(marks)
    by_symbol = {
        p["symbol"]: {
            "marketValue": float(p["market_value"]),
            "allocationPct": float(p["allocation_pct"]),
            "strategyId": p.get("strategy_id"),
        }
        for p in positions
    }
    by_strategy: dict[str, float] = {}
    for p in positions:
        sid = str(p.get("strategy_id") or "unattributed")
        by_strategy[sid] = by_strategy.get(sid, 0.0) + abs(float(p["market_value"]))
    targets = dict(allocations or {})
    drifts: list[dict[str, Any]] = []
    for sym, tgt in targets.items():
        actual = by_symbol.get(sym, {}).get("allocationPct", 0.0)
        drifts.append(
            {
                "symbol": sym,
                "targetPct": float(tgt),
                "actualPct": float(actual),
                "driftPct": float(actual) - float(tgt),
                "status": "MEASURED",
            }
        )
    conc_limit = float(settings.get("asset_concentration_pct", 40.0))
    cash_tgt = float(settings.get("cash_reserve_pct", 10.0))
    dd_limit = float(settings.get("max_drawdown_pct", 20.0))
    cash_pct = (float(book.cash) / eq * 100.0) if eq > 0 else 0.0
    dd = float(book.drawdown_pct(marks))
    max_alloc = max((float(p["allocation_pct"]) for p in positions), default=0.0)
    constraints = {
        "concentration": {
            "limitPct": conc_limit,
            "utilizationPct": max_alloc,
            "breached": max_alloc > conc_limit,
            "status": "MEASURED",
        },
        "cashReserve": {
            "targetPct": cash_tgt,
            "actualPct": cash_pct,
            "breached": cash_pct < cash_tgt,
            "status": "MEASURED",
        },
        "drawdown": {
            "limitPct": dd_limit,
            "actualPct": dd,
            "utilizationPct": (dd / dd_limit * 100.0) if dd_limit else 0.0,
            "breached": dd >= dd_limit,
            "status": "MEASURED",
        },
    }
    return {
        "equity": eq,
        "bySymbol": by_symbol,
        "byStrategy": {k: {"marketValue": v, "pctEquity": (v / eq * 100.0) if eq else 0.0} for k, v in by_strategy.items()},
        "allocationDrifts": drifts,
        "constraints": constraints,
        "truth": {
            "from_real_portfolio_book": True,
            "no_factor_risk_engine": True,
            "heuristic_insights_are_separate": True,
        },
    }
