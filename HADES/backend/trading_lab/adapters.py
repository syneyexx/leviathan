"""Instrument-family accounting and lifecycle adapters.

Each family differs in ways that change the books, not just the label. A simulator that
treats an option like a share, or a future like spot, produces confidently wrong numbers.
These adapters own those differences:

- equity/ETF: splits, dividends, delisting, borrow availability, short borrow cost
- future: contract multiplier, expiry settlement, margin, roll warning, negative prices
- perpetual: funding, mark/index price, liquidation
- option: expiry, strike, multiplier, Greeks, exercise, assignment, leg risk
- forex: base/quote conversion, session hours, rollover financing
- CFD: broker contract spec, dealer spread, overnight financing, margin
- bond: coupon, accrued interest, clean/dirty price, redemption at maturity
- crypto spot: two-currency wallet, minimum notional, no shorting
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from trading_lab.accounting import Portfolio, Position, SettlementStyle, ZERO
from trading_lab.contracts import (
    FillEvent,
    InstrumentSpec,
    MarketEvent,
    OrderIntent,
    to_decimal,
)

DAYS_PER_YEAR = Decimal("365")


@dataclass
class CashFlow:
    kind: str
    currency: str
    amount: Decimal
    memo: str = ""
    suffix: str = ""


@dataclass
class LifecycleAction:
    kind: str  # settle_expiry | force_close_delisted | redeem_maturity | liquidate
    reason: str
    price: Decimal | None = None
    quantity: Decimal | None = None
    cash_flows: list[CashFlow] = field(default_factory=list)


class InstrumentAdapter:
    """Base adapter. Defaults describe a fully funded, non-accruing instrument."""

    settlement_style: SettlementStyle = "funded"
    family = "generic"

    # --- trade booking -----------------------------------------------------------

    def cash_notional(self, spec: InstrumentSpec, fill: FillEvent) -> Decimal | None:
        """Exchanged cash for a fill. ``None`` means "signed quantity x price x multiplier"."""
        return None

    def accrued_interest(self, spec: InstrumentSpec, fill: FillEvent) -> Decimal:
        return ZERO

    def margin_requirement(self, spec: InstrumentSpec, position: Position, mark: Decimal) -> Decimal:
        if self.settlement_style == "funded":
            if position.signed_quantity < 0:
                return abs(position.signed_quantity) * abs(mark) * spec.multiplier * spec.initial_margin_rate
            return ZERO
        return abs(position.signed_quantity) * abs(mark) * spec.multiplier * spec.initial_margin_rate

    def maintenance_margin(self, spec: InstrumentSpec, position: Position, mark: Decimal) -> Decimal:
        return abs(position.signed_quantity) * abs(mark) * spec.multiplier * spec.maintenance_margin_rate

    def order_notional(self, spec: InstrumentSpec, quantity: Decimal, price: Decimal) -> Decimal:
        return abs(quantity) * abs(price) * spec.multiplier

    # --- validation --------------------------------------------------------------

    def validate_intent(
        self,
        spec: InstrumentSpec,
        intent: OrderIntent,
        position: Position | None,
    ) -> tuple[bool, str]:
        if intent.reduce_only:
            held = position.signed_quantity if position else ZERO
            if held == 0:
                return False, "reduce_only_with_no_position"
            if (held > 0 and intent.side != "sell") or (held < 0 and intent.side != "buy"):
                return False, "reduce_only_would_increase_exposure"
            if intent.quantity > abs(held):
                return False, "reduce_only_quantity_exceeds_position"
        return True, "ok"

    # --- lifecycle ---------------------------------------------------------------

    def periodic_accruals(
        self,
        spec: InstrumentSpec,
        position: Position,
        event: MarketEvent,
        *,
        previous_event_time: str | None,
    ) -> list[CashFlow]:
        return []

    def lifecycle(
        self,
        spec: InstrumentSpec,
        position: Position,
        event: MarketEvent,
    ) -> list[LifecycleAction]:
        return []

    def apply_corporate_action(
        self,
        spec: InstrumentSpec,
        portfolio: Portfolio,
        action: dict[str, Any],
        event_time: str,
        *,
        event_id: str,
    ) -> list[CashFlow]:
        return []

    def risk_metrics(self, spec: InstrumentSpec, position: Position, event: MarketEvent) -> dict[str, Any]:
        return {}


class SpotAdapter(InstrumentAdapter):
    family = "crypto_spot"
    settlement_style = "funded"

    def validate_intent(self, spec, intent, position):
        ok, reason = super().validate_intent(spec, intent, position)
        if not ok:
            return ok, reason
        if intent.side == "sell":
            held = position.signed_quantity if position else ZERO
            if held <= 0:
                return False, "spot_wallet_cannot_go_short"
            if intent.quantity > held:
                return False, "spot_sell_exceeds_held_quantity"
        return True, "ok"

    def margin_requirement(self, spec, position, mark):
        return ZERO


class EquityAdapter(InstrumentAdapter):
    family = "equity"
    settlement_style = "funded"

    def validate_intent(self, spec, intent, position):
        ok, reason = super().validate_intent(spec, intent, position)
        if not ok:
            return ok, reason
        held = position.signed_quantity if position else ZERO
        opening_short = intent.side == "sell" and (held - intent.quantity) < 0
        if opening_short and not intent.reduce_only:
            if not spec.shorting_allowed:
                return False, "short_not_allowed_for_instrument"
            if not spec.borrow_available:
                return False, "no_borrow_availability_for_short"
        return True, "ok"

    def periodic_accruals(self, spec, position, event, *, previous_event_time):
        if position.signed_quantity >= 0 or spec.borrow_fee_annual <= 0:
            return []
        days = _elapsed_days(previous_event_time, event.event_time)
        if days <= 0:
            return []
        mark = to_decimal(event.reference_price)
        notional = abs(position.signed_quantity) * abs(mark) * spec.multiplier
        amount = notional * spec.borrow_fee_annual * days / DAYS_PER_YEAR
        if amount == 0:
            return []
        return [
            CashFlow(
                kind="borrow_fee",
                currency=spec.settle_currency,
                amount=-amount,
                memo=f"short borrow {spec.borrow_fee_annual} annual over {days} day(s)",
                suffix="borrow",
            )
        ]

    def lifecycle(self, spec, position, event):
        if not spec.delisted_at or position.is_flat:
            return []
        delisted = _parse(spec.delisted_at)
        if delisted is None or _parse(event.event_time) < delisted:
            return []
        return [
            LifecycleAction(
                kind="force_close_delisted",
                reason=f"instrument_delisted_at:{spec.delisted_at}",
                price=to_decimal(event.reference_price),
                quantity=abs(position.signed_quantity),
            )
        ]

    def apply_corporate_action(self, spec, portfolio, action, event_time, *, event_id):
        kind = str(action.get("kind") or action.get("type") or "").lower()
        position = portfolio.position(spec.instrument_id)
        if position is None or position.is_flat:
            return []
        if kind in {"split", "reverse_split"}:
            ratio = to_decimal(action.get("ratio", 1))
            if ratio <= 0:
                raise ValueError("split_ratio_must_be_positive")
            portfolio.adjust_position_for_corporate_action(
                spec.instrument_id,
                quantity_factor=ratio,
                price_factor=Decimal("1") / ratio,
            )
            return []
        if kind in {"dividend", "distribution"}:
            per_share = to_decimal(action.get("amount", 0))
            if per_share == 0:
                return []
            amount = per_share * position.signed_quantity * spec.multiplier
            return [
                CashFlow(
                    kind="dividend",
                    currency=spec.settle_currency,
                    amount=amount,
                    memo=f"{kind} {per_share} per unit on {position.signed_quantity}",
                    suffix="dividend",
                )
            ]
        return []


class ForexAdapter(InstrumentAdapter):
    family = "forex"
    settlement_style = "margin"

    def periodic_accruals(self, spec, position, event, *, previous_event_time):
        if position.is_flat or spec.financing_spread_annual <= 0:
            return []
        days = _elapsed_days(previous_event_time, event.event_time)
        if days <= 0:
            return []
        notional = abs(position.signed_quantity) * abs(to_decimal(event.reference_price)) * spec.multiplier
        amount = notional * spec.financing_spread_annual * days / DAYS_PER_YEAR
        return [
            CashFlow(
                kind="financing",
                currency=spec.settle_currency,
                amount=-amount,
                memo=f"rollover financing over {days} day(s)",
                suffix="financing",
            )
        ]


class FutureAdapter(InstrumentAdapter):
    family = "future"
    settlement_style = "margin"

    def lifecycle(self, spec, position, event):
        terms = spec.future_terms
        if terms is None or position.is_flat:
            return []
        expiry = _parse(terms.expiry)
        now = _parse(event.event_time)
        if expiry is None or now is None:
            return []
        actions: list[LifecycleAction] = []
        if now >= expiry:
            actions.append(
                LifecycleAction(
                    kind="settle_expiry",
                    reason=f"future_expired:{terms.expiry} settlement={terms.settlement}",
                    price=to_decimal(event.reference_price),
                    quantity=abs(position.signed_quantity),
                )
            )
        elif now >= expiry - timedelta(days=terms.roll_days_before_expiry):
            actions.append(
                LifecycleAction(
                    kind="roll_window",
                    reason=(
                        f"roll_window_open: expiry {terms.expiry} in "
                        f"<= {terms.roll_days_before_expiry} day(s); no continuous-contract dataset is assumed"
                    ),
                )
            )
        return actions

    def risk_metrics(self, spec, position, event):
        return {
            "contract_multiplier": str(spec.multiplier),
            "notional": str(position.notional()),
            "expiry": spec.future_terms.expiry if spec.future_terms else None,
            "price_can_be_negative": spec.price_can_be_negative,
        }


class PerpetualAdapter(InstrumentAdapter):
    family = "crypto_perpetual"
    settlement_style = "margin"

    def periodic_accruals(self, spec, position, event, *, previous_event_time):
        if position.is_flat:
            return []
        if event.funding_rate is None:
            return []
        interval = spec.funding_interval_hours or 8
        now = _parse(event.event_time)
        if now is None:
            return []
        # Funding is charged on interval boundaries only, not on every bar.
        if (now.hour % interval) != 0 or now.minute != 0:
            return []
        if previous_event_time is not None:
            previous = _parse(previous_event_time)
            if previous is not None and previous.replace(minute=0, second=0, microsecond=0) == now.replace(
                minute=0, second=0, microsecond=0
            ):
                return []
        mark = to_decimal(event.mark_price if event.mark_price is not None else event.reference_price)
        notional = position.signed_quantity * mark * spec.multiplier
        rate = to_decimal(event.funding_rate)
        amount = -(notional * rate)
        if amount == 0:
            return []
        return [
            CashFlow(
                kind="funding",
                currency=spec.settle_currency,
                amount=amount,
                memo=f"funding rate {rate} on signed notional {notional}",
                suffix=f"funding-{now.isoformat()}",
            )
        ]

    def lifecycle(self, spec, position, event):
        if position.is_flat:
            return []
        mark = to_decimal(event.mark_price if event.mark_price is not None else event.reference_price)
        maintenance = self.maintenance_margin(spec, position, mark)
        equity_backing = position.margin_used + position.unrealized_pnl()
        if maintenance > 0 and equity_backing < maintenance:
            return [
                LifecycleAction(
                    kind="liquidate",
                    reason=(
                        f"maintenance_margin_breach: backing={equity_backing} < required={maintenance} "
                        f"at mark {mark}"
                    ),
                    price=mark,
                    quantity=abs(position.signed_quantity),
                )
            ]
        return []

    def risk_metrics(self, spec, position, event):
        mark = event.mark_price if event.mark_price is not None else event.close
        return {
            "mark_price": None if mark is None else str(mark),
            "index_price": None if event.index_price is None else str(event.index_price),
            "funding_rate": None if event.funding_rate is None else str(event.funding_rate),
            "funding_interval_hours": spec.funding_interval_hours,
            "funding_data_available": event.funding_rate is not None,
            "maintenance_margin": str(
                self.maintenance_margin(spec, position, to_decimal(mark)) if mark is not None else ZERO
            ),
        }


class CfdAdapter(InstrumentAdapter):
    family = "cfd"
    settlement_style = "margin"

    def periodic_accruals(self, spec, position, event, *, previous_event_time):
        if position.is_flat or spec.financing_spread_annual <= 0:
            return []
        days = _elapsed_days(previous_event_time, event.event_time)
        if days <= 0:
            return []
        notional = abs(position.signed_quantity) * abs(to_decimal(event.reference_price)) * spec.multiplier
        amount = notional * spec.financing_spread_annual * days / DAYS_PER_YEAR
        return [
            CashFlow(
                kind="financing",
                currency=spec.settle_currency,
                amount=-amount,
                memo=f"CFD overnight financing over {days} day(s)",
                suffix="financing",
            )
        ]

    def risk_metrics(self, spec, position, event):
        return {
            "broker_contract": "bilateral CFD; specification is broker-specific and not exchange-verifiable",
            "financing_spread_annual": str(spec.financing_spread_annual),
        }


class OptionAdapter(InstrumentAdapter):
    family = "option"
    settlement_style = "funded"

    def margin_requirement(self, spec, position, mark):
        if position.signed_quantity >= 0:
            return ZERO
        # A short option is not covered by a premium-funded model; reserve notional-scaled margin.
        terms = spec.option_terms
        strike = terms.strike if terms else abs(mark)
        return abs(position.signed_quantity) * strike * spec.multiplier * spec.initial_margin_rate

    def lifecycle(self, spec, position, event):
        terms = spec.option_terms
        if terms is None or position.is_flat:
            return []
        expiry = _parse(terms.expiry)
        now = _parse(event.event_time)
        if expiry is None or now is None or now < expiry:
            return []
        underlying = event.payload.get("underlying_price")
        if underlying is None:
            underlying = event.index_price if event.index_price is not None else None
        if underlying is None:
            return [
                LifecycleAction(
                    kind="settle_expiry",
                    reason=(
                        f"option_expired_without_underlying_price:{terms.expiry} — "
                        "position closed at last option mark because intrinsic value is not derivable"
                    ),
                    price=to_decimal(event.reference_price),
                    quantity=abs(position.signed_quantity),
                )
            ]
        intrinsic = _intrinsic(terms.right, to_decimal(underlying), terms.strike)
        kind = "settle_expiry" if position.signed_quantity > 0 else "settle_expiry"
        reason = (
            f"option_expiry {terms.right} strike={terms.strike} underlying={underlying} "
            f"intrinsic={intrinsic} style={terms.exercise_style} settlement={terms.settlement}"
        )
        if position.signed_quantity < 0 and intrinsic > 0:
            reason = "assignment: " + reason
        elif position.signed_quantity > 0 and intrinsic > 0:
            reason = "exercise: " + reason
        else:
            reason = "expired_worthless: " + reason
        return [
            LifecycleAction(
                kind=kind,
                reason=reason,
                price=intrinsic,
                quantity=abs(position.signed_quantity),
            )
        ]

    def risk_metrics(self, spec, position, event):
        terms = spec.option_terms
        if terms is None:
            return {}
        underlying = event.payload.get("underlying_price") or event.index_price
        implied = event.payload.get("implied_volatility")
        if underlying is None or implied is None:
            return {
                "greeks_available": False,
                "reason": "greeks require an underlying price and an implied-volatility input from the dataset",
                "strike": str(terms.strike),
                "expiry": terms.expiry,
                "multiplier": str(spec.multiplier),
            }
        expiry = _parse(terms.expiry)
        now = _parse(event.event_time)
        if expiry is None or now is None:
            return {"greeks_available": False, "reason": "unparsable expiry"}
        years = max(1e-6, (expiry - now).total_seconds() / (365.0 * 86400.0))
        greeks = black_scholes_greeks(
            spot=float(underlying),
            strike=float(terms.strike),
            years=years,
            rate=float(event.payload.get("risk_free_rate", 0.0)),
            sigma=float(implied),
            right=terms.right,
        )
        greeks.update(
            {
                "greeks_available": True,
                "strike": str(terms.strike),
                "expiry": terms.expiry,
                "multiplier": str(spec.multiplier),
                "years_to_expiry": years,
            }
        )
        return greeks


class BondAdapter(InstrumentAdapter):
    family = "bond"
    settlement_style = "funded"

    def cash_notional(self, spec: InstrumentSpec, fill: FillEvent) -> Decimal | None:
        terms = spec.bond_terms
        if terms is None:
            return None
        signed = fill.quantity if fill.side == "buy" else -fill.quantity
        clean = fill.price * terms.face_value / Decimal("100") if _quoted_per_100(fill.price, terms) else fill.price
        return signed * clean * spec.multiplier

    def accrued_interest(self, spec: InstrumentSpec, fill: FillEvent) -> Decimal:
        terms = spec.bond_terms
        if terms is None or terms.coupon_frequency <= 0 or terms.quote_convention != "clean":
            return ZERO
        fraction = _accrual_fraction(terms, fill.event_time)
        coupon = terms.face_value * terms.coupon_rate / Decimal(terms.coupon_frequency)
        signed = fill.quantity if fill.side == "buy" else -fill.quantity
        return abs(signed) * coupon * fraction * (Decimal("1") if fill.side == "buy" else Decimal("-1"))

    def periodic_accruals(self, spec, position, event, *, previous_event_time):
        terms = spec.bond_terms
        if terms is None or position.is_flat or terms.coupon_frequency <= 0:
            return []
        if previous_event_time is None:
            return []
        paid = _coupon_dates_between(terms, previous_event_time, event.event_time)
        if not paid:
            return []
        coupon = terms.face_value * terms.coupon_rate / Decimal(terms.coupon_frequency)
        flows: list[CashFlow] = []
        for moment in paid:
            flows.append(
                CashFlow(
                    kind="coupon",
                    currency=spec.settle_currency,
                    amount=position.signed_quantity * coupon * spec.multiplier,
                    memo=f"coupon {coupon} per bond on {moment}",
                    suffix=f"coupon-{moment}",
                )
            )
        return flows

    def lifecycle(self, spec, position, event):
        terms = spec.bond_terms
        if terms is None or position.is_flat:
            return []
        maturity = _parse(terms.maturity)
        now = _parse(event.event_time)
        if maturity is None or now is None or now < maturity:
            return []
        return [
            LifecycleAction(
                kind="redeem_maturity",
                reason=f"bond_matured:{terms.maturity} redeemed at face value {terms.face_value}",
                price=terms.face_value,
                quantity=abs(position.signed_quantity),
            )
        ]

    def risk_metrics(self, spec, position, event):
        terms = spec.bond_terms
        if terms is None:
            return {}
        fraction = _accrual_fraction(terms, event.event_time)
        coupon = terms.face_value * terms.coupon_rate / Decimal(max(1, terms.coupon_frequency))
        accrued = coupon * fraction
        clean = to_decimal(event.reference_price)
        return {
            "quote_convention": terms.quote_convention,
            "clean_price": str(clean),
            "accrued_interest_per_bond": str(accrued),
            "dirty_price": str(clean + accrued),
            "maturity": terms.maturity,
            "coupon_rate": str(terms.coupon_rate),
        }


_ADAPTERS: dict[str, InstrumentAdapter] = {
    "crypto_spot": SpotAdapter(),
    "crypto_perpetual": PerpetualAdapter(),
    "equity": EquityAdapter(),
    "etf": EquityAdapter(),
    "forex": ForexAdapter(),
    "future": FutureAdapter(),
    "option": OptionAdapter(),
    "cfd": CfdAdapter(),
    "bond": BondAdapter(),
}


def adapter_for(spec: InstrumentSpec) -> InstrumentAdapter:
    adapter = _ADAPTERS.get(spec.family)
    if adapter is None:
        raise KeyError(f"no_adapter_for_family:{spec.family}")
    return adapter


# --- maths ---------------------------------------------------------------------------


def _norm_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _norm_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def black_scholes_greeks(
    *,
    spot: float,
    strike: float,
    years: float,
    rate: float,
    sigma: float,
    right: str,
) -> dict[str, float]:
    """Analytic Black-Scholes price and Greeks.

    Used for risk reporting on option positions. It is a model, not a market price, and the
    Trading Lab never substitutes it for an observed option quote.
    """
    if spot <= 0 or strike <= 0 or years <= 0 or sigma <= 0:
        intrinsic = max(0.0, spot - strike) if right == "call" else max(0.0, strike - spot)
        return {
            "model_price": intrinsic,
            "delta": 1.0 if intrinsic > 0 and right == "call" else (-1.0 if intrinsic > 0 else 0.0),
            "gamma": 0.0,
            "vega": 0.0,
            "theta": 0.0,
            "rho": 0.0,
            "degenerate_inputs": True,
        }
    sqrt_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * sigma * sigma) * years) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    discount = math.exp(-rate * years)
    if right == "call":
        price = spot * _norm_cdf(d1) - strike * discount * _norm_cdf(d2)
        delta = _norm_cdf(d1)
        rho = strike * years * discount * _norm_cdf(d2) / 100.0
        theta = (
            -spot * _norm_pdf(d1) * sigma / (2 * sqrt_t) - rate * strike * discount * _norm_cdf(d2)
        ) / 365.0
    else:
        price = strike * discount * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0
        rho = -strike * years * discount * _norm_cdf(-d2) / 100.0
        theta = (
            -spot * _norm_pdf(d1) * sigma / (2 * sqrt_t) + rate * strike * discount * _norm_cdf(-d2)
        ) / 365.0
    return {
        "model_price": price,
        "delta": delta,
        "gamma": _norm_pdf(d1) / (spot * sigma * sqrt_t),
        "vega": spot * _norm_pdf(d1) * sqrt_t / 100.0,
        "theta": theta,
        "rho": rho,
        "degenerate_inputs": False,
    }


def _intrinsic(right: str, underlying: Decimal, strike: Decimal) -> Decimal:
    if right == "call":
        return underlying - strike if underlying > strike else ZERO
    return strike - underlying if strike > underlying else ZERO


def _quoted_per_100(price: Decimal, terms: Any) -> bool:
    """Bonds are conventionally quoted per 100 of face value."""
    return terms.face_value > Decimal("100") and price < terms.face_value / Decimal("2")


def _accrual_fraction(terms: Any, moment: str) -> Decimal:
    stamp = _parse(moment)
    if stamp is None or terms.coupon_frequency <= 0:
        return ZERO
    period_days = Decimal(360 if terms.day_count == "30/360" else 365) / Decimal(terms.coupon_frequency)
    anchor = _parse(terms.first_coupon) or _parse(terms.maturity)
    if anchor is None:
        return ZERO
    period_seconds = float(period_days) * 86400.0
    delta = (anchor - stamp).total_seconds()
    if period_seconds <= 0:
        return ZERO
    # Distance since the most recent coupon boundary, walking back from the anchor date.
    remainder = delta % period_seconds
    since = (period_seconds - remainder) % period_seconds
    fraction = Decimal(str(since / period_seconds))
    return max(ZERO, min(Decimal("1"), fraction))


def _coupon_dates_between(terms: Any, start: str, end: str) -> list[str]:
    begin = _parse(start)
    finish = _parse(end)
    maturity = _parse(terms.maturity)
    if begin is None or finish is None or maturity is None or terms.coupon_frequency <= 0:
        return []
    interval = timedelta(days=365 / terms.coupon_frequency)
    dates: list[str] = []
    cursor = maturity
    guard = 0
    while cursor > begin and guard < 400:
        if begin < cursor <= finish:
            dates.append(cursor.isoformat(timespec="seconds"))
        cursor = cursor - interval
        guard += 1
    return sorted(dates)


def _elapsed_days(previous: str | None, current: str) -> Decimal:
    start = _parse(previous) if previous else None
    end = _parse(current)
    if start is None or end is None or end <= start:
        return ZERO
    seconds = (end - start).total_seconds()
    return Decimal(str(seconds / 86400.0))


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)


__all__ = [
    "BondAdapter",
    "CashFlow",
    "CfdAdapter",
    "EquityAdapter",
    "ForexAdapter",
    "FutureAdapter",
    "InstrumentAdapter",
    "LifecycleAction",
    "OptionAdapter",
    "PerpetualAdapter",
    "SpotAdapter",
    "adapter_for",
    "black_scholes_greeks",
]
