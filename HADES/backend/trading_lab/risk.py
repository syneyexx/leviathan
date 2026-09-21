"""Risk Engine.

Deterministic code with the decisive veto. There is no parameter, prompt field or metadata
key through which a model can raise a limit or overrule a block: :meth:`RiskEngine.evaluate`
reads limits only from the stored :class:`RiskLimits`, and any override-looking key on an
intent is itself a blocking reason.

Kill switch semantics are explicit, because "kill switch" alone is ambiguous:

- new exposure is blocked;
- risk-reducing orders stay allowed when ``kill_switch_allows_risk_reduction`` is set,
  otherwise nothing is allowed;
- open working orders are cancelled when ``kill_switch_cancels_open_orders`` is set;
- existing positions are **not** force-closed. Liquidating into an unknown market is a
  separate, explicit operator action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from typing import Any, Iterable, Sequence

from trading_lab.accounting import Portfolio
from trading_lab.adapters import InstrumentAdapter
from trading_lab.contracts import (
    InstrumentSpec,
    MarketEvent,
    OrderIntent,
    RiskDecision,
    RiskLimits,
    quantize_step,
    to_decimal,
)

ZERO = Decimal("0")
ENGINE_VERSION = "risk-engine-1"

OVERRIDE_KEYS = (
    "risk_override",
    "override_limits",
    "bypass_risk",
    "force",
    "force_execute",
    "ignore_limits",
    "approved_by_model",
)


@dataclass
class RiskContext:
    """Everything the engine needs, all of it factual."""

    event: MarketEvent | None = None
    equity: Decimal = ZERO
    peak_equity: Decimal = ZERO
    day_realized_pnl: Decimal = ZERO
    open_order_count: int = 0
    stale_seconds: float | None = None
    data_complete: bool = True
    correlation_groups: dict[str, str] = field(default_factory=dict)
    kill_switch_armed: bool = False
    notes: list[str] = field(default_factory=list)


class RiskEngine:
    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits

    # --- public ------------------------------------------------------------------

    def evaluate(
        self,
        intent: OrderIntent,
        *,
        spec: InstrumentSpec,
        adapter: InstrumentAdapter,
        portfolio: Portfolio,
        context: RiskContext,
    ) -> RiskDecision:
        reasons: list[str] = []
        limits = self.limits
        armed = limits.kill_switch_armed or context.kill_switch_armed
        position = portfolio.position(spec.instrument_id)
        held = position.signed_quantity if position else ZERO
        reduces = self._is_risk_reducing(intent, held)

        override = [key for key in OVERRIDE_KEYS if key in (intent.metadata or {})]
        if override:
            return self._block(
                [
                    f"override_attempt_rejected:{','.join(sorted(override))} — "
                    "the risk engine has the decisive veto and accepts no override field"
                ],
                limits,
                context,
            )

        if armed:
            if not reduces:
                return self._block(["kill_switch_blocks_new_exposure"], limits, context)
            if not limits.kill_switch_allows_risk_reduction:
                return self._block(
                    ["kill_switch_blocks_everything: risk reduction is disabled by configuration"],
                    limits,
                    context,
                )
            reasons.append("kill_switch_armed: risk-reducing order permitted")

        ok, reason = adapter.validate_intent(spec, intent, position)
        if not ok:
            return self._block([f"instrument_rule:{reason}"], limits, context)

        if not context.data_complete and not reduces:
            return self._block(["incomplete_market_data_blocks_new_exposure"], limits, context)

        if (
            limits.max_stale_data_seconds > 0
            and context.stale_seconds is not None
            and context.stale_seconds > limits.max_stale_data_seconds
            and not reduces
        ):
            return self._block(
                [
                    f"stale_data:{context.stale_seconds:.0f}s > "
                    f"max_stale_data_seconds:{limits.max_stale_data_seconds}"
                ],
                limits,
                context,
            )

        if context.open_order_count >= limits.max_open_orders and not reduces:
            return self._block(
                [f"max_open_orders_reached:{limits.max_open_orders}"], limits, context
            )

        drawdown_block = self._drawdown_block(context, reduces)
        if drawdown_block:
            return self._block([drawdown_block], limits, context)

        reference = self._reference_price(intent, context)
        if reference is None:
            return self._block(["no_reference_price_available_for_risk_sizing"], limits, context)

        approved = intent.quantity
        if reduces:
            # Risk reduction is never scaled down by exposure limits; that would trap risk.
            approved = min(approved, abs(held)) if held != ZERO else approved
            reasons.append("risk_reducing_order")
            return self._allow(approved, intent, spec, reasons, limits, context)

        approved, sized_reasons = self._apply_sizing_limits(
            intent,
            spec=spec,
            adapter=adapter,
            portfolio=portfolio,
            context=context,
            reference=reference,
            requested=approved,
        )
        reasons.extend(sized_reasons)

        approved = quantize_step(approved, spec.lot_size, rounding=ROUND_DOWN)
        if approved <= 0:
            return self._block(reasons or ["risk_limits_reduce_order_to_zero"], limits, context)

        margin_reason = self._margin_check(
            intent, spec=spec, adapter=adapter, portfolio=portfolio, quantity=approved, reference=reference
        )
        if margin_reason:
            return self._block([margin_reason], limits, context)

        return self._allow(approved, intent, spec, reasons, limits, context)

    def on_kill_switch(self, *, armed: bool) -> dict[str, Any]:
        """Declared behaviour, used by the engine and shown in the UI."""
        return {
            "armed": armed,
            "new_exposure": "blocked" if armed else "allowed",
            "risk_reduction": (
                "allowed" if (armed and self.limits.kill_switch_allows_risk_reduction) else ("blocked" if armed else "allowed")
            ),
            "open_orders": (
                "cancelled" if (armed and self.limits.kill_switch_cancels_open_orders) else "left_working"
            ),
            "existing_positions": "left_open — force-closing is a separate explicit operator action",
        }

    # --- internals ---------------------------------------------------------------

    @staticmethod
    def _is_risk_reducing(intent: OrderIntent, held: Decimal) -> bool:
        if intent.reduce_only:
            return True
        if held == ZERO:
            return False
        if held > ZERO and intent.side == "sell":
            return intent.quantity <= held
        if held < ZERO and intent.side == "buy":
            return intent.quantity <= abs(held)
        return False

    @staticmethod
    def _reference_price(intent: OrderIntent, context: RiskContext) -> Decimal | None:
        for candidate in (intent.limit_price, intent.stop_price):
            if candidate is not None:
                return abs(candidate)
        if context.event is not None:
            try:
                return abs(to_decimal(context.event.reference_price))
            except ValueError:
                return None
        return None

    def _drawdown_block(self, context: RiskContext, reduces: bool) -> str | None:
        limits = self.limits
        if reduces:
            return None
        if limits.max_daily_loss is not None and context.day_realized_pnl < -abs(limits.max_daily_loss):
            return f"daily_loss_limit_hit:{context.day_realized_pnl} < -{limits.max_daily_loss}"
        if (
            limits.max_drawdown_fraction is not None
            and context.peak_equity > 0
            and context.equity > 0
        ):
            drawdown = (context.peak_equity - context.equity) / context.peak_equity
            if drawdown > limits.max_drawdown_fraction:
                return (
                    f"drawdown_limit_hit:{drawdown:.4f} > {limits.max_drawdown_fraction} "
                    f"(peak {context.peak_equity}, equity {context.equity})"
                )
        return None

    def _apply_sizing_limits(
        self,
        intent: OrderIntent,
        *,
        spec: InstrumentSpec,
        adapter: InstrumentAdapter,
        portfolio: Portfolio,
        context: RiskContext,
        reference: Decimal,
        requested: Decimal,
    ) -> tuple[Decimal, list[str]]:
        limits = self.limits
        reasons: list[str] = []
        approved = requested
        unit_notional = adapter.order_notional(spec, Decimal("1"), reference)
        if unit_notional <= 0:
            return ZERO, ["zero_unit_notional"]

        def cap(maximum: Decimal, label: str) -> None:
            nonlocal approved
            allowed = maximum / unit_notional
            if allowed < approved:
                reasons.append(f"{label}:reduced_to_{allowed}")
                approved = allowed if allowed > 0 else ZERO

        if limits.max_order_notional is not None:
            cap(limits.max_order_notional, "max_order_notional")

        position = portfolio.position(spec.instrument_id)
        current_notional = position.notional() if position else ZERO
        if limits.max_position_notional is not None:
            headroom = limits.max_position_notional - current_notional
            if headroom <= 0:
                return ZERO, reasons + [f"max_position_notional_exhausted:{limits.max_position_notional}"]
            cap(headroom, "max_position_notional")

        gross = portfolio.gross_exposure()
        if limits.max_gross_exposure is not None:
            headroom = limits.max_gross_exposure - gross
            if headroom <= 0:
                return ZERO, reasons + [f"max_gross_exposure_exhausted:{limits.max_gross_exposure}"]
            cap(headroom, "max_gross_exposure")

        if limits.max_net_exposure is not None:
            net = portfolio.net_exposure()
            direction = Decimal("1") if intent.side == "buy" else Decimal("-1")
            projected_room = limits.max_net_exposure - (net * direction)
            if projected_room <= 0:
                return ZERO, reasons + [f"max_net_exposure_exhausted:{limits.max_net_exposure}"]
            cap(projected_room, "max_net_exposure")

        if limits.max_leverage is not None and context.equity > 0:
            headroom = (limits.max_leverage * context.equity) - gross
            if headroom <= 0:
                return ZERO, reasons + [
                    f"max_leverage_exhausted:{limits.max_leverage} (gross {gross}, equity {context.equity})"
                ]
            cap(headroom, "max_leverage")

        if limits.max_instrument_concentration is not None and context.equity > 0:
            headroom = (limits.max_instrument_concentration * context.equity) - current_notional
            if headroom <= 0:
                return ZERO, reasons + [
                    f"instrument_concentration_exhausted:{limits.max_instrument_concentration}"
                ]
            cap(headroom, "max_instrument_concentration")

        if limits.max_correlated_group_exposure is not None and context.equity > 0:
            group = context.correlation_groups.get(spec.instrument_id)
            if group:
                group_notional = ZERO
                for other in portfolio.positions.values():
                    if context.correlation_groups.get(other.instrument_id) == group:
                        group_notional += other.notional()
                headroom = (limits.max_correlated_group_exposure * context.equity) - group_notional
                if headroom <= 0:
                    return ZERO, reasons + [
                        f"correlated_group_exposure_exhausted:{group}:{limits.max_correlated_group_exposure}"
                    ]
                cap(headroom, f"max_correlated_group_exposure:{group}")

        if limits.max_participation is not None and context.event is not None and context.event.volume:
            allowance = to_decimal(context.event.volume) * limits.max_participation
            if allowance < approved:
                reasons.append(f"max_participation:reduced_to_{allowance}")
                approved = allowance if allowance > 0 else ZERO

        if spec.min_notional > 0 and approved * unit_notional < spec.min_notional:
            return ZERO, reasons + [f"below_min_notional_after_risk_sizing:{spec.min_notional}"]

        return approved, reasons

    def _margin_check(
        self,
        intent: OrderIntent,
        *,
        spec: InstrumentSpec,
        adapter: InstrumentAdapter,
        portfolio: Portfolio,
        quantity: Decimal,
        reference: Decimal,
    ) -> str | None:
        notional = adapter.order_notional(spec, quantity, reference)
        if adapter.settlement_style == "funded" and intent.side == "buy":
            available = portfolio.available(spec.settle_currency)
            if available < notional:
                return (
                    f"insufficient_settlement_cash:{spec.settle_currency} "
                    f"available={available} required={notional}"
                )
            return None
        required_initial = notional * spec.initial_margin_rate
        buffer = Decimal("1") + self.limits.min_maintenance_margin_buffer
        available = portfolio.available(spec.settle_currency)
        if available < required_initial * buffer:
            return (
                f"insufficient_margin:{spec.settle_currency} available={available} "
                f"required={required_initial} buffer={self.limits.min_maintenance_margin_buffer}"
            )
        return None

    def worst_case_shock(
        self,
        *,
        portfolio: Portfolio,
        shock_fraction: Decimal = Decimal("0.2"),
    ) -> dict[str, str]:
        """Simple adverse-move scenario used as a margin sanity check, not a VaR claim."""
        loss = ZERO
        for position in portfolio.positions.values():
            if position.is_flat or position.mark_price is None:
                continue
            adverse = position.mark_price * (Decimal("1") - shock_fraction) if position.signed_quantity > 0 else position.mark_price * (Decimal("1") + shock_fraction)
            change = position.signed_quantity * (adverse - position.mark_price) * position.multiplier
            converted = portfolio.convert(position.currency, change)
            loss += converted if converted is not None else ZERO
        equity, _ = portfolio.equity()
        return {
            "shock_fraction": str(shock_fraction),
            "projected_pnl": str(loss),
            "projected_equity": str(equity + loss),
            "method": "single adverse parallel shock; not a distributional value-at-risk estimate",
        }

    def _allow(
        self,
        approved: Decimal,
        intent: OrderIntent,
        spec: InstrumentSpec,
        reasons: Sequence[str],
        limits: RiskLimits,
        context: RiskContext,
    ) -> RiskDecision:
        reduced = approved < intent.quantity
        return RiskDecision(
            decision="allow_reduced" if reduced else "allow",
            approved_quantity=approved,
            reasons=list(reasons) + ([f"requested {intent.quantity} reduced to {approved}"] if reduced else []),
            limit_snapshot=self._snapshot(limits, context, spec),
            evaluated_at=context.event.event_time if context.event else "",
            engine_version=ENGINE_VERSION,
        )

    def _block(self, reasons: Sequence[str], limits: RiskLimits, context: RiskContext) -> RiskDecision:
        return RiskDecision(
            decision="block",
            approved_quantity=ZERO,
            reasons=list(reasons),
            limit_snapshot=self._snapshot(limits, context, None),
            evaluated_at=context.event.event_time if context.event else "",
            engine_version=ENGINE_VERSION,
        )

    @staticmethod
    def _snapshot(limits: RiskLimits, context: RiskContext, spec: InstrumentSpec | None) -> dict[str, Any]:
        return {
            "limits": limits.as_json(),
            "equity": str(context.equity),
            "peak_equity": str(context.peak_equity),
            "day_realized_pnl": str(context.day_realized_pnl),
            "open_orders": context.open_order_count,
            "stale_seconds": context.stale_seconds,
            "data_complete": context.data_complete,
            "kill_switch_armed": limits.kill_switch_armed or context.kill_switch_armed,
            "instrument_id": spec.instrument_id if spec else None,
        }


def sanitize_model_risk_payload(payload: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    """Strip override-looking keys from anything a model produced.

    Used at the boundary where an agent proposal becomes an :class:`OrderIntent`. The keys are
    not silently dropped: they are returned so the run log can record the attempt.
    """
    clean: dict[str, Any] = {}
    stripped: list[str] = []
    for key, value in (payload or {}).items():
        if key in OVERRIDE_KEYS or key.startswith("risk_"):
            stripped.append(key)
            continue
        clean[key] = value
    return clean, stripped


def correlation_groups_from_specs(specs: Iterable[InstrumentSpec]) -> dict[str, str]:
    """Group instruments that obviously share a risk driver.

    Deliberately crude and transparent: same family plus same quote currency, and options or
    futures inherit their underlying's group. It is a concentration guard, not a factor model.
    """
    groups: dict[str, str] = {}
    for spec in specs:
        underlying = None
        if spec.option_terms:
            underlying = spec.option_terms.underlying_instrument_id
        elif spec.future_terms and spec.future_terms.underlying_instrument_id:
            underlying = spec.future_terms.underlying_instrument_id
        if underlying:
            groups[spec.instrument_id] = f"underlying:{underlying}"
        else:
            groups[spec.instrument_id] = f"{spec.family}:{spec.quote_currency.upper()}"
    return groups


__all__ = [
    "ENGINE_VERSION",
    "OVERRIDE_KEYS",
    "RiskContext",
    "RiskEngine",
    "correlation_groups_from_specs",
    "sanitize_model_risk_payload",
]
