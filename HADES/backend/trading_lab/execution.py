"""Exchange / broker simulator.

This module is the **only** writer of fills. A strategy or an agent submits an
:class:`OrderIntent` that carries no price guarantee; this layer decides whether, when, how
much and at what price it fills, and what it costs.

Candle-only reality modelling, stated explicitly because it is where backtests lie:

- An order becomes eligible on the first event **after** the observation that produced it.
  The signal-on-close/fill-on-the-same-close shortcut is structurally impossible here.
- Within one candle the path is unknown. When both a stop and a target are inside the same
  candle, the conservative rule takes the stop and marks the fill ``intrabar_ambiguous``.
  The alternative — picking the favourable order — is inventing a path.
- Fill size is capped by a participation fraction of the candle's volume, which produces
  genuine partial fills instead of unlimited liquidity.
- ``modelled_slippage_bps`` records what the model charged. ``observed_execution`` stays
  ``False`` for every simulated fill, so a report can never present modelled cost as
  measured cost.
- Historical replay does not pretend our own orders moved the market. Participation capping
  limits how much we may take; it does not rewrite the candle.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal
from typing import Any, Iterable, Literal

from trading_lab.calendars import get_calendar
from trading_lab.capabilities import validate_order_capability
from trading_lab.contracts import (
    CostModel,
    FillEvent,
    InstrumentSpec,
    MarketEvent,
    OrderEvent,
    OrderIntent,
    OrderSide,
    quantize_step,
    to_decimal,
    utc_iso,
)

ZERO = Decimal("0")
BPS = Decimal("10000")

OrderStatus = Literal[
    "pending_eligibility",
    "working",
    "partially_filled",
    "filled",
    "cancelled",
    "rejected",
    "expired",
]


def deterministic_event_id(*parts: Any) -> str:
    """Stable id derived from content, so a replay produces the same event ids.

    Idempotency in the ledger is keyed on these ids: replaying the same run cannot book a
    second copy of the same fill.
    """
    blob = "|".join(str(part) for part in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


@dataclass
class WorkingOrder:
    order_id: str
    intent: OrderIntent
    spec: InstrumentSpec
    status: OrderStatus = "pending_eligibility"
    remaining: Decimal = ZERO
    filled: Decimal = ZERO
    notional_filled: Decimal = ZERO
    eligible_from: str = ""
    expires_at: str | None = None
    triggered: bool = False
    trail_anchor: Decimal | None = None
    effective_stop: Decimal | None = None
    oco_group: str | None = None
    parent_order_id: str | None = None
    created_event_time: str = ""
    fills: int = 0
    reject_reason: str = ""

    @property
    def average_fill_price(self) -> Decimal | None:
        if self.filled <= 0:
            return None
        return self.notional_filled / self.filled

    def as_record(self, run_id: str) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "run_id": run_id,
            "instrument_id": self.spec.instrument_id,
            "strategy_id": self.intent.strategy_id,
            "side": self.intent.side,
            "order_type": self.intent.order_type,
            "time_in_force": self.intent.time_in_force,
            "status": self.status,
            "quantity": str(self.intent.quantity),
            "filled_quantity": str(self.filled),
            "average_fill_price": None if self.average_fill_price is None else str(self.average_fill_price),
            "limit_price": None if self.intent.limit_price is None else str(self.intent.limit_price),
            "stop_price": None if self.effective_stop is None else str(self.effective_stop),
            "reduce_only": self.intent.reduce_only,
            "post_only": self.intent.post_only,
            "parent_order_id": self.parent_order_id,
            "oco_group": self.oco_group,
            "intent": self.intent.as_json(),
            "price_source": self.intent.price_source,
            "created_event_time": self.created_event_time,
            "eligible_from_event_time": self.eligible_from,
            "expires_at_event_time": self.expires_at,
            "reject_reason": self.reject_reason,
        }


@dataclass
class ExecutionOutcome:
    order_events: list[OrderEvent] = field(default_factory=list)
    fills: list[FillEvent] = field(default_factory=list)
    touched_orders: list[WorkingOrder] = field(default_factory=list)

    def extend(self, other: "ExecutionOutcome") -> None:
        self.order_events.extend(other.order_events)
        self.fills.extend(other.fills)
        self.touched_orders.extend(other.touched_orders)


class ExchangeSimulator:
    """Order book free simulator driven by closed market events."""

    def __init__(
        self,
        *,
        cost_model: CostModel,
        available_data_levels: Iterable[str] = ("ohlcv",),
        deterministic_rejects: bool = True,
    ) -> None:
        self.cost_model = cost_model
        self.available_data_levels = tuple(available_data_levels)
        self.deterministic_rejects = deterministic_rejects
        self.orders: dict[str, WorkingOrder] = {}
        self._oco_groups: dict[str, set[str]] = {}
        self._sequence = 0

    # --- submission --------------------------------------------------------------

    def submit(
        self,
        intent: OrderIntent,
        spec: InstrumentSpec,
        *,
        eligible_from: str,
        now: str,
        position_quantity: Decimal = ZERO,
    ) -> ExecutionOutcome:
        outcome = ExecutionOutcome()
        order_id = f"ord_{deterministic_event_id(intent.intent_id, spec.instrument_id, now)[:20]}"
        order = WorkingOrder(
            order_id=order_id,
            intent=intent,
            spec=spec,
            remaining=intent.quantity,
            eligible_from=eligible_from,
            created_event_time=now,
        )
        self.orders[order_id] = order
        outcome.touched_orders.append(order)

        ok, reason = validate_order_capability(spec, intent, available_data_levels=self.available_data_levels)
        if not ok:
            return self._reject(order, reason, now, outcome)

        rounded = quantize_step(intent.quantity, spec.lot_size, rounding=ROUND_DOWN)
        if rounded <= 0:
            return self._reject(order, f"quantity_below_lot_size:{spec.lot_size}", now, outcome)
        order.remaining = rounded

        if intent.reduce_only:
            if position_quantity == 0:
                return self._reject(order, "reduce_only_with_no_position", now, outcome)
            if (position_quantity > 0 and intent.side != "sell") or (
                position_quantity < 0 and intent.side != "buy"
            ):
                return self._reject(order, "reduce_only_would_increase_exposure", now, outcome)
            order.remaining = min(order.remaining, abs(position_quantity))

        for price in (intent.limit_price, intent.stop_price, intent.take_profit_price, intent.stop_loss_price):
            if price is None:
                continue
            try:
                spec.validate_price(price)
            except ValueError as exc:
                return self._reject(order, str(exc), now, outcome)

        if intent.order_type == "trailing_stop":
            order.trail_anchor = None
            order.effective_stop = None
        elif intent.order_type in {"stop_market", "stop_limit"}:
            order.effective_stop = intent.stop_price

        if intent.time_in_force == "DAY":
            calendar = get_calendar(spec.calendar)
            order.expires_at = utc_iso(calendar.session_end_utc(datetime.fromisoformat(eligible_from)))

        order.status = "pending_eligibility"
        outcome.order_events.append(
            self._event(order, "accepted", now, reason=f"eligible_from={eligible_from}")
        )

        if intent.order_type == "bracket":
            outcome.extend(self._register_bracket(order, spec, eligible_from, now))
        return outcome

    def cancel(self, order_id: str, now: str, *, reason: str = "cancelled_by_operator") -> ExecutionOutcome:
        outcome = ExecutionOutcome()
        order = self.orders.get(order_id)
        if order is None or order.status in {"filled", "cancelled", "rejected", "expired"}:
            return outcome
        order.status = "cancelled"
        order.reject_reason = reason
        outcome.order_events.append(self._event(order, "cancelled", now, reason=reason))
        outcome.touched_orders.append(order)
        return outcome

    def cancel_all(self, now: str, *, reason: str, instrument_id: str | None = None) -> ExecutionOutcome:
        outcome = ExecutionOutcome()
        for order_id, order in list(self.orders.items()):
            if instrument_id and order.spec.instrument_id != instrument_id:
                continue
            if order.status in {"filled", "cancelled", "rejected", "expired"}:
                continue
            outcome.extend(self.cancel(order_id, now, reason=reason))
        return outcome

    def open_orders(self, instrument_id: str | None = None) -> list[WorkingOrder]:
        return [
            order
            for order in self.orders.values()
            if order.status in {"pending_eligibility", "working", "partially_filled"}
            and (instrument_id is None or order.spec.instrument_id == instrument_id)
        ]

    # --- event processing --------------------------------------------------------

    def process_event(
        self,
        event: MarketEvent,
        *,
        position_quantities: dict[str, Decimal] | None = None,
    ) -> ExecutionOutcome:
        """Match every eligible resting order against one closed market event."""
        outcome = ExecutionOutcome()
        positions = dict(position_quantities or {})
        for order in list(self.orders.values()):
            if order.spec.instrument_id != event.instrument_id:
                continue
            if order.status in {"filled", "cancelled", "rejected", "expired"}:
                continue
            if event.available_at <= order.eligible_from:
                continue
            if order.expires_at and event.event_time >= order.expires_at:
                order.status = "expired"
                outcome.order_events.append(
                    self._event(order, "expired", event.event_time, reason=f"time_in_force={order.intent.time_in_force}")
                )
                outcome.touched_orders.append(order)
                continue
            if order.status == "pending_eligibility":
                order.status = "working"
                outcome.order_events.append(self._event(order, "working", event.event_time))
            if order.intent.reduce_only:
                held = positions.get(order.spec.instrument_id, ZERO)
                if held == 0 or (held > 0 and order.intent.side != "sell") or (
                    held < 0 and order.intent.side != "buy"
                ):
                    order.status = "cancelled"
                    order.reject_reason = "reduce_only_position_closed"
                    outcome.order_events.append(
                        self._event(order, "cancelled", event.event_time, reason="reduce_only_position_closed")
                    )
                    outcome.touched_orders.append(order)
                    continue
                order.remaining = min(order.remaining, abs(held))
            outcome.extend(self._match(order, event))
            if order.intent.time_in_force == "IOC" and order.status in {"working", "partially_filled"}:
                order.status = "cancelled"
                order.reject_reason = "ioc_remainder_cancelled"
                outcome.order_events.append(
                    self._event(order, "cancelled", event.event_time, reason="ioc_remainder_cancelled")
                )
            outcome.touched_orders.append(order)
        outcome.extend(self._settle_oco(outcome, event))
        return outcome

    def _match(self, order: WorkingOrder, event: MarketEvent) -> ExecutionOutcome:
        outcome = ExecutionOutcome()
        intent = order.intent
        spec = order.spec
        if intent.order_type == "trailing_stop":
            outcome.extend(self._advance_trailing(order, event))
            if not order.triggered:
                return outcome
        if intent.order_type in {"stop_market", "stop_limit"} and not order.triggered:
            triggered, trigger_price = self._stop_triggered(order, event)
            if not triggered:
                return outcome
            order.triggered = True
            outcome.order_events.append(
                self._event(order, "triggered", event.event_time, reason=f"stop={trigger_price}")
            )

        if self._rejected_by_venue(order, event):
            order.status = "rejected"
            order.reject_reason = "venue_reject_modelled"
            outcome.order_events.append(
                self._event(
                    order,
                    "rejected",
                    event.event_time,
                    reason=f"modelled venue reject (probability {self.cost_model.reject_probability})",
                )
            )
            return outcome

        if intent.order_type == "market" or (intent.order_type == "stop_market" and order.triggered):
            fill = self._fill_market(order, event)
        elif intent.order_type in {"limit", "take_profit"} or (
            intent.order_type == "stop_limit" and order.triggered
        ):
            fill = self._fill_limit(order, event)
        elif intent.order_type == "trailing_stop":
            fill = self._fill_market(order, event)
        elif intent.order_type == "bracket":
            return outcome  # children do the work
        else:
            fill = None

        if fill is None:
            return outcome

        quantity, price, liquidity, ambiguous, note = fill
        quantity = quantize_step(quantity, spec.lot_size, rounding=ROUND_DOWN)
        if quantity <= 0:
            return outcome
        if intent.time_in_force == "FOK" and quantity < order.remaining:
            order.status = "cancelled"
            order.reject_reason = "fok_insufficient_liquidity"
            outcome.order_events.append(
                self._event(order, "cancelled", event.event_time, reason="fok_insufficient_liquidity")
            )
            return outcome

        price = quantize_step(price, spec.tick_size, rounding=ROUND_HALF_EVEN)
        try:
            spec.validate_price(price)
        except ValueError as exc:
            order.status = "rejected"
            order.reject_reason = str(exc)
            outcome.order_events.append(self._event(order, "rejected", event.event_time, reason=str(exc)))
            return outcome

        fee = self._fee(order, quantity, price, liquidity)
        self._sequence += 1
        fill_event = FillEvent(
            event_id=deterministic_event_id(order.order_id, event.event_time, order.fills, quantity, price),
            order_id=order.order_id,
            instrument_id=spec.instrument_id,
            event_time=event.event_time,
            side=intent.side,
            quantity=quantity,
            price=price,
            fee=fee,
            fee_currency=spec.settle_currency,
            liquidity=liquidity,
            intrabar_ambiguous=ambiguous,
            modelled_slippage_bps=self.cost_model.slippage_bps if liquidity == "taker" else ZERO,
            observed_execution=False,
            metadata={
                "note": note,
                "event_volume": event.volume,
                "participation_cap": str(self.cost_model.max_volume_participation),
                "data_level": "ohlcv",
                "cost_basis": "modelled — not an observed execution",
            },
        )
        order.fills += 1
        order.filled += quantity
        order.notional_filled += quantity * price
        order.remaining -= quantity
        order.status = "filled" if order.remaining <= 0 else "partially_filled"
        outcome.fills.append(fill_event)
        outcome.order_events.append(
            self._event(
                order,
                "filled" if order.status == "filled" else "partially_filled",
                event.event_time,
                reason=note,
            )
        )
        return outcome

    # --- fill rules --------------------------------------------------------------

    def _fill_market(
        self, order: WorkingOrder, event: MarketEvent
    ) -> tuple[Decimal, Decimal, str, bool, str] | None:
        reference = to_decimal(event.open if event.open is not None else event.reference_price)
        if order.intent.order_type == "stop_market" and order.effective_stop is not None:
            reference = self._gap_aware_stop_price(order, event, reference)
        if order.intent.order_type == "trailing_stop" and order.effective_stop is not None:
            reference = self._gap_aware_stop_price(order, event, reference)
        price = self._apply_costs(order.intent.side, reference)
        quantity, capped = self._participation_limit(order, event)
        if quantity <= 0:
            return None
        note = "market fill at event open with modelled half-spread and slippage"
        if capped:
            note += "; size capped by volume participation (partial fill)"
        return quantity, price, "taker", False, note

    def _fill_limit(
        self, order: WorkingOrder, event: MarketEvent
    ) -> tuple[Decimal, Decimal, str, bool, str] | None:
        limit = order.intent.limit_price
        if limit is None:
            return None
        high = to_decimal(event.high if event.high is not None else event.reference_price)
        low = to_decimal(event.low if event.low is not None else event.reference_price)
        open_price = to_decimal(event.open if event.open is not None else event.reference_price)
        side = order.intent.side
        if order.intent.post_only:
            crosses = (side == "buy" and open_price <= limit) or (side == "sell" and open_price >= limit)
            if crosses:
                order.status = "cancelled"
                order.reject_reason = "post_only_would_cross"
                return None
        reachable = (side == "buy" and low <= limit) or (side == "sell" and high >= limit)
        if not reachable:
            return None
        # Conservative: a resting limit never fills better than its own price, even when the
        # candle opened through it. Assuming the best price inside the candle is inventing a path.
        price = limit
        if side == "buy" and open_price < limit:
            price = limit
        if side == "sell" and open_price > limit:
            price = limit
        quantity, capped = self._participation_limit(order, event)
        if quantity <= 0:
            return None
        liquidity = "maker" if not order.triggered else "taker"
        note = "limit fill at the limit price after the candle traded through it"
        if capped:
            note += "; size capped by volume participation (partial fill)"
        return quantity, price, liquidity, False, note

    def _stop_triggered(self, order: WorkingOrder, event: MarketEvent) -> tuple[bool, Decimal | None]:
        stop = order.effective_stop if order.effective_stop is not None else order.intent.stop_price
        if stop is None:
            return False, None
        high = to_decimal(event.high if event.high is not None else event.reference_price)
        low = to_decimal(event.low if event.low is not None else event.reference_price)
        if order.intent.side == "buy":
            return (high >= stop, stop)
        return (low <= stop, stop)

    def _gap_aware_stop_price(
        self, order: WorkingOrder, event: MarketEvent, reference: Decimal
    ) -> Decimal:
        """A stop does not fill at the stop when the market gapped past it."""
        stop = order.effective_stop if order.effective_stop is not None else order.intent.stop_price
        if stop is None:
            return reference
        if order.intent.side == "buy":
            return max(stop, reference)
        return min(stop, reference)

    def _advance_trailing(self, order: WorkingOrder, event: MarketEvent) -> ExecutionOutcome:
        """Update the trail on closed events only; intrabar trailing needs finer data."""
        outcome = ExecutionOutcome()
        offset = order.intent.trail_offset or ZERO
        close = to_decimal(event.close if event.close is not None else event.reference_price)
        if order.intent.side == "sell":
            anchor = close if order.trail_anchor is None else max(order.trail_anchor, close)
            order.trail_anchor = anchor
            order.effective_stop = anchor - offset
            low = to_decimal(event.low if event.low is not None else close)
            if order.effective_stop is not None and low <= order.effective_stop:
                order.triggered = True
        else:
            anchor = close if order.trail_anchor is None else min(order.trail_anchor, close)
            order.trail_anchor = anchor
            order.effective_stop = anchor + offset
            high = to_decimal(event.high if event.high is not None else close)
            if order.effective_stop is not None and high >= order.effective_stop:
                order.triggered = True
        if order.triggered:
            outcome.order_events.append(
                self._event(
                    order,
                    "triggered",
                    event.event_time,
                    reason=f"trailing stop {order.effective_stop} reached (anchor {order.trail_anchor})",
                )
            )
        return outcome

    def _participation_limit(self, order: WorkingOrder, event: MarketEvent) -> tuple[Decimal, bool]:
        volume = to_decimal(event.volume or 0)
        if volume <= 0:
            # No volume information: fill the full remainder but say so in the fill note.
            return order.remaining, False
        allowance = volume * self.cost_model.max_volume_participation
        if allowance >= order.remaining:
            return order.remaining, False
        return allowance, True

    def _apply_costs(self, side: OrderSide, reference: Decimal) -> Decimal:
        half_spread = abs(reference) * self.cost_model.half_spread_bps / BPS
        slippage = abs(reference) * self.cost_model.slippage_bps / BPS
        if side == "buy":
            return reference + half_spread + slippage
        return reference - half_spread - slippage

    def _fee(self, order: WorkingOrder, quantity: Decimal, price: Decimal, liquidity: str) -> Decimal:
        rate = self.cost_model.maker_fee_bps if liquidity == "maker" else self.cost_model.taker_fee_bps
        notional = abs(quantity) * abs(price) * order.spec.multiplier
        fee = notional * rate / BPS
        return max(fee, self.cost_model.min_fee) if notional > 0 else ZERO

    def _rejected_by_venue(self, order: WorkingOrder, event: MarketEvent) -> bool:
        if self.cost_model.reject_probability <= 0:
            return False
        if not self.deterministic_rejects:
            return False
        # Deterministic pseudo-random draw from content, so the same run rejects the same orders.
        digest = deterministic_event_id(order.order_id, event.event_time, "reject")
        draw = Decimal(int(digest[:8], 16)) / Decimal(0xFFFFFFFF)
        return draw < self.cost_model.reject_probability

    # --- bracket / OCO -----------------------------------------------------------

    def _register_bracket(
        self, parent: WorkingOrder, spec: InstrumentSpec, eligible_from: str, now: str
    ) -> ExecutionOutcome:
        outcome = ExecutionOutcome()
        group = f"oco_{parent.order_id}"
        exit_side: OrderSide = "sell" if parent.intent.side == "buy" else "buy"
        children: list[WorkingOrder] = []
        if parent.intent.take_profit_price is not None:
            children.append(
                self._child(
                    parent,
                    spec,
                    side=exit_side,
                    order_type="take_profit",
                    limit_price=parent.intent.take_profit_price,
                    stop_price=None,
                    eligible_from=eligible_from,
                    now=now,
                    group=group,
                    tag="take_profit",
                )
            )
        if parent.intent.stop_loss_price is not None:
            children.append(
                self._child(
                    parent,
                    spec,
                    side=exit_side,
                    order_type="stop_market",
                    limit_price=None,
                    stop_price=parent.intent.stop_loss_price,
                    eligible_from=eligible_from,
                    now=now,
                    group=group,
                    tag="stop_loss",
                )
            )
        if children:
            self._oco_groups[group] = {child.order_id for child in children}
            parent.oco_group = group
        for child in children:
            outcome.order_events.append(
                self._event(child, "accepted", now, reason=f"bracket child of {parent.order_id}")
            )
            outcome.touched_orders.append(child)
        parent.status = "working"
        return outcome

    def _child(
        self,
        parent: WorkingOrder,
        spec: InstrumentSpec,
        *,
        side: OrderSide,
        order_type: str,
        limit_price: Decimal | None,
        stop_price: Decimal | None,
        eligible_from: str,
        now: str,
        group: str,
        tag: str,
    ) -> WorkingOrder:
        intent = OrderIntent(
            intent_id=f"{parent.intent.intent_id}:{tag}",
            instrument_id=spec.instrument_id,
            side=side,
            order_type=order_type,  # type: ignore[arg-type]
            quantity=parent.intent.quantity,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=parent.intent.time_in_force,
            reduce_only=True,
            strategy_id=parent.intent.strategy_id,
            strategy_version=parent.intent.strategy_version,
            rationale=f"{tag} leg of bracket {parent.order_id}",
            created_at_event_time=now,
            price_source=parent.intent.price_source,
        )
        order_id = f"ord_{deterministic_event_id(intent.intent_id, spec.instrument_id, now)[:20]}"
        child = WorkingOrder(
            order_id=order_id,
            intent=intent,
            spec=spec,
            remaining=parent.intent.quantity,
            eligible_from=eligible_from,
            created_event_time=now,
            oco_group=group,
            parent_order_id=parent.order_id,
            effective_stop=stop_price,
            status="pending_eligibility",
        )
        self.orders[order_id] = child
        return child

    def _settle_oco(self, outcome: ExecutionOutcome, event: MarketEvent) -> ExecutionOutcome:
        """One-cancels-other plus the intrabar ambiguity rule."""
        extra = ExecutionOutcome()
        for group, members in list(self._oco_groups.items()):
            orders = [self.orders[order_id] for order_id in members if order_id in self.orders]
            if not orders:
                continue
            filled_this_event = [
                order
                for order in orders
                if order.status in {"filled", "partially_filled"}
                and any(fill.order_id == order.order_id and fill.event_time == event.event_time for fill in outcome.fills)
            ]
            if len(filled_this_event) > 1:
                # Stop and target both inside one candle: the conservative rule wins.
                adverse = next(
                    (order for order in filled_this_event if order.intent.order_type in {"stop_market", "stop_limit"}),
                    filled_this_event[0],
                )
                for order in filled_this_event:
                    if order.order_id == adverse.order_id:
                        continue
                    outcome.fills = [
                        fill
                        for fill in outcome.fills
                        if not (fill.order_id == order.order_id and fill.event_time == event.event_time)
                    ]
                    order.status = "cancelled"
                    order.filled = ZERO
                    order.notional_filled = ZERO
                    order.remaining = order.intent.quantity
                    order.reject_reason = "oco_conservative_rule_stop_assumed_first"
                    extra.order_events.append(
                        self._event(
                            order,
                            "cancelled",
                            event.event_time,
                            reason=(
                                "intrabar ambiguity: stop and target were both inside this candle; "
                                f"the {self.cost_model.intrabar_rule} rule assumes the stop executed first. "
                                "Use finer-grained data to resolve the true path."
                            ),
                        )
                    )
                for fill in outcome.fills:
                    if fill.order_id == adverse.order_id and fill.event_time == event.event_time:
                        fill.intrabar_ambiguous = True
                        fill.metadata["intrabar_rule"] = self.cost_model.intrabar_rule
            for order in orders:
                if order.status == "filled":
                    for sibling in orders:
                        if sibling.order_id == order.order_id:
                            continue
                        if sibling.status in {"pending_eligibility", "working", "partially_filled"}:
                            sibling.status = "cancelled"
                            sibling.reject_reason = "oco_sibling_filled"
                            extra.order_events.append(
                                self._event(sibling, "cancelled", event.event_time, reason="oco_sibling_filled")
                            )
                    self._oco_groups.pop(group, None)
                    break
        return extra

    # --- forced closes -----------------------------------------------------------

    def forced_fill(
        self,
        spec: InstrumentSpec,
        *,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        event_time: str,
        reason: str,
        liquidity: str = "settlement",
        strategy_id: str | None = None,
    ) -> tuple[WorkingOrder, OrderEvent, FillEvent]:
        """Settlement, delisting, maturity redemption and liquidation.

        These are not strategy decisions, so they bypass intent validation, but they are
        still written as a normal order plus fill so the audit trail stays complete.
        """
        intent = OrderIntent(
            intent_id=f"forced:{spec.instrument_id}:{event_time}:{reason[:32]}",
            instrument_id=spec.instrument_id,
            side=side,
            order_type="market",
            quantity=quantity,
            time_in_force="IOC",
            reduce_only=True,
            strategy_id=strategy_id,
            rationale=reason,
            created_at_event_time=event_time,
            price_source="risk_reduction",
        )
        order_id = f"ord_{deterministic_event_id(intent.intent_id, event_time)[:20]}"
        order = WorkingOrder(
            order_id=order_id,
            intent=intent,
            spec=spec,
            remaining=ZERO,
            filled=quantity,
            notional_filled=quantity * price,
            eligible_from=event_time,
            created_event_time=event_time,
            status="filled",
        )
        self.orders[order_id] = order
        event = self._event(order, "liquidated" if liquidity == "liquidation" else "filled", event_time, reason=reason)
        fill = FillEvent(
            event_id=deterministic_event_id(order_id, event_time, "forced", quantity, price),
            order_id=order_id,
            instrument_id=spec.instrument_id,
            event_time=event_time,
            side=side,
            quantity=quantity,
            price=quantize_step(price, spec.tick_size, rounding=ROUND_HALF_EVEN),
            fee=ZERO,
            fee_currency=spec.settle_currency,
            liquidity=liquidity,  # type: ignore[arg-type]
            observed_execution=False,
            metadata={"forced": True, "reason": reason},
        )
        return order, event, fill

    # --- helpers -----------------------------------------------------------------

    def _reject(
        self, order: WorkingOrder, reason: str, now: str, outcome: ExecutionOutcome
    ) -> ExecutionOutcome:
        order.status = "rejected"
        order.reject_reason = reason
        outcome.order_events.append(self._event(order, "rejected", now, reason=reason))
        return outcome

    def _event(self, order: WorkingOrder, kind: str, event_time: str, *, reason: str = "") -> OrderEvent:
        self._sequence += 1
        return OrderEvent(
            event_id=deterministic_event_id(order.order_id, kind, event_time, self._sequence),
            order_id=order.order_id,
            instrument_id=order.spec.instrument_id,
            event_time=event_time,
            kind=kind,  # type: ignore[arg-type]
            reason=reason,
            remaining_quantity=max(ZERO, order.remaining),
            metadata={"status": order.status, "order_type": order.intent.order_type},
        )

    def state(self) -> dict[str, Any]:
        return {
            "sequence": self._sequence,
            "oco_groups": {group: sorted(members) for group, members in self._oco_groups.items()},
            "orders": [
                {
                    "order_id": order.order_id,
                    "intent": order.intent.as_json(),
                    "status": order.status,
                    "remaining": str(order.remaining),
                    "filled": str(order.filled),
                    "notional_filled": str(order.notional_filled),
                    "eligible_from": order.eligible_from,
                    "expires_at": order.expires_at,
                    "triggered": order.triggered,
                    "trail_anchor": None if order.trail_anchor is None else str(order.trail_anchor),
                    "effective_stop": None if order.effective_stop is None else str(order.effective_stop),
                    "oco_group": order.oco_group,
                    "parent_order_id": order.parent_order_id,
                    "created_event_time": order.created_event_time,
                    "fills": order.fills,
                    "reject_reason": order.reject_reason,
                }
                for order in self.orders.values()
            ],
        }

    def restore(self, state: dict[str, Any], specs: dict[str, InstrumentSpec]) -> None:
        self._sequence = int(state.get("sequence", 0))
        self._oco_groups = {group: set(members) for group, members in (state.get("oco_groups") or {}).items()}
        for payload in state.get("orders") or []:
            intent = OrderIntent.model_validate(payload["intent"])
            spec = specs.get(intent.instrument_id)
            if spec is None:
                continue
            order = WorkingOrder(
                order_id=payload["order_id"],
                intent=intent,
                spec=spec,
                status=payload.get("status", "working"),
                remaining=to_decimal(payload.get("remaining", "0")),
                filled=to_decimal(payload.get("filled", "0")),
                notional_filled=to_decimal(payload.get("notional_filled", "0")),
                eligible_from=payload.get("eligible_from", ""),
                expires_at=payload.get("expires_at"),
                triggered=bool(payload.get("triggered")),
                trail_anchor=None if payload.get("trail_anchor") is None else to_decimal(payload["trail_anchor"]),
                effective_stop=None if payload.get("effective_stop") is None else to_decimal(payload["effective_stop"]),
                oco_group=payload.get("oco_group"),
                parent_order_id=payload.get("parent_order_id"),
                created_event_time=payload.get("created_event_time", ""),
                fills=int(payload.get("fills", 0)),
                reject_reason=payload.get("reject_reason", ""),
            )
            self.orders[order.order_id] = order


__all__ = [
    "ExchangeSimulator",
    "ExecutionOutcome",
    "OrderStatus",
    "WorkingOrder",
    "deterministic_event_id",
]
