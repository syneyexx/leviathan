"""Instrument / market model — honest capability claims per family.

Institutional W07 foundation: structured identifiers, multiplier/notional,
family inventory including fixed_income stubs, and fail-closed unsupported
families (enum existence is never market support).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_EVEN
from enum import Enum
from typing import Any


class InstrumentFamily(str, Enum):
    EQUITY = "equity"
    CRYPTO_SPOT = "crypto_spot"
    OPTIONS = "options"
    FUTURES = "futures"
    FOREX = "forex"
    FIXED_INCOME = "fixed_income"
    OTHER = "other"


class DataLevel(str, Enum):
    OHLCV = "ohlcv"
    TRADES = "trades"
    QUOTES = "quotes"
    ORDERBOOK = "orderbook"


class CapabilityState(str, Enum):
    """Derived from working adapters + config checks — not feature flags alone."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    BLOCKED = "BLOCKED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


# Families the sim/paper path actually implements. Everything else must stay
# explicit NOT_IMPLEMENTED — never silently reuse equity lot/tick/fill rules (T16).
SUPPORTED_SIM_FAMILIES: frozenset[InstrumentFamily] = frozenset(
    {InstrumentFamily.EQUITY, InstrumentFamily.CRYPTO_SPOT}
)
UNSUPPORTED_SIM_FAMILIES: frozenset[InstrumentFamily] = frozenset(
    {
        InstrumentFamily.OPTIONS,
        InstrumentFamily.FUTURES,
        InstrumentFamily.FOREX,
        InstrumentFamily.FIXED_INCOME,
        InstrumentFamily.OTHER,
    }
)


@dataclass(frozen=True)
class InstrumentIdentifiers:
    """Canonical identity fields — free-text venue/symbol alone is not enough long-term."""

    symbol: str
    venue: str
    isin: str | None = None
    figi: str | None = None
    exchange_symbol: str | None = None
    currency_pair: str | None = None  # FX later (W09); unused for equity/crypto

    def public_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "venue": self.venue,
            "isin": self.isin,
            "figi": self.figi,
            "exchangeSymbol": self.exchange_symbol or self.symbol,
            "currencyPair": self.currency_pair,
        }


def make_instrument_id(
    family: InstrumentFamily | str,
    symbol: str,
    venue: str,
) -> str:
    fam = family.value if isinstance(family, InstrumentFamily) else str(family)
    return f"{fam}:{symbol.upper()}:{venue.upper()}"


def parse_instrument_id(instrument_id: str) -> tuple[str, str, str]:
    """Parse ``family:SYMBOL:VENUE`` — raises ValueError on malformed ids."""
    parts = (instrument_id or "").split(":")
    if len(parts) != 3 or not all(parts):
        raise ValueError(f"malformed instrument_id: {instrument_id!r}")
    return parts[0], parts[1], parts[2]


def family_capability_status(family: InstrumentFamily | str) -> CapabilityState:
    """Return sim capability for a family — unsupported never reports AVAILABLE."""
    if isinstance(family, str):
        try:
            family = InstrumentFamily(family)
        except ValueError:
            return CapabilityState.NOT_IMPLEMENTED
    if family in SUPPORTED_SIM_FAMILIES:
        return CapabilityState.AVAILABLE
    return CapabilityState.NOT_IMPLEMENTED


def assert_family_implemented(family: InstrumentFamily | str) -> InstrumentFamily:
    """Raise MarketSimError when family would silently fall back to equity mechanics."""
    from .types import MarketSimError

    if isinstance(family, str):
        try:
            fam = InstrumentFamily(family)
        except ValueError as exc:
            raise MarketSimError(
                "INSTRUMENT_FAMILY_NOT_IMPLEMENTED",
                f"Unknown instrument family {family!r} — refusing equity fallback",
                http_status=501,
            ) from exc
    else:
        fam = family
    status = family_capability_status(fam)
    if status == CapabilityState.NOT_IMPLEMENTED:
        raise MarketSimError(
            "INSTRUMENT_FAMILY_NOT_IMPLEMENTED",
            (
                f"Instrument family '{fam.value}' is NOT_IMPLEMENTED — "
                "refusing to simulate as equity/crypto_spot"
            ),
            http_status=501,
        )
    return fam


