"""Instrument / market model — honest capability claims per family."""

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


@dataclass(frozen=True)
class InstrumentSpec:
    instrument_id: str
    symbol: str
    family: InstrumentFamily
    venue: str
    quote_currency: str
    timezone: str = "UTC"
    tick_size: str = "0.01"
    lot_size: str = "0.0001"
    min_notional: str = "1"
    supports_short: bool = False
    data_level: DataLevel = DataLevel.OHLCV
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "family": self.family.value,
            "venue": self.venue,
            "quote_currency": self.quote_currency,
            "timezone": self.timezone,
            "tick_size": self.tick_size,
            "lot_size": self.lot_size,
            "min_notional": self.min_notional,
            "supports_short": self.supports_short,
            "data_level": self.data_level.value,
            "metadata": self.metadata,
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
)


def infer_family(
    symbol: str,
    *,
    venue: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> InstrumentFamily:
    """Infer family. Explicit metadata.family is never silently overwritten."""
    meta = metadata or {}
    if meta.get("family") is not None:
        try:
            return InstrumentFamily(str(meta["family"]))
        except ValueError as exc:
            raise ValueError(f"INSTRUMENT_RULE: unknown family {meta['family']!r}") from exc
    sym = symbol.upper().replace("/", "").replace("-", "")
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
    if family == InstrumentFamily.CRYPTO_SPOT:
        return InstrumentSpec(
            instrument_id=f"crypto_spot:{symbol.upper()}:{meta.get('venue') or 'BINANCE'}",
            symbol=symbol.upper(),
            family=family,
            venue=str(meta.get("venue") or "BINANCE"),
            quote_currency=str(meta.get("quote_currency") or "USDT"),
            timezone="UTC",
            tick_size=str(meta.get("tick_size") or "0.01"),
            lot_size=str(meta.get("lot_size") or "0.0001"),
            min_notional=str(meta.get("min_notional") or "10"),
            supports_short=supports_short,
            metadata={"timeframe": timeframe, **meta},
        )
    if family in {InstrumentFamily.OPTIONS, InstrumentFamily.FUTURES, InstrumentFamily.FOREX}:
        return InstrumentSpec(
            instrument_id=f"{family.value}:{symbol.upper()}:{meta.get('venue') or 'UNKNOWN'}",
            symbol=symbol.upper(),
            family=family,
            venue=str(meta.get("venue") or "UNKNOWN"),
            quote_currency=str(meta.get("quote_currency") or "USD"),
            timezone=str(meta.get("timezone") or "UTC"),
            tick_size=str(meta.get("tick_size") or "0.01"),
            lot_size=str(meta.get("lot_size") or "1"),
            min_notional=str(meta.get("min_notional") or "1"),
            supports_short=supports_short,
            metadata={"timeframe": timeframe, "capability": "NOT_IMPLEMENTED", **meta},
        )
    return InstrumentSpec(
        instrument_id=f"equity:{symbol.upper()}:{meta.get('venue') or 'NASDAQ'}",
        symbol=symbol.upper(),
        family=InstrumentFamily.EQUITY,
        venue=str(meta.get("venue") or "NASDAQ"),
        quote_currency=str(meta.get("quote_currency") or "USD"),
        timezone=str(meta.get("timezone") or "America/New_York"),
        tick_size=str(meta.get("tick_size") or "0.01"),
        lot_size=str(meta.get("lot_size") or "1"),
        min_notional=str(meta.get("min_notional") or "1"),
        supports_short=supports_short,
        metadata={"timeframe": timeframe, **meta},
    )


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

    rounded_qty = round_to_lot(qty, spec.lot_size)
    if rounded_qty <= 0:
        return False, "INSTRUMENT_RULE: qty rounds to zero under lot_size", Decimal("0")
    px = round_to_tick(price, spec.tick_size)
    notional = rounded_qty * px
    min_n = Decimal(str(spec.min_notional))
    if notional < min_n:
        return False, f"INSTRUMENT_RULE: notional {notional} < min_notional {min_n}", rounded_qty
    if opening_short:
        policy = short_margin_policy
        if isinstance(policy, dict):
            policy = ShortMarginPolicy.from_dict(policy)
        ok, reason = short_open_allowed(supports_short=spec.supports_short, margin_policy=policy)
        if not ok:
            return False, reason, rounded_qty
    return True, "ok", rounded_qty
