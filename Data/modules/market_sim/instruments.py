"""Instrument / market model — honest capability claims per family."""

from __future__ import annotations

from dataclasses import dataclass, field
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


# Well-known instruments for demos / tests
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


def infer_family(symbol: str, *, venue: str | None = None, metadata: dict[str, Any] | None = None) -> InstrumentFamily:
    meta = metadata or {}
    if meta.get("family"):
        try:
            return InstrumentFamily(str(meta["family"]))
        except ValueError:
            pass
    sym = symbol.upper().replace("/", "").replace("-", "")
    if venue and venue.upper() in {"BINANCE", "COINBASE", "KRAKEN"}:
        return InstrumentFamily.CRYPTO_SPOT
    if sym.endswith("USDT") or sym.endswith("USDC") or sym.endswith("BTC") and len(sym) > 6:
        return InstrumentFamily.CRYPTO_SPOT
    if sym in {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"}:
        return InstrumentFamily.CRYPTO_SPOT
    return InstrumentFamily.EQUITY


def spec_for_symbol(symbol: str, *, timeframe: str = "1h", metadata: dict[str, Any] | None = None) -> InstrumentSpec:
    meta = dict(metadata or {})
    family = infer_family(symbol, venue=meta.get("venue"), metadata=meta)
    if family == InstrumentFamily.CRYPTO_SPOT:
        return InstrumentSpec(
            instrument_id=f"crypto_spot:{symbol.upper()}:BINANCE",
            symbol=symbol.upper(),
            family=family,
            venue=str(meta.get("venue") or "BINANCE"),
            quote_currency=str(meta.get("quote_currency") or "USDT"),
            timezone="UTC",
            tick_size=str(meta.get("tick_size") or "0.01"),
            lot_size=str(meta.get("lot_size") or "0.0001"),
            min_notional=str(meta.get("min_notional") or "10"),
            metadata={"timeframe": timeframe, **meta},
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
        metadata={"timeframe": timeframe, **meta},
    )