@dataclass(frozen=True)
class BorrowConstraints:
    """Equity/ETF borrow honesty (W08). Fee unset ⇒ borrow cost UNMEASURED."""

    locatable: bool = True
    hard_to_borrow: bool = False
    borrow_fee_bps_per_day: float | None = None
    status: str = "UNMEASURED"  # MEASURED | UNMEASURED

    def resolved_status(self) -> str:
        if self.borrow_fee_bps_per_day is not None:
            return "MEASURED"
        return self.status if self.status in {"MEASURED", "UNMEASURED"} else "UNMEASURED"

    def allows_short_open(self) -> tuple[bool, str]:
        if not self.locatable:
            return False, "BORROW_CONSTRAINT: not locatable"
        return True, "borrow_ok"

    def public_dict(self) -> dict[str, Any]:
        return {
            "locatable": self.locatable,
            "hardToBorrow": self.hard_to_borrow,
            "borrowFeeBpsPerDay": self.borrow_fee_bps_per_day,
            "borrowCost": self.resolved_status(),
            "truth": {
                "supports_short_is_not_borrow_inventory": True,
                "unset_borrow_fee_is_UNMEASURED": self.borrow_fee_bps_per_day is None,
            },
        }


@dataclass(frozen=True)
class InstrumentSpec:
    instrument_id: str
    symbol: str
    family: InstrumentFamily
    venue: str
    quote_currency: str
    settlement_currency: str | None = None  # W13A: defaults to quote when unset
    timezone: str = "UTC"
    tick_size: str = "0.01"
    lot_size: str = "0.0001"
    min_notional: str = "1"
    supports_short: bool = False
    data_level: DataLevel = DataLevel.OHLCV
    # W07 — contract multiplier (futures/options later). Equity/crypto default "1".
    multiplier: str = "1"
    isin: str | None = None
    figi: str | None = None
    exchange_symbol: str | None = None
    # W08 — equities/ETF hardening (ETF remains InstrumentFamily.EQUITY).
    is_etf: bool = False
    adjustment_mode: str = "as_traded"
    session_calendar_id: str | None = None
    borrow: BorrowConstraints | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def resolved_settlement_currency(self) -> str:
        return self.settlement_currency or self.quote_currency

    def identifiers(self) -> InstrumentIdentifiers:
        return InstrumentIdentifiers(
            symbol=self.symbol,
            venue=self.venue,
            isin=self.isin,
            figi=self.figi,
            exchange_symbol=self.exchange_symbol or self.symbol,
            currency_pair=(self.metadata or {}).get("currency_pair"),
        )

    def capability_status(self) -> CapabilityState:
        meta_cap = self.metadata.get("capability") if self.metadata else None
        if meta_cap:
            try:
                return CapabilityState(str(meta_cap))
            except ValueError:
                pass
        return family_capability_status(self.family)

    def normalized_adjustment_mode(self) -> str:
        from .pit_fabric import normalize_adjustment_mode

        return normalize_adjustment_mode(self.adjustment_mode)

    def public_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "family": self.family.value,
            "venue": self.venue,
            "quote_currency": self.quote_currency,
            "settlement_currency": self.resolved_settlement_currency(),
            "timezone": self.timezone,
            "tick_size": self.tick_size,
            "lot_size": self.lot_size,
            "min_notional": self.min_notional,
            "multiplier": self.multiplier,
            "supports_short": self.supports_short,
            "data_level": self.data_level.value,
            "is_etf": self.is_etf,
            "adjustment_mode": self.normalized_adjustment_mode(),
            "session_calendar_id": self.session_calendar_id,
            "borrow": self.borrow.public_dict() if self.borrow else None,
            "identifiers": self.identifiers().public_dict(),
            "capability": self.capability_status().value,
            "metadata": self.metadata,
            "truth": {
                "unsupported_family_never_silently_equity": (
                    self.family in SUPPORTED_SIM_FAMILIES
                    or self.capability_status() == CapabilityState.NOT_IMPLEMENTED
                ),
                "enum_exists_is_not_market_support": True,
                "multiplier_required_for_contract_notional": True,
                "etf_is_equity_family_not_separate_enum": True,
                "adjusted_vs_unadjusted_must_be_labeled": True,
                "supports_short_is_not_borrow_inventory": True,
            },
        }


