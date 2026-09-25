"""Deterministic rebalancing recommendations from real portfolio state."""

from __future__ import annotations

import uuid
from typing import Any

from ..paper_broker import utc_now
from .ledger import PortfolioBook


def _now() -> str:
    return utc_now()


def generate_recommendations(
    *,
    portfolio_id: str,
    book: PortfolioBook,
    marks: dict[str, Any],
    settings: dict[str, Any],
    allocations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    eq = float(book.equity(marks))
    if eq <= 0:
        return []
    out: list[dict[str, Any]] = []
    conc_limit = float(settings.get("asset_concentration_pct", settings.get("max_symbol_exposure_pct", 40.0)))
    cash_target = float(settings.get("cash_reserve_pct", 10.0))
    max_lev = float(settings.get("max_leverage", 1.0))

    positions = book.open_positions_public(marks)
    for pos in positions:
        if pos["allocation_pct"] > conc_limit + 0.01:
            reduce_pct = pos["allocation_pct"] - conc_limit
            reduce_qty = float(pos["qty"]) * (reduce_pct / pos["allocation_pct"])
            out.append(
                {
                    "recommendation_id": str(uuid.uuid4()),
                    "portfolio_id": portfolio_id,
                    "type": "REDUCE_CONCENTRATION",
                    "target": pos["symbol"],
                    "reason": (
                        f"{pos['symbol']} concentration {pos['allocation_pct']:.1f}% "
                        f"exceeds target {conc_limit:.1f}%"
                    ),
                    "current_value": f"{pos['allocation_pct']:.2f}%",
                    "target_value": f"{conc_limit:.2f}%",
                    "impact": "HIGH" if pos["allocation_pct"] > conc_limit * 1.2 else "MEDIUM",
                    "estimated_orders": [
                        {
                            "symbol": pos["symbol"],
                            "side": "SELL" if pos["side"] == "LONG" else "COVER",
                            "qty": round(reduce_qty, 8),
                        }
                    ],
                    "status": "PENDING",
                    "created_at": _now(),
                    "metadata": {"position_id": pos["position_id"]},
                }
            )

    cash_pct = float(book.cash) / eq * 100.0
    if cash_pct < cash_target - 0.5:
        out.append(
            {
                "recommendation_id": str(uuid.uuid4()),
                "portfolio_id": portfolio_id,
                "type": "RESTORE_CASH_RESERVE",
                "target": "CASH",
                "reason": f"Cash reserve {cash_pct:.1f}% below target {cash_target:.1f}%",
                "current_value": f"{cash_pct:.2f}%",
                "target_value": f"{cash_target:.2f}%",
                "impact": "HIGH" if cash_pct < cash_target * 0.5 else "MEDIUM",
                "estimated_orders": _sell_to_raise_cash(positions, eq * (cash_target - cash_pct) / 100.0),
                "status": "PENDING",
                "created_at": _now(),
                "metadata": {},
            }
        )

    gross = float(book.gross_exposure(marks))
    lev = gross / eq if eq else 0.0
    if lev > max_lev + 0.01:
        out.append(
            {
                "recommendation_id": str(uuid.uuid4()),
                "portfolio_id": portfolio_id,
                "type": "REDUCE_LEVERAGE",
                "target": "PORTFOLIO",
                "reason": f"Leverage {lev:.2f}x exceeds max {max_lev:.2f}x",
                "current_value": f"{lev:.2f}x",
                "target_value": f"{max_lev:.2f}x",
                "impact": "HIGH",
                "estimated_orders": _trim_largest(positions, fraction=0.25),
                "status": "PENDING",
                "created_at": _now(),
                "metadata": {},
            }
        )

    # Strategy dominance
    by_strat: dict[str, float] = {}
    for pos in positions:
        sid = pos.get("strategy_id") or "unattributed"
        by_strat[sid] = by_strat.get(sid, 0.0) + abs(float(pos["market_value"]))
    for sid, mv in by_strat.items():
        pct = mv / eq * 100.0
        ceiling = float(settings.get("strategy_allocation_ceiling_pct", 40.0))
        if sid != "unattributed" and pct > ceiling + 0.01:
            out.append(
                {
                    "recommendation_id": str(uuid.uuid4()),
                    "portfolio_id": portfolio_id,
                    "type": "REDUCE_STRATEGY_ALLOCATION",
                    "target": sid,
                    "reason": f"Strategy {sid} holds {pct:.1f}% > ceiling {ceiling:.1f}%",
                    "current_value": f"{pct:.2f}%",
                    "target_value": f"{ceiling:.2f}%",
                    "impact": "MEDIUM",
                    "estimated_orders": [],
                    "status": "PENDING",
                    "created_at": _now(),
                    "metadata": {"strategy_id": sid},
                }
            )

    return out[:8]


def _sell_to_raise_cash(positions: list[dict[str, Any]], need: float) -> list[dict[str, Any]]:
    orders: list[dict[str, Any]] = []
    remaining = need
    for pos in sorted(positions, key=lambda p: -p["allocation_pct"]):
        if remaining <= 0:
            break
        if pos["side"] != "LONG":
            continue
        mv = abs(float(pos["market_value"]))
        frac = min(1.0, remaining / mv) if mv > 0 else 0.0
        if frac <= 0:
            continue
        orders.append(
            {
                "symbol": pos["symbol"],
                "side": "SELL",
                "qty": round(float(pos["qty"]) * frac, 8),
            }
        )
        remaining -= mv * frac
    return orders


def _trim_largest(positions: list[dict[str, Any]], *, fraction: float) -> list[dict[str, Any]]:
    if not positions:
        return []
    pos = max(positions, key=lambda p: p["allocation_pct"])
    side = "SELL" if pos["side"] == "LONG" else "COVER"
    return [
        {
            "symbol": pos["symbol"],
            "side": side,
            "qty": round(float(pos["qty"]) * fraction, 8),
        }
    ]


def preview_rebalance(
    *,
    book: PortfolioBook,
    marks: dict[str, Any],
    orders: list[dict[str, Any]],
    fee_bps: float,
    slippage_bps: float,
) -> dict[str, Any]:
    """Non-mutating preview of proposed paper orders."""
    from copy import deepcopy

    # Simulate on a cloned book
    clone = PortfolioBook.deserialize(book.serialize())
    estimated: list[dict[str, Any]] = []
    for o in orders:
        sym = str(o["symbol"]).upper()
        side = str(o["side"]).upper()
        qty = float(o["qty"])
        px = float(marks.get(sym) or 0)
        if px <= 0 or qty <= 0:
            estimated.append({**o, "status": "skipped", "reason": "missing mark or qty"})
            continue
        slip = px * (slippage_bps / 10_000.0)
        fill_px = px + slip if side in ("BUY", "COVER") else px - slip
        fee = abs(qty * fill_px) * (fee_bps / 10_000.0)
        try:
            effect = clone.apply_fill(
                symbol=sym,
                side=side,
                qty=qty,
                price=fill_px,
                fee=fee,
                tx_id=f"preview-{uuid.uuid4()}",
            )
            estimated.append({**o, "fill_price": fill_px, "fee": fee, "status": "ok", "result": effect["result"]})
        except Exception as exc:  # noqa: BLE001
            estimated.append({**o, "status": "failed", "reason": str(exc)})

    before = {
        "equity": str(book.equity(marks)),
        "cash": str(book.cash),
        "allocation": [
            {"symbol": p["symbol"], "allocation_pct": p["allocation_pct"]}
            for p in book.open_positions_public(marks)
        ],
    }
    after_marks = dict(marks)
    after = {
        "equity": str(clone.equity(after_marks)),
        "cash": str(clone.cash),
        "allocation": [
            {"symbol": p["symbol"], "allocation_pct": p["allocation_pct"]}
            for p in clone.open_positions_public(after_marks)
        ],
    }
    return {
        "orders": estimated,
        "before": before,
        "after": after,
        "truth": {"preview_only": True, "no_state_mutation": True, "paper_only": True},
    }
