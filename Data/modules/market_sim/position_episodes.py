"""Closed position episode tracker — foundation for closed-trade win rate (P0A).

Fill-level realized_delta supports interim metrics but is NOT the definition of
"one won trade". Win rate over ClosedTrade / PositionEpisode is the canonical
closed-trade measure once episodes are attributed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from .types import ClosedTrade, FillStatus


@dataclass
class _OpenEpisode:
    trade_id: str
    side: str  # LONG | SHORT
    opened_at: str
    open_bar_index: int
    entry_quantity: float = 0.0
    avg_entry_price: float = 0.0
    fees: float = 0.0
    slippage_cost: float = 0.0
    partial_fill_count: int = 0
    exit_quantity: float = 0.0
    exit_notional: float = 0.0
    agent_id: str | None = None


@dataclass
class PositionEpisodeTracker:
    """Accumulate fills into closed position episodes for one instrument/wallet."""

    run_id: str
    instrument: str
    strategy_id: str | None = None
    strategy_version: int | None = None
    closed: list[ClosedTrade] = field(default_factory=list)
    _open: _OpenEpisode | None = None

    def on_fill(
        self,
        *,
        side: str,
        qty: float,
        price: float,
        fee: float,
        slippage: float = 0.0,
        ts: str,
        bar_index: int,
        status: str = FillStatus.FILLED.value,
        agent_id: str | None = None,
        close_reason: str = "signal",
        trade_id: str | None = None,
    ) -> ClosedTrade | None:
        """Apply one fill. Returns ClosedTrade when an episode fully closes."""
        q = float(qty)
        if q <= 0:
            return None
        px = float(price)
        f = float(fee)
        slip = float(slippage)
        is_partial = status == FillStatus.PARTIAL.value

        if side.upper() == "BUY":
            return self._apply_buy(
                qty=q,
                price=px,
                fee=f,
                slippage=slip,
                ts=ts,
                bar_index=bar_index,
                is_partial=is_partial,
                agent_id=agent_id,
                trade_id=trade_id,
            )
        if side.upper() == "SELL":
            return self._apply_sell(
                qty=q,
                price=px,
                fee=f,
                slippage=slip,
                ts=ts,
                bar_index=bar_index,
                is_partial=is_partial,
                agent_id=agent_id,
                close_reason=close_reason,
            )
        return None

    def _apply_buy(
        self,
        *,
        qty: float,
        price: float,
        fee: float,
        slippage: float,
        ts: str,
        bar_index: int,
        is_partial: bool,
        agent_id: str | None,
        trade_id: str | None,
    ) -> ClosedTrade | None:
        if self._open is None:
            self._open = _OpenEpisode(
                trade_id=trade_id or str(uuid.uuid4()),
                side="LONG",
                opened_at=ts,
                open_bar_index=bar_index,
                entry_quantity=qty,
                avg_entry_price=price,
                fees=fee,
                slippage_cost=slippage,
                partial_fill_count=1 if is_partial else 0,
                agent_id=agent_id,
            )
            return None
        if self._open.side == "SHORT":
            # Cover short — treat as exit toward flat; full short semantics land in P0C.
            return self._reduce_open(
                qty=qty,
                price=price,
                fee=fee,
                slippage=slippage,
                ts=ts,
                bar_index=bar_index,
                is_partial=is_partial,
                close_reason="cover",
            )
        # Scale in long
        ep = self._open
        new_qty = ep.entry_quantity + qty
        if new_qty > 0:
            ep.avg_entry_price = (
                ep.avg_entry_price * ep.entry_quantity + price * qty
            ) / new_qty
        ep.entry_quantity = new_qty
        ep.fees += fee
        ep.slippage_cost += slippage
        if is_partial:
            ep.partial_fill_count += 1
        return None

    def _apply_sell(
        self,
        *,
        qty: float,
        price: float,
        fee: float,
        slippage: float,
        ts: str,
        bar_index: int,
        is_partial: bool,
        agent_id: str | None,
        close_reason: str,
    ) -> ClosedTrade | None:
        if self._open is None:
            # Opening short without margin policy is blocked elsewhere (P0C).
            # Track as SHORT episode foundation only when explicitly enabled later.
            self._open = _OpenEpisode(
                trade_id=str(uuid.uuid4()),
                side="SHORT",
                opened_at=ts,
                open_bar_index=bar_index,
                entry_quantity=qty,
                avg_entry_price=price,
                fees=fee,
                slippage_cost=slippage,
                partial_fill_count=1 if is_partial else 0,
                agent_id=agent_id,
            )
            return None
        if self._open.side == "LONG":
            return self._reduce_open(
                qty=qty,
                price=price,
                fee=fee,
                slippage=slippage,
                ts=ts,
                bar_index=bar_index,
                is_partial=is_partial,
                close_reason=close_reason,
            )
        # Increase short
        ep = self._open
        new_qty = ep.entry_quantity + qty
        if new_qty > 0:
            ep.avg_entry_price = (
                ep.avg_entry_price * ep.entry_quantity + price * qty
            ) / new_qty
        ep.entry_quantity = new_qty
        ep.fees += fee
        ep.slippage_cost += slippage
        if is_partial:
            ep.partial_fill_count += 1
        return None

    def _reduce_open(
        self,
        *,
        qty: float,
        price: float,
        fee: float,
        slippage: float,
        ts: str,
        bar_index: int,
        is_partial: bool,
        close_reason: str,
    ) -> ClosedTrade | None:
        ep = self._open
        assert ep is not None
        exit_qty = min(qty, ep.entry_quantity - ep.exit_quantity)
        if exit_qty <= 0:
            return None
        ep.exit_quantity += exit_qty
        ep.exit_notional += exit_qty * price
        ep.fees += fee
        ep.slippage_cost += slippage
        if is_partial:
            ep.partial_fill_count += 1

        remaining = ep.entry_quantity - ep.exit_quantity
        if remaining > 1e-12:
            return None

        avg_exit = ep.exit_notional / ep.exit_quantity if ep.exit_quantity else 0.0
        if ep.side == "LONG":
            gross = (avg_exit - ep.avg_entry_price) * ep.exit_quantity
        else:
            gross = (ep.avg_entry_price - avg_exit) * ep.exit_quantity
        net = gross - ep.fees
        closed = ClosedTrade(
            trade_id=ep.trade_id,
            run_id=self.run_id,
            instrument=self.instrument,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            opened_at=ep.opened_at,
            closed_at=ts,
            side=ep.side,
            entry_quantity=ep.entry_quantity,
            exit_quantity=ep.exit_quantity,
            avg_entry_price=ep.avg_entry_price,
            avg_exit_price=avg_exit,
            gross_pnl=gross,
            fees=ep.fees,
            slippage_cost=ep.slippage_cost,
            net_pnl=net,
            holding_period_bars=max(0, bar_index - ep.open_bar_index),
            partial_fill_count=ep.partial_fill_count,
            close_reason=close_reason,
            open_bar_index=ep.open_bar_index,
            close_bar_index=bar_index,
            agent_id=ep.agent_id,
        )
        self.closed.append(closed)
        self._open = None
        return closed

    def open_quantity(self) -> float:
        if self._open is None:
            return 0.0
        return max(0.0, self._open.entry_quantity - self._open.exit_quantity)

    def current_trade_id(self) -> str | None:
        return self._open.trade_id if self._open else None

    def public_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "instrument": self.instrument,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "open_quantity": self.open_quantity(),
            "current_trade_id": self.current_trade_id(),
            "closed_trades": [t.public_dict() for t in self.closed],
        }
