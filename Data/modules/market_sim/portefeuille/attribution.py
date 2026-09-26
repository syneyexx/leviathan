"""Performance / return attribution (W19) — portefeuille owner."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def attribute_contributions(
    *,
    positions: Sequence[Mapping[str, Any]],
    total_pnl: float | None = None,
) -> dict[str, Any]:
    """Sum unrealized/realized contribution by symbol and strategy.

    Does not claim Brinson/factor attribution — labelled contribution only.
    """
    by_symbol: dict[str, float] = {}
    by_strategy: dict[str, float] = {}
    for pos in positions:
        sym = str(pos.get("symbol") or "?")
        sid = str(pos.get("strategy_id") or pos.get("strategyId") or "unattributed")
        pnl = float(
            pos.get("unrealized_pnl")
            if pos.get("unrealized_pnl") is not None
            else pos.get("realized_pnl") or 0.0
        )
        by_symbol[sym] = by_symbol.get(sym, 0.0) + pnl
        by_strategy[sid] = by_strategy.get(sid, 0.0) + pnl
    summed = sum(by_symbol.values())
    residual = None if total_pnl is None else float(total_pnl) - summed
    return {
        "bySymbol": by_symbol,
        "byStrategy": by_strategy,
        "sumContributions": summed,
        "totalPnl": total_pnl,
        "residual": residual,
        "method": "position_contribution",
        "truth": {
            "not_brinson_factor_attribution": True,
            "contributions_sum_to_total_when_residual_near_zero": residual is None
            or abs(residual) < 1e-6,
        },
    }
