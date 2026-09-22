"""Honest fill model — fees + slippage; no fabricated success."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from .portfolio import Portfolio


@dataclass(frozen=True)
class FillResult:
    filled: bool
    qty: float
    price: float
    fee: float
    slippage: float
    detail: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "filled": self.filled,
            "qty": self.qty,
            "price": self.price,
            "fee": self.fee,
            "slippage": self.slippage,
            "detail": self.detail,
        }


class FillModel:
    """Conservative bar fill: market orders fill at close ± slippage.

    When order-book data is absent, we do not claim partial L2 realism.
    """

    def __init__(
        self,
        *,
        fee_bps: float = 5.0,
        slippage_bps: float = 2.0,
        seed: int = 0,
        stochastic: bool = False,
    ) -> None:
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self.rng = random.Random(seed)
        self.stochastic = stochastic

    def execute(
        self,
        *,
        portfolio: Portfolio,
        side: str,
        qty: float,
        bar_close: float,
        bar_volume: float,
    ) -> FillResult:
        if side == "HOLD" or qty <= 0:
            return FillResult(False, 0.0, bar_close, 0.0, 0.0, "no trade")
        if bar_close <= 0:
            return FillResult(False, 0.0, 0.0, 0.0, 0.0, "invalid bar close")

        slip_bps = self.slippage_bps
        if self.stochastic:
            slip_bps = abs(self.rng.gauss(self.slippage_bps, self.slippage_bps * 0.25))
        # Volume-aware: larger fraction of bar volume → more slippage
        if bar_volume > 0:
            participation = min(1.0, qty / max(bar_volume, 1e-9))
            slip_bps += participation * self.slippage_bps * 2.0

        slip_frac = slip_bps / 10_000.0
        if side == "BUY":
            fill_price = bar_close * (1.0 + slip_frac)
        else:
            fill_price = bar_close * (1.0 - slip_frac)

        notional = qty * fill_price
        fee = notional * (self.fee_bps / 10_000.0)
        slippage_cost = abs(fill_price - bar_close) * qty

        if side == "BUY":
            total_cost = notional + fee
            if total_cost > portfolio.cash + 1e-9:
                return FillResult(False, 0.0, fill_price, 0.0, 0.0, "insufficient cash after fees")
            # Update avg entry
            new_qty = portfolio.position_qty + qty
            if new_qty > 0:
                portfolio.avg_entry = (
                    (portfolio.avg_entry * portfolio.position_qty) + (fill_price * qty)
                ) / new_qty
            portfolio.position_qty = new_qty
            portfolio.cash -= total_cost
            return FillResult(True, qty, fill_price, fee, slippage_cost, "filled buy")

        # SELL
        sell_qty = min(qty, portfolio.position_qty)
        if sell_qty <= 0:
            return FillResult(False, 0.0, fill_price, 0.0, 0.0, "no position")
        proceeds = sell_qty * fill_price - fee
        portfolio.realized_pnl += (fill_price - portfolio.avg_entry) * sell_qty - fee
        portfolio.position_qty -= sell_qty
        portfolio.cash += proceeds
        if portfolio.position_qty <= 1e-12:
            portfolio.position_qty = 0.0
            portfolio.avg_entry = 0.0
        return FillResult(True, sell_qty, fill_price, fee, slippage_cost, "filled sell")