EQUITY_AAPL = InstrumentSpec(
    instrument_id="equity:AAPL:NASDAQ",
    symbol="AAPL",
    family=InstrumentFamily.EQUITY,
    venue="NASDAQ",
    quote_currency="USD",
    timezone="America/New_York",
    tick_size="0.01",
    lot_size="1",
    min_notional="1",
    multiplier="1",
    isin="US0378331005",
    exchange_symbol="AAPL",
    is_etf=False,
    adjustment_mode="as_traded",
    session_calendar_id="XNYS",
    borrow=BorrowConstraints(locatable=True, hard_to_borrow=False),
)

EQUITY_SPY = InstrumentSpec(
    instrument_id="equity:SPY:ARCA",
    symbol="SPY",
    family=InstrumentFamily.EQUITY,
    venue="ARCA",
    quote_currency="USD",
    timezone="America/New_York",
    tick_size="0.01",
    lot_size="1",
    min_notional="1",
    multiplier="1",
    isin="US78462F1030",
    exchange_symbol="SPY",
    is_etf=True,
    adjustment_mode="as_traded",
    session_calendar_id="XNYS",
    borrow=BorrowConstraints(locatable=True, hard_to_borrow=False),
)

CRYPTO_BTCUSDT = InstrumentSpec(
    instrument_id="crypto_spot:BTCUSDT:BINANCE",
    symbol="BTCUSDT",
    family=InstrumentFamily.CRYPTO_SPOT,
    venue="BINANCE",
    quote_currency="USDT",
    timezone="UTC",
    tick_size="0.01",
    lot_size="0.0001",
    min_notional="10",
    multiplier="1",
    exchange_symbol="BTCUSDT",
)

# Stub specs for unsupported families — capability NOT_IMPLEMENTED; never tradeable.
FUTURES_ES_STUB = InstrumentSpec(
    instrument_id="futures:ES:CME",
    symbol="ES",
    family=InstrumentFamily.FUTURES,
    venue="CME",
    quote_currency="USD",
    tick_size="0.25",
    lot_size="1",
    min_notional="1",
    multiplier="50",
    metadata={"capability": "NOT_IMPLEMENTED", "stub": True},
)

FIXED_INCOME_US10Y_STUB = InstrumentSpec(
    instrument_id="fixed_income:US10Y:OTC",
    symbol="US10Y",
    family=InstrumentFamily.FIXED_INCOME,
    venue="OTC",
    quote_currency="USD",
    tick_size="0.001",
    lot_size="1000",
    min_notional="1000",
    multiplier="1",
    metadata={"capability": "NOT_IMPLEMENTED", "stub": True},
)

_REGISTRY: dict[str, InstrumentSpec] = {
    EQUITY_AAPL.instrument_id: EQUITY_AAPL,
    EQUITY_SPY.instrument_id: EQUITY_SPY,
    CRYPTO_BTCUSDT.instrument_id: CRYPTO_BTCUSDT,
    FUTURES_ES_STUB.instrument_id: FUTURES_ES_STUB,
    FIXED_INCOME_US10Y_STUB.instrument_id: FIXED_INCOME_US10Y_STUB,
    EQUITY_AAPL.symbol: EQUITY_AAPL,
    EQUITY_SPY.symbol: EQUITY_SPY,
    CRYPTO_BTCUSDT.symbol: CRYPTO_BTCUSDT,
    FUTURES_ES_STUB.symbol: FUTURES_ES_STUB,
    FIXED_INCOME_US10Y_STUB.symbol: FIXED_INCOME_US10Y_STUB,
}


def family_capability(family: InstrumentFamily | str) -> CapabilityState:
    """Honest capability matrix — enum existence is not market support."""
    return family_capability_status(family)


def support_matrix() -> dict[str, Any]:
    """Explicit support matrix for operator/UI honesty (W19 / T16 / W07)."""
    rows = []
    for fam in InstrumentFamily:
        cap = family_capability(fam)
        rows.append(
            {
                "family": fam.value,
                "capability": cap.value,
                "end_to_end": cap == CapabilityState.AVAILABLE,
                "truth": {
                    "enum_exists_is_not_market_support": True,
                    "no_silent_equity_fallback": True,
                },
            }
        )
    return {
        "families": rows,
        "truth": {
            "enum_exists_is_not_market_support": True,
            "unsupported_is_explicit": True,
            "fixed_income_is_not_equity": True,
        },
    }


