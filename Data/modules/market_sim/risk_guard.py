"""Deterministic risk guard — model output cannot override limits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .accounting import D, WalletLedger, money
from .execution import OrderIntent


OVERRIDE_KEYS = (
    "risk_override",
    "override_limits",
    "bypass_risk",
    "force",
    "force_execute",
    "ignore_limits",
    "approved_by_model",
    "simulate_human_auth",
)


@dataclass(frozen=True)
class RiskLimits:
    max_position_pct: float = 25.0
    max_drawdown_pct: float = 20.0
    per_trade_risk_pct: float = 1.0
    max_orders_per_day: int = 50
    max_symbol_exposure_pct: float = 40.0
    leverage_allowed: bool = False
    kill_switch_armed: bool = False
    kill_switch_allows_risk_reduction: bool = True


@dataclass
class RiskDecision:
    allowed: bool
    reason: str
    sized_qty: float = 0.0
    blocked_keys: list[str] | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "sized_qty": self.sized_qty,
            "blocked_keys": self.blocked_keys or [],
        }


class RiskGuard:
    """Decisive veto layer outside agents. Override-looking keys are themselves blocks."""

    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits
        self.killed = bool(limits.kill_switch_armed)
        self.kill_reason: str | None = "kill switch armed" if self.killed else None
        self.orders_today = 0

    def arm_kill_switch(self, reason: str) -> None:
        self.killed = True
        self.kill_reason = reason
        self.limits = RiskLimits(
            max_position_pct=self.limits.max_position_pct,
            max_drawdown_pct=self.limits.max_drawdown_pct,
            per_trade_risk_pct=self.limits.per_trade_risk_pct,
            max_orders_per_day=self.limits.max_orders_per_day,
            max_symbol_exposure_pct=self.limits.max_symbol_exposure_pct,
            leverage_allowed=False,
            kill_switch_armed=True,
            kill_switch_allows_risk_reduction=self.limits.kill_switch_allows_risk_reduction,
        )

    def check_drawdown(self, wallet: WalletLedger, price: float) -> bool:
        dd = wallet.drawdown_pct(price)
        if dd >= self.limits.max_drawdown_pct:
            self.arm_kill_switch(f"Max drawdown kill-switch at {dd:.2f}%")
            return False
        return True

    def evaluate_intent(
        self,
        intent: OrderIntent,
        *,
        wallet: WalletLedger,
        price: float,
    ) -> RiskDecision:
        meta = intent.metadata or {}
        blocked = [k for k in OVERRIDE_KEYS if k in meta]
        if blocked:
            return RiskDecision(
                False,
                f"override_attempt_rejected:{','.join(sorted(blocked))}",
                blocked_keys=blocked,
            )

        if not self.limits.leverage_allowed and meta.get("leverage"):
            return RiskDecision(False, "leverage disabled by default")

        reduces = (
            intent.side == "SELL" and wallet.position_qty > 0
        ) or intent.side == "HOLD"

        if self.killed or self.limits.kill_switch_armed:
            if reduces and self.limits.kill_switch_allows_risk_reduction:
                pass
            else:
                return RiskDecision(False, self.kill_reason or "kill switch armed")

        if self.orders_today >= self.limits.max_orders_per_day and intent.side in {"BUY", "SELL"}:
            return RiskDecision(False, "max orders per day reached")

        if intent.side == "HOLD":
            return RiskDecision(True, "hold", sized_qty=0.0)

        equity = float(wallet.equity(price))
        if price <= 0 or equity <= 0:
            return RiskDecision(False, "invalid price/equity")

        max_notional = equity * (self.limits.max_position_pct / 100.0)
        risk_notional = equity * (self.limits.per_trade_risk_pct / 100.0)
        cap_qty = max_notional / price
        risk_qty = risk_notional / price
        requested = float(intent.qty) if intent.qty is not None else None

        if intent.side == "BUY":
            affordable = float(wallet.available_cash) / price
            target = requested if requested is not None else min(cap_qty, risk_qty)
            qty = max(0.0, min(target, cap_qty, affordable, risk_qty * 5))
            if qty <= 0:
                return RiskDecision(False, "insufficient cash or size")
            pos_after = float(wallet.position_qty) + qty
            if pos_after * price > equity * (self.limits.max_symbol_exposure_pct / 100.0) + 1e-9:
                qty = max(0.0, (equity * self.limits.max_symbol_exposure_pct / 100.0) / price - float(wallet.position_qty))
                if qty <= 0:
                    return RiskDecision(False, "max symbol exposure")
            return RiskDecision(True, "sized", sized_qty=qty)

        if intent.side == "SELL":
            if wallet.position_qty <= 0:
                return RiskDecision(False, "no long position to sell")
            target = requested if requested is not None else float(wallet.position_qty)
            qty = max(0.0, min(target, float(wallet.position_qty)))
            if qty <= 0:
                return RiskDecision(False, "zero sell size")
            return RiskDecision(True, "sized", sized_qty=qty)

        return RiskDecision(False, f"unknown side {intent.side}")

    def size_order(
        self,
        *,
        portfolio: Any,
        price: float,
        side: str,
        requested_qty: float | None,
        equity: float,
    ) -> RiskDecision:
        """Back-compat shim for legacy Portfolio path."""
        from .portfolio import Portfolio

        if isinstance(portfolio, Portfolio):
            wallet = WalletLedger(
                wallet_id="legacy",
                owner_id="legacy",
                owner_kind="shared",
                cash=money(portfolio.cash),
                position_qty=money(portfolio.position_qty),
                avg_entry=money(portfolio.avg_entry),
                realized_pnl=money(portfolio.realized_pnl),
                peak_equity=money(portfolio.peak_equity),
            )
        else:
            wallet = portfolio
        intent = OrderIntent(
            intent_id="tmp",
            run_id="tmp",
            agent_id="legacy",
            wallet_id=getattr(wallet, "wallet_id", "legacy"),
            side=side,
            qty=None if requested_qty is None else money(requested_qty),
            decision_bar_index=0,
            decision_ts="",
            eligible_bar_index=1,
        )
        return self.evaluate_intent(intent, wallet=wallet, price=price)
