"""LEGACY float Portfolio fill model — compatibility shim only.

Canonical historical execution is NextBarFillModel in execution.py.
SimulationEngine.step_once must NOT call this module.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

from .accounting import WalletLedger, money
from .execution import NextBarFillModel
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
    """Thin adapter over NextBarFillModel for legacy Portfolio callers.

    Prefer NextBarFillModel + WalletLedger directly.
    """

    def __init__(
        self,
        *,
        fee_bps: float = 5.0,
        slippage_bps: float = 2.0,
        seed: int = 0,
        stochastic: bool = False,
        max_participation: float = 0.1,
    ) -> None:
        if stochastic:
            warnings.warn(
                "FillModel stochastic mode is ignored — NextBarFillModel is deterministic",
                DeprecationWarning,
                stacklevel=2,
            )
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self.seed = seed
        self.stochastic = False
        self._model = NextBarFillModel(
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            max_participation=max_participation,
        )

    def execute(
        self,
        *,
        portfolio: Portfolio,
        side: str,
        qty: float,
        bar_close: float,
        bar_volume: float,
    ) -> FillResult:
        """Compatibility: map Portfolio ↔ temporary WalletLedger, sync back."""
        from .execution import OrderIntent
        from .types import OrderSide

        if side == OrderSide.HOLD.value or qty <= 0:
            return FillResult(False, 0.0, bar_close, 0.0, 0.0, "no trade")
        if bar_close <= 0:
            return FillResult(False, 0.0, 0.0, 0.0, 0.0, "invalid bar close")

        wallet = WalletLedger(
            wallet_id="legacy-shim",
            owner_id="legacy",
            owner_kind="shared",
            cash=money(portfolio.cash),
            position_qty=money(portfolio.position_qty),
            avg_entry=money(portfolio.avg_entry),
            realized_pnl=money(portfolio.realized_pnl),
            peak_equity=money(portfolio.peak_equity or portfolio.cash),
        )
        intent = OrderIntent(
            intent_id=f"legacy-{self.seed}",
            run_id="legacy",
            agent_id="legacy",
            wallet_id=wallet.wallet_id,
            side=side,
            qty=money(qty),
            decision_bar_index=0,
            decision_ts="",
            eligible_bar_index=0,
            order_type="MARKET",
            time_in_force="BAR",
        )
        result = self._model.execute_intent(
            wallet=wallet,
            intent=intent,
            fill_open=bar_close,
            bar_volume=bar_volume,
            fill_bar_index=0,
        )
        # Sync wallet → portfolio
        portfolio.cash = float(wallet.cash)
        portfolio.position_qty = float(wallet.position_qty)
        portfolio.avg_entry = float(wallet.avg_entry)
        portfolio.realized_pnl = float(wallet.realized_pnl)
        portfolio.peak_equity = float(wallet.peak_equity)
        return FillResult(
            filled=result.filled,
            qty=float(result.qty),
            price=float(result.price),
            fee=float(result.fee),
            slippage=float(result.slippage),
            detail=result.detail,
        )
