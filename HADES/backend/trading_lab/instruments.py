"""Instrument Registry.

Owns instrument identity and contract rules. Every other layer asks the registry instead
of guessing: tick/lot grids, multipliers, margin rates, calendars, whether shorting is
allowed, and whether a price may be zero or negative.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Iterable

from trading_lab.calendars import get_calendar
from trading_lab.contracts import (
    BondTerms,
    FutureTerms,
    InstrumentFamily,
    InstrumentSpec,
    OptionTerms,
)

LEGACY_VENUE = "LOCAL"


def make_instrument_id(family: str, venue: str, symbol: str) -> str:
    return f"{family}:{venue.strip().upper()}:{symbol.strip().upper()}"


def _spec(**values: Any) -> InstrumentSpec:
    return InstrumentSpec(**values)


def default_instruments() -> list[InstrumentSpec]:
    """Built-in reference instruments, one per supported family.

    These are *contract definitions*, not market data. They exist so the capability matrix
    and the order ticket can be exercised without first downloading anything. None of them
    implies that HADES has price history for the instrument.
    """
    return [
        _spec(
            instrument_id=make_instrument_id("crypto_spot", LEGACY_VENUE, "BTC/USDT"),
            family="crypto_spot",
            venue=LEGACY_VENUE,
            symbol="BTC/USDT",
            description="Bitcoin against USDT, spot.",
            base_currency="BTC",
            quote_currency="USDT",
            tick_size=Decimal("0.01"),
            lot_size=Decimal("0.00000100"),
            min_notional=Decimal("5"),
            shorting_allowed=False,
            calendar="24x7",
            listed_from="2017-08-17",
            initial_margin_rate=Decimal("1"),
            maintenance_margin_rate=Decimal("1"),
        ),
        _spec(
            instrument_id=make_instrument_id("crypto_spot", LEGACY_VENUE, "ETH/USDT"),
            family="crypto_spot",
            venue=LEGACY_VENUE,
            symbol="ETH/USDT",
            description="Ether against USDT, spot.",
            base_currency="ETH",
            quote_currency="USDT",
            tick_size=Decimal("0.01"),
            lot_size=Decimal("0.00010000"),
            min_notional=Decimal("5"),
            shorting_allowed=False,
            calendar="24x7",
            listed_from="2017-08-17",
        ),
        _spec(
            instrument_id=make_instrument_id("crypto_perpetual", LEGACY_VENUE, "BTC-PERP"),
            family="crypto_perpetual",
            venue=LEGACY_VENUE,
            symbol="BTC-PERP",
            description="Inverse-of-nothing linear perpetual on BTC, USDT margined.",
            base_currency="BTC",
            quote_currency="USDT",
            settlement_currency="USDT",
            tick_size=Decimal("0.1"),
            lot_size=Decimal("0.00100000"),
            shorting_allowed=True,
            calendar="24x7",
            funding_interval_hours=8,
            initial_margin_rate=Decimal("0.1"),
            maintenance_margin_rate=Decimal("0.05"),
            listed_from="2019-09-01",
        ),
        _spec(
            instrument_id=make_instrument_id("equity", "XNAS", "AAPL"),
            family="equity",
            venue="XNAS",
            symbol="AAPL",
            description="Apple Inc. common stock.",
            base_currency="AAPL",
            quote_currency="USD",
            tick_size=Decimal("0.01"),
            lot_size=Decimal("1"),
            shorting_allowed=True,
            borrow_available=True,
            borrow_fee_annual=Decimal("0.005"),
            calendar="us_equity_rth",
            listed_from="1980-12-12",
            initial_margin_rate=Decimal("0.5"),
            maintenance_margin_rate=Decimal("0.25"),
        ),
        _spec(
            instrument_id=make_instrument_id("etf", "ARCX", "SPY"),
            family="etf",
            venue="ARCX",
            symbol="SPY",
            description="SPDR S&P 500 ETF Trust.",
            base_currency="SPY",
            quote_currency="USD",
            tick_size=Decimal("0.01"),
            lot_size=Decimal("1"),
            shorting_allowed=True,
            borrow_fee_annual=Decimal("0.003"),
            calendar="us_equity_rth",
            listed_from="1993-01-22",
            initial_margin_rate=Decimal("0.5"),
            maintenance_margin_rate=Decimal("0.25"),
        ),
        _spec(
            instrument_id=make_instrument_id("forex", "FX", "EUR/USD"),
            family="forex",
            venue="FX",
            symbol="EUR/USD",
            description="Euro against US dollar, spot FX.",
            base_currency="EUR",
            quote_currency="USD",
            tick_size=Decimal("0.00001"),
            lot_size=Decimal("1000"),
            shorting_allowed=True,
            calendar="fx_5x24",
            financing_spread_annual=Decimal("0.005"),
            initial_margin_rate=Decimal("0.03"),
            maintenance_margin_rate=Decimal("0.015"),
        ),
        _spec(
            instrument_id=make_instrument_id("future", "CME", "CLZ2024"),
            family="future",
            venue="CME",
            symbol="CLZ2024",
            description="WTI crude oil futures contract. Price may be negative (April 2020 precedent).",
            base_currency="USD",
            quote_currency="USD",
            multiplier=Decimal("1000"),
            tick_size=Decimal("0.01"),
            lot_size=Decimal("1"),
            price_can_be_negative=True,
            shorting_allowed=True,
            calendar="cme_near_24",
            initial_margin_rate=Decimal("0.1"),
            maintenance_margin_rate=Decimal("0.07"),
            future_terms=FutureTerms(expiry="2024-11-20T18:30:00+00:00", settlement="cash", roll_days_before_expiry=5),
        ),
        _spec(
            instrument_id=make_instrument_id("option", "OPRA", "AAPL-2024-12-20-C-200"),
            family="option",
            venue="OPRA",
            symbol="AAPL-2024-12-20-C-200",
            description="AAPL 200 call expiring 2024-12-20, 100 multiplier.",
            base_currency="USD",
            quote_currency="USD",
            multiplier=Decimal("100"),
            tick_size=Decimal("0.01"),
            lot_size=Decimal("1"),
            shorting_allowed=True,
            calendar="us_equity_rth",
            initial_margin_rate=Decimal("1"),
            maintenance_margin_rate=Decimal("1"),
            option_terms=OptionTerms(
                right="call",
                strike=Decimal("200"),
                expiry="2024-12-20T21:00:00+00:00",
                exercise_style="american",
                settlement="cash",
                underlying_instrument_id=make_instrument_id("equity", "XNAS", "AAPL"),
            ),
        ),
        _spec(
            instrument_id=make_instrument_id("cfd", "CFD", "GER40"),
            family="cfd",
            venue="CFD",
            symbol="GER40",
            description="Index CFD on the German 40. Synthetic broker contract, not an exchange product.",
            base_currency="EUR",
            quote_currency="EUR",
            multiplier=Decimal("1"),
            tick_size=Decimal("0.1"),
            lot_size=Decimal("0.1"),
            shorting_allowed=True,
            calendar="cme_near_24",
            financing_spread_annual=Decimal("0.025"),
            initial_margin_rate=Decimal("0.05"),
            maintenance_margin_rate=Decimal("0.025"),
        ),
        _spec(
            instrument_id=make_instrument_id("bond", "OTC", "US10Y-2034"),
            family="bond",
            venue="OTC",
            symbol="US10Y-2034",
            description="Reference 10-year government bond, 1000 face, semi-annual coupon.",
            base_currency="USD",
            quote_currency="USD",
            multiplier=Decimal("1"),
            tick_size=Decimal("0.01"),
            lot_size=Decimal("1"),
            shorting_allowed=False,
            calendar="bond_otc",
            initial_margin_rate=Decimal("1"),
            maintenance_margin_rate=Decimal("1"),
            bond_terms=BondTerms(
                coupon_rate=Decimal("0.04"),
                coupon_frequency=2,
                face_value=Decimal("1000"),
                maturity="2034-05-15T00:00:00+00:00",
                day_count="30/360",
                quote_convention="clean",
            ),
        ),
    ]


class InstrumentRegistry:
    """In-memory registry with optional durable backing.

    ``store`` is any object exposing ``list_instruments()``/``upsert_instrument(spec)``.
    Passing ``None`` keeps the registry ephemeral, which is what unit fixtures want.
    """

    def __init__(self, store: Any | None = None) -> None:
        self._store = store
        self._specs: dict[str, InstrumentSpec] = {}
        for spec in default_instruments():
            self._specs[spec.instrument_id] = spec
        self._builtin_ids = set(self._specs)
        self.reload()

    # --- lifecycle ---------------------------------------------------------------

    def reload(self) -> None:
        if self._store is None:
            return
        for payload in self._store.list_instruments():
            try:
                spec = InstrumentSpec.model_validate(payload)
            except Exception:
                continue
            self._specs[spec.instrument_id] = spec

    def register(self, spec: InstrumentSpec, *, persist: bool = True) -> InstrumentSpec:
        if get_calendar(spec.calendar).calendar_id != spec.calendar and spec.calendar not in {"24x7"}:
            raise ValueError(f"unknown_calendar:{spec.calendar}")
        self._specs[spec.instrument_id] = spec
        if persist and self._store is not None:
            self._store.upsert_instrument(spec)
        return spec

    def remove(self, instrument_id: str) -> bool:
        if instrument_id in self._builtin_ids:
            raise ValueError("builtin_instrument_not_removable")
        existed = self._specs.pop(instrument_id, None) is not None
        if existed and self._store is not None:
            self._store.delete_instrument(instrument_id)
        return existed

    # --- lookup ------------------------------------------------------------------

    def get(self, instrument_id: str) -> InstrumentSpec:
        spec = self._specs.get(instrument_id)
        if spec is None:
            raise KeyError(f"unknown_instrument:{instrument_id}")
        return spec

    def find(self, instrument_id: str) -> InstrumentSpec | None:
        return self._specs.get(instrument_id)

    def list(self, *, family: InstrumentFamily | None = None, venue: str | None = None) -> list[InstrumentSpec]:
        items = list(self._specs.values())
        if family:
            items = [item for item in items if item.family == family]
        if venue:
            items = [item for item in items if item.venue.upper() == venue.upper()]
        return sorted(items, key=lambda item: (item.family, item.venue, item.symbol))

    def families(self) -> list[str]:
        return sorted({spec.family for spec in self._specs.values()})

    def venues(self) -> list[str]:
        return sorted({spec.venue for spec in self._specs.values()})

    # --- legacy bridge -----------------------------------------------------------

    def resolve_legacy_symbol(self, symbol: str, *, family: str = "crypto_spot") -> InstrumentSpec:
        """Map a bare legacy ``market_bars`` symbol onto an instrument.

        The legacy Paper flow stores symbols such as ``BTC/USDT`` with no venue or family.
        Rather than guessing silently, this resolves to an explicit ``LOCAL`` instrument and
        registers a conservative spot definition when one does not exist yet.
        """
        clean = (symbol or "").strip().upper()
        if not clean:
            raise ValueError("empty_symbol")
        exact = self._specs.get(clean)
        if exact is not None:
            return exact
        candidate = make_instrument_id(family, LEGACY_VENUE, clean)
        existing = self._specs.get(candidate)
        if existing is not None:
            return existing
        matches = [spec for spec in self._specs.values() if spec.symbol.upper() == clean]
        if len(matches) == 1:
            return matches[0]
        base, _, quote = clean.partition("/")
        spec = InstrumentSpec(
            instrument_id=candidate,
            family="crypto_spot",
            venue=LEGACY_VENUE,
            symbol=clean,
            description="Auto-registered from legacy market_bars symbol; contract details unverified.",
            base_currency=base or clean,
            quote_currency=quote or "USDT",
            tick_size=Decimal("0.00000001"),
            lot_size=Decimal("0.00000001"),
            shorting_allowed=False,
            calendar="24x7",
            metadata={"origin": "legacy_market_bars", "contract_details": "unverified"},
        )
        return self.register(spec)

    # --- rules -------------------------------------------------------------------

    def is_tradable_at(self, instrument_id: str, moment: datetime) -> tuple[bool, str]:
        spec = self.get(instrument_id)
        stamp = moment.astimezone(UTC)
        if spec.listed_from:
            listed = _parse(spec.listed_from)
            if listed and stamp < listed:
                return False, f"not_listed_before:{spec.listed_from}"
        if spec.delisted_at:
            delisted = _parse(spec.delisted_at)
            if delisted and stamp >= delisted:
                return False, f"delisted_at:{spec.delisted_at}"
        for terms in (spec.future_terms, spec.option_terms):
            expiry = getattr(terms, "expiry", None)
            if expiry:
                moment_expiry = _parse(expiry)
                if moment_expiry and stamp > moment_expiry:
                    return False, f"expired_at:{expiry}"
        if spec.bond_terms:
            maturity = _parse(spec.bond_terms.maturity)
            if maturity and stamp > maturity:
                return False, f"matured_at:{spec.bond_terms.maturity}"
        if not get_calendar(spec.calendar).is_open(stamp):
            return False, f"venue_closed:{spec.calendar}"
        return True, "open"

    def point_in_time_universe(self, moment: datetime, *, family: InstrumentFamily | None = None) -> list[InstrumentSpec]:
        """Instruments that existed at ``moment`` — including ones later delisted."""
        stamp = moment.astimezone(UTC)
        result: list[InstrumentSpec] = []
        for spec in self.list(family=family):
            listed = _parse(spec.listed_from) if spec.listed_from else None
            delisted = _parse(spec.delisted_at) if spec.delisted_at else None
            if listed and stamp < listed:
                continue
            if delisted and stamp >= delisted:
                continue
            result.append(spec)
        return result

    def round_quantity(self, instrument_id: str, quantity: Decimal) -> Decimal:
        from trading_lab.contracts import quantize_step

        return quantize_step(quantity, self.get(instrument_id).lot_size)

    def round_price(self, instrument_id: str, price: Decimal) -> Decimal:
        from decimal import ROUND_HALF_EVEN

        from trading_lab.contracts import quantize_step

        return quantize_step(price, self.get(instrument_id).tick_size, rounding=ROUND_HALF_EVEN)

    def as_json(self, instruments: Iterable[InstrumentSpec] | None = None) -> list[dict[str, Any]]:
        source = instruments if instruments is not None else self.list()
        return [spec.as_json() for spec in source]


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


__all__ = ["InstrumentRegistry", "LEGACY_VENUE", "default_instruments", "make_instrument_id"]
