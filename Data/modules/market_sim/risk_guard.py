"""Deterministic risk guard — model output cannot override limits."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .accounting import D, WalletLedger, money
from .execution import OrderIntent
from .instruments import InstrumentSpec, validate_intent_rules
from .short_margin import ShortMarginPolicy
from .sizing import SizingModel


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


def _utc_day(ts: str | datetime | None) -> str | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        dt = ts
    else:
        raw = str(ts).strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            # date-only or bare date prefix
            if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
                return raw[:10]
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date().isoformat()


class RiskGuard:
    """Decisive veto layer outside agents. Override-looking keys are themselves blocks."""

    def __init__(
        self,
        limits: RiskLimits,
        *,
        sizing_model: SizingModel | None = None,
        instrument_spec: InstrumentSpec | None = None,
        short_margin_policy: ShortMarginPolicy | None = None,
        portfolio_shorting_enabled: bool | None = None,
    ) -> None:
        self.limits = limits
        self.killed = bool(limits.kill_switch_armed)
        self.kill_reason: str | None = "kill switch armed" if self.killed else None
        self.orders_today = 0
        self._current_utc_day: str | None = None
        self.sizing_model = sizing_model or SizingModel(
            kind="risk_pct",
            per_trade_risk_pct=limits.per_trade_risk_pct,
            max_position_pct=limits.max_position_pct,
        )
        self.instrument_spec = instrument_spec
        self.short_margin_policy = short_margin_policy
        self.portfolio_shorting_enabled = portfolio_shorting_enabled

    def on_bar_timestamp(self, ts: str | datetime | None) -> None:
        """Reset orders_today when the UTC calendar day changes."""
        day = _utc_day(ts)
        if day is None:
            return
        if self._current_utc_day is None:
            self._current_utc_day = day
            return
        if day != self._current_utc_day:
            self.orders_today = 0
            self._current_utc_day = day

    # Alias used by some call sites / characterization
    roll_day = on_bar_timestamp

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

    def clear_kill_switch(self, reason: str = "cleared") -> None:
        """Disarm kill switch. State must be explicit — never ambiguous.

        ``reason`` is accepted for audit call-sites; armed/clear flags are the
        authoritative state via ``kill_switch_state()``.
        """
        _ = reason
        self.killed = False
        self.kill_reason = None
        self.limits = RiskLimits(
            max_position_pct=self.limits.max_position_pct,
            max_drawdown_pct=self.limits.max_drawdown_pct,
            per_trade_risk_pct=self.limits.per_trade_risk_pct,
            max_orders_per_day=self.limits.max_orders_per_day,
            max_symbol_exposure_pct=self.limits.max_symbol_exposure_pct,
            leverage_allowed=self.limits.leverage_allowed,
            kill_switch_armed=False,
            kill_switch_allows_risk_reduction=self.limits.kill_switch_allows_risk_reduction,
        )

    def kill_switch_state(self) -> dict[str, Any]:
        """Clear, unambiguous kill-switch status for callers / tests."""
        armed = bool(self.killed or self.limits.kill_switch_armed)
        return {
            "armed": armed,
            "clear": not armed,
            "reason": self.kill_reason,
            "allows_risk_reduction": bool(self.limits.kill_switch_allows_risk_reduction),
            "limits_kill_switch_armed": bool(self.limits.kill_switch_armed),
            "runtime_killed": bool(self.killed),
        }

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
            (intent.side == "SELL" and wallet.position_qty > 0)
            or (intent.side == "BUY" and wallet.position_qty < 0)
            or intent.side == "HOLD"
        )

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

        requested = float(intent.qty) if intent.qty is not None else None
        opening_short = intent.side == "SELL" and float(wallet.position_qty) <= 0
        increasing_short = intent.side == "SELL" and float(wallet.position_qty) < 0

        if intent.side == "BUY":
            if float(wallet.position_qty) < 0:
                short_abs = abs(float(wallet.position_qty))
                target = requested if requested is not None else short_abs
                allow_rev = bool(
                    (intent.metadata or {}).get("allow_position_reversal")
                    or getattr(wallet, "allow_position_reversal", False)
                )
                if target > short_abs + 1e-12 and not allow_rev:
                    qty = short_abs
                    reason = "sized_cover_no_reversal"
                    if qty <= 0:
                        return RiskDecision(False, "POSITION_REVERSAL_BLOCKED")
                else:
                    qty = max(0.0, target)
                    reason = "sized_short_cover"
                if qty <= 0:
                    return RiskDecision(False, "zero cover size")
            else:
                qty, reason = self.sizing_model.target_qty(
                    price=price,
                    equity=equity,
                    available_cash=float(wallet.available_cash),
                    requested_qty=requested,
                )
                if qty <= 0:
                    return RiskDecision(False, "insufficient cash or size")
                pos_after = float(wallet.position_qty) + qty
                max_sym = equity * (self.limits.max_symbol_exposure_pct / 100.0)
                if pos_after * price > max_sym + 1e-9:
                    qty = max(0.0, max_sym / price - float(wallet.position_qty))
                    if qty <= 0:
                        return RiskDecision(False, "max symbol exposure")
                    reason = "sized_symbol_cap"
        elif intent.side == "SELL":
            long_exit_only = float(wallet.position_qty) > 0 and not (
                requested is not None
                and requested > float(wallet.position_qty) + 1e-12
                and (
                    getattr(wallet, "shorting_enabled", False)
                    or self.portfolio_shorting_enabled is True
                    or self.short_margin_policy is not None
                )
            )
            if long_exit_only:
                target = requested if requested is not None else float(wallet.position_qty)
                qty = max(0.0, min(target, float(wallet.position_qty)))
                reason = "sized_long_exit"
                if qty <= 0:
                    return RiskDecision(False, "zero sell size")
            else:
                if self.portfolio_shorting_enabled is False:
                    return RiskDecision(False, "PORTFOLIO_SHORTING_DISABLED")
                ok_short = True
                short_reason = "short_allowed"
                if self.instrument_spec is not None:
                    ok_short, short_reason, _ = validate_intent_rules(
                        spec=self.instrument_spec,
                        side=intent.side,
                        qty=requested or 0,
                        price=price,
                        opening_short=True,
                        short_margin_policy=self.short_margin_policy,
                    )
                else:
                    from .short_margin import short_open_allowed

                    ok_short, short_reason = short_open_allowed(
                        supports_short=bool(
                            getattr(wallet, "shorting_enabled", False)
                            or self.short_margin_policy is not None
                        ),
                        margin_policy=self.short_margin_policy,
                    )
                if not ok_short:
                    return RiskDecision(False, short_reason)
                if (
                    getattr(wallet, "short_margin_policy", None) is None
                    and self.short_margin_policy is not None
                ):
                    wallet.short_margin_policy = self.short_margin_policy
                if not getattr(wallet, "shorting_enabled", False):
                    wallet.shorting_enabled = True
                qty, reason = self.sizing_model.target_qty(
                    price=price,
                    equity=equity,
                    available_cash=float(wallet.available_cash),
                    requested_qty=requested,
                )
                if qty <= 0:
                    return RiskDecision(False, "insufficient margin/size for short")
                policy = self.short_margin_policy or getattr(
                    wallet, "short_margin_policy", None
                )
                if policy is not None:
                    from .short_margin import ShortMarginPolicy

                    if isinstance(policy, dict):
                        policy = ShortMarginPolicy.from_dict(policy)
                    if policy is not None:
                        margin_need = (
                            qty * price * float(policy.initial_margin_pct) / 100.0
                        )
                        # Pre-proceeds available cash only — do not let short proceeds fund margin.
                        if float(wallet.available_cash) < margin_need - 1e-6:
                            return RiskDecision(False, "MARGIN_BLOCK: insufficient for initial margin")
                reason = f"short_{reason}"
        else:
            return RiskDecision(False, f"unknown side {intent.side}")

        if self.instrument_spec is not None and qty > 0:
            ok, rule_reason, rounded = validate_intent_rules(
                spec=self.instrument_spec,
                side=intent.side,
                qty=qty,
                price=price,
                opening_short=(opening_short or increasing_short)
                and float(wallet.position_qty) <= 0,
                short_margin_policy=self.short_margin_policy,
            )
            if not ok:
                return RiskDecision(False, rule_reason)
            qty = float(rounded)
            if qty <= 0:
                return RiskDecision(False, "INSTRUMENT_RULE: qty rounds to zero")

        return RiskDecision(True, reason, sized_qty=qty)

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
