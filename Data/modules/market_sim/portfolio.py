"""Portfolio state and risk constraints for paper simulation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Portfolio:
    cash: float
    position_qty: float = 0.0
    avg_entry: float = 0.0
    realized_pnl: float = 0.0
    peak_equity: float = 0.0
    equity_curve: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.peak_equity <= 0:
            self.peak_equity = self.cash

    def mark_to_market(self, price: float) -> float:
        unrealized = self.position_qty * (price - self.avg_entry) if self.position_qty else 0.0
        equity = self.cash + self.position_qty * price
        self.peak_equity = max(self.peak_equity, equity)
        self.equity_curve.append(equity)
        return equity

    @property
    def unrealized_pnl(self) -> float:
        if not self.equity_curve or self.position_qty == 0:
            return 0.0
        # Caller should use last mark; keep simple.
        return 0.0

    def drawdown_pct(self, equity: float) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - equity) / self.peak_equity * 100.0)

    def public_dict(self, price: float) -> dict[str, Any]:
        equity = self.cash + self.position_qty * price
        unrealized = self.position_qty * (price - self.avg_entry) if self.position_qty else 0.0
        return {
            "cash": self.cash,
            "position_qty": self.position_qty,
            "avg_entry": self.avg_entry,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": unrealized,
            "equity": equity,
            "peak_equity": self.peak_equity,
            "drawdown_pct": self.drawdown_pct(equity),
        }


@dataclass(frozen=True)
class RiskLimits:
    max_position_pct: float = 25.0
    max_drawdown_pct: float = 20.0
    per_trade_risk_pct: float = 1.0


@dataclass
class RiskDecision:
    allowed: bool
    reason: str
    sized_qty: float = 0.0

    def public_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "sized_qty": self.sized_qty,
        }


class RiskEngine:
    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits
        self.killed = False
        self.kill_reason: str | None = None

    def check_drawdown(self, portfolio: Portfolio, equity: float) -> bool:
        dd = portfolio.drawdown_pct(equity)
        if dd >= self.limits.max_drawdown_pct:
            self.killed = True
            self.kill_reason = f"Max drawdown kill-switch at {dd:.2f}%"
            return False
        return True

    def size_order(
        self,
        *,
        portfolio: Portfolio,
        price: float,
        side: str,
        requested_qty: float | None,
        equity: float,
    ) -> RiskDecision:
        if self.killed:
            return RiskDecision(False, self.kill_reason or "risk kill-switch active")
        if price <= 0:
            return RiskDecision(False, "invalid price")
        if side == "HOLD":
            return RiskDecision(True, "hold", sized_qty=0.0)

        max_notional = equity * (self.limits.max_position_pct / 100.0)
        risk_notional = equity * (self.limits.per_trade_risk_pct / 100.0)
        cap_qty = max_notional / price
        risk_qty = risk_notional / price

        if side == "BUY":
            affordable = portfolio.cash / price
            target = requested_qty if requested_qty is not None else min(cap_qty, risk_qty)
            qty = max(0.0, min(target, cap_qty, affordable, risk_qty))
            if qty <= 0:
                return RiskDecision(False, "insufficient cash or size")
            # Position cap after buy
            if (portfolio.position_qty + qty) * price > max_notional + 1e-9:
                qty = max(0.0, (max_notional / price) - portfolio.position_qty)
                if qty <= 0:
                    return RiskDecision(False, "max position reached")
            return RiskDecision(True, "sized", sized_qty=qty)

        if side == "SELL":
            if portfolio.position_qty <= 0:
                return RiskDecision(False, "no long position to sell")
            target = requested_qty if requested_qty is not None else portfolio.position_qty
            qty = max(0.0, min(target, portfolio.position_qty))
            if qty <= 0:
                return RiskDecision(False, "zero sell size")
            return RiskDecision(True, "sized", sized_qty=qty)

        return RiskDecision(False, f"unknown side {side}")