def infer_family(
    symbol: str,
    *,
    venue: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> InstrumentFamily:
    """Infer family. Explicit metadata.family is never silently overwritten.

    Unknown symbols without explicit family metadata default to equity only when
    they look like equity tickers — never map options/futures/forex markers to equity.
    """
    meta = metadata or {}
    if meta.get("family") is not None:
        try:
            return InstrumentFamily(str(meta["family"]))
        except ValueError as exc:
            raise ValueError(f"INSTRUMENT_RULE: unknown family {meta['family']!r}") from exc
    sym = symbol.upper().replace("/", "").replace("-", "")
    itype = str(meta.get("instrument_type") or "").lower()
    # ETF is equity family with is_etf flag — not a separate InstrumentFamily.
    if itype in {"etf", "exchange_traded_fund"} or meta.get("is_etf") is True:
        return InstrumentFamily.EQUITY
    if itype in {"bond", "fixed_income", "treasury", "govvie"}:
        return InstrumentFamily.FIXED_INCOME
    if any(tok in sym for tok in ("BOND", "US10Y", "TNOTE", "TBILL")):
        return InstrumentFamily.FIXED_INCOME
    # Explicit unsupported-family markers — never equity fallback.
    if any(tok in sym for tok in ("OPT", "CALL", "PUT")) or itype in {
        "option",
        "options",
    }:
        return InstrumentFamily.OPTIONS
    if any(tok in sym for tok in ("PERP", "FUT", "FUTURE")) or itype in {
        "future",
        "futures",
    }:
        return InstrumentFamily.FUTURES
    if itype in {"fx", "forex"} or (
        len(sym) == 6 and sym.isalpha() and sym[:3] != sym[3:] and sym.endswith(("USD", "EUR", "GBP", "JPY"))
        and not sym.endswith(("USDT", "USDC"))
    ):
        # Crude FX pair detector; still NOT_IMPLEMENTED for execution.
        if venue and venue.upper() in {"BINANCE", "COINBASE", "KRAKEN"}:
            pass  # crypto venues win below
        elif itype in {"fx", "forex"} or meta.get("family") == "forex":
            return InstrumentFamily.FOREX
        elif len(sym) == 6 and sym.isalpha() and not sym.endswith(("USDT", "USDC")):
            # EURUSD-style — treat as forex unsupported rather than equity.
            if sym[:3] in {"EUR", "GBP", "USD", "JPY", "CHF", "AUD", "CAD", "NZD"}:
                return InstrumentFamily.FOREX
    if venue and venue.upper() in {"BINANCE", "COINBASE", "KRAKEN"}:
        return InstrumentFamily.CRYPTO_SPOT
    if sym.endswith("USDT") or sym.endswith("USDC") or (sym.endswith("BTC") and len(sym) > 6):
        return InstrumentFamily.CRYPTO_SPOT
    if sym in {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"}:
        return InstrumentFamily.CRYPTO_SPOT
    return InstrumentFamily.EQUITY


def spec_for_symbol(
    symbol: str,
    *,
    timeframe: str = "1h",
    metadata: dict[str, Any] | None = None,
) -> InstrumentSpec:
    meta = dict(metadata or {})
    family = infer_family(symbol, venue=meta.get("venue"), metadata=meta)
    supports_short = bool(meta.get("supports_short", False))
    multiplier = str(meta.get("multiplier") or "1")
    venue = str(meta.get("venue") or ("BINANCE" if family == InstrumentFamily.CRYPTO_SPOT else "NASDAQ"))
    if family == InstrumentFamily.CRYPTO_SPOT:
        venue = str(meta.get("venue") or "BINANCE")
        return InstrumentSpec(
            instrument_id=make_instrument_id(family, symbol, venue),
            symbol=symbol.upper(),
            family=family,
            venue=venue,
            quote_currency=str(meta.get("quote_currency") or "USDT"),
            timezone="UTC",
            tick_size=str(meta.get("tick_size") or "0.01"),
            lot_size=str(meta.get("lot_size") or "0.0001"),
            min_notional=str(meta.get("min_notional") or "10"),
            supports_short=supports_short,
            multiplier=multiplier,
            isin=meta.get("isin"),
            figi=meta.get("figi"),
            exchange_symbol=str(meta.get("exchange_symbol") or symbol.upper()),
            metadata={"timeframe": timeframe, **meta},
        )
    if family in UNSUPPORTED_SIM_FAMILIES:
        venue = str(meta.get("venue") or "UNKNOWN")
        return InstrumentSpec(
            instrument_id=make_instrument_id(family, symbol, venue),
            symbol=symbol.upper(),
            family=family,
            venue=venue,
            quote_currency=str(meta.get("quote_currency") or "USD"),
            timezone=str(meta.get("timezone") or "UTC"),
            tick_size=str(meta.get("tick_size") or "0.01"),
            lot_size=str(meta.get("lot_size") or "1"),
            min_notional=str(meta.get("min_notional") or "1"),
            supports_short=supports_short,
            multiplier=multiplier,
            isin=meta.get("isin"),
            figi=meta.get("figi"),
            exchange_symbol=str(meta.get("exchange_symbol") or symbol.upper()),
            metadata={
                "timeframe": timeframe,
                "capability": family_capability(family).value,
                "end_to_end": False,
                "no_equity_fallback": True,
                **meta,
            },
        )
    venue = str(meta.get("venue") or "NASDAQ")
    is_etf = bool(meta.get("is_etf")) or str(meta.get("instrument_type") or "").lower() in {
        "etf",
        "exchange_traded_fund",
    }
    borrow = None
    if "borrow" in meta and isinstance(meta["borrow"], BorrowConstraints):
        borrow = meta["borrow"]
    elif meta.get("borrow") and isinstance(meta["borrow"], dict):
        raw_b = meta["borrow"]
        borrow = BorrowConstraints(
            locatable=bool(raw_b.get("locatable", True)),
            hard_to_borrow=bool(raw_b.get("hard_to_borrow", raw_b.get("hardToBorrow", False))),
            borrow_fee_bps_per_day=(
                None
                if raw_b.get("borrow_fee_bps_per_day", raw_b.get("borrowFeeBpsPerDay")) is None
                else float(raw_b.get("borrow_fee_bps_per_day", raw_b.get("borrowFeeBpsPerDay")))
            ),
            status=str(raw_b.get("status") or "UNMEASURED"),
        )
    return InstrumentSpec(
        instrument_id=make_instrument_id(InstrumentFamily.EQUITY, symbol, venue),
        symbol=symbol.upper(),
        family=InstrumentFamily.EQUITY,
        venue=venue,
        quote_currency=str(meta.get("quote_currency") or "USD"),
        timezone=str(meta.get("timezone") or "America/New_York"),
        tick_size=str(meta.get("tick_size") or "0.01"),
        lot_size=str(meta.get("lot_size") or "1"),
        min_notional=str(meta.get("min_notional") or "1"),
        supports_short=supports_short,
        multiplier=multiplier,
        isin=meta.get("isin"),
        figi=meta.get("figi"),
        exchange_symbol=str(meta.get("exchange_symbol") or symbol.upper()),
        is_etf=is_etf,
        adjustment_mode=str(meta.get("adjustment_mode") or "as_traded"),
        session_calendar_id=meta.get("session_calendar_id") or meta.get("sessionCalendarId"),
        borrow=borrow,
        metadata={"timeframe": timeframe, **meta},
    )


def registry_lookup(
    symbol_or_id: str,
    *,
    venue: str | None = None,
    family: InstrumentFamily | str | None = None,
) -> InstrumentSpec | None:
    """Lookup known catalog specs; None when unknown (does not invent support)."""
    key = (symbol_or_id or "").strip()
    if not key:
        return None
    if key in _REGISTRY:
        return _REGISTRY[key]
    upper = key.upper()
    if upper in _REGISTRY:
        return _REGISTRY[upper]
    if family is not None and venue:
        fam = family if isinstance(family, InstrumentFamily) else InstrumentFamily(str(family))
        iid = make_instrument_id(fam, upper, venue)
        return _REGISTRY.get(iid)
    return None


def register_instrument(spec: InstrumentSpec) -> InstrumentSpec:
    """Insert/replace a catalog entry (tests / operator seeding)."""
    _REGISTRY[spec.instrument_id] = spec
    _REGISTRY[spec.symbol.upper()] = spec
    return spec


def compute_notional(qty: Any, price: Any, *, multiplier: str | Decimal | InstrumentSpec = "1") -> Decimal:
    """Contract-aware notional = qty × price × multiplier."""
    mult = multiplier
    if isinstance(multiplier, InstrumentSpec):
        mult = multiplier.multiplier
    return Decimal(str(qty)) * Decimal(str(price)) * Decimal(str(mult))


def round_to_lot(qty: Any, lot_size: str | Decimal) -> Decimal:
    lot = Decimal(str(lot_size))
    if lot <= 0:
        return Decimal(str(qty))
    q = Decimal(str(qty))
    return (q / lot).to_integral_value(rounding=ROUND_DOWN) * lot


def round_to_tick(price: Any, tick_size: str | Decimal) -> Decimal:
    tick = Decimal(str(tick_size))
    if tick <= 0:
        return Decimal(str(price))
    p = Decimal(str(price))
    return (p / tick).to_integral_value(rounding=ROUND_HALF_EVEN) * tick


def validate_intent_rules(
    *,
    spec: InstrumentSpec,
    side: str,
    qty: Any,
    price: Any,
    opening_short: bool = False,
    short_margin_policy: Any = None,
) -> tuple[bool, str, Decimal]:
    """Enforce lot/tick/min_notional and short policy. Returns (ok, reason, rounded_qty)."""
    from .short_margin import ShortMarginPolicy, short_open_allowed

    # T16: unsupported families must fail closed — never apply equity lot/tick rules.
    if (
        spec.family in UNSUPPORTED_SIM_FAMILIES
        or spec.capability_status() == CapabilityState.NOT_IMPLEMENTED
    ):
        return (
            False,
            (
                f"INSTRUMENT_FAMILY_NOT_IMPLEMENTED: family={spec.family.value} "
                "cannot trade under equity/crypto_spot rules"
            ),
            Decimal("0"),
        )

    rounded_qty = round_to_lot(qty, spec.lot_size)
    if rounded_qty <= 0:
        return False, "INSTRUMENT_RULE: qty rounds to zero under lot_size", Decimal("0")
    px = round_to_tick(price, spec.tick_size)
    notional = compute_notional(rounded_qty, px, multiplier=spec)
    min_n = Decimal(str(spec.min_notional))
    if notional < min_n:
        return False, f"INSTRUMENT_RULE: notional {notional} < min_notional {min_n}", rounded_qty
    if opening_short:
        policy = short_margin_policy
        if isinstance(policy, dict):
            policy = ShortMarginPolicy.from_dict(policy)
        ok, reason = short_open_allowed(
            supports_short=spec.supports_short,
            margin_policy=policy,
            borrow=spec.borrow,
        )
        if not ok:
            return False, reason, rounded_qty
    return True, "ok", rounded_qty


def equity_session_is_open(
    spec: InstrumentSpec,
    date: str,
    *,
    universe: Any | None = None,
) -> dict[str, Any]:
    """Session calendar hook for equity/ETF (W08). Missing calendar ⇒ default open + UNMEASURED."""
    from .universe import PointInTimeUniverse

    calendar_id = spec.session_calendar_id or "UNMEASURED"
    if universe is None:
        return {
            "date": date,
            "isOpen": True,
            "sessionCalendarId": calendar_id,
            "status": "UNMEASURED",
            "truth": {"missing_calendar_defaults_open_labelled": True},
        }
    uni = universe if isinstance(universe, PointInTimeUniverse) else universe
    open_ = bool(uni.is_trading_day(date, exchange=spec.venue))
    return {
        "date": date,
        "isOpen": open_,
        "sessionCalendarId": calendar_id,
        "status": "MEASURED" if uni.calendar else "UNMEASURED",
        "truth": {"missing_calendar_defaults_open_labelled": not bool(uni.calendar)},
    }
