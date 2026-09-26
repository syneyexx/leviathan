"""FX spot instrument helpers (institutional W09).

Currency-pair model and pip conventions. Trading remains fail-closed until
the family is explicitly enabled in SUPPORTED_SIM_FAMILIES.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


MAJOR_CCY = frozenset({"USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD"})


@dataclass(frozen=True)
class CurrencyPair:
    base: str
    quote: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "base", self.base.upper())
        object.__setattr__(self, "quote", self.quote.upper())

    @property
    def symbol(self) -> str:
        return f"{self.base}{self.quote}"

    @classmethod
    def parse(cls, symbol: str) -> "CurrencyPair":
        raw = (symbol or "").upper().replace("/", "").replace("-", "").strip()
        if len(raw) == 6 and raw.isalpha():
            return cls(base=raw[:3], quote=raw[3:])
        raise ValueError(f"not a currency pair symbol: {symbol!r}")

    def pip_size(self) -> Decimal:
        # JPY pairs traditionally 0.01 pip; others 0.0001.
        if self.quote == "JPY" or self.base == "JPY":
            return Decimal("0.01")
        return Decimal("0.0001")

    def default_tick_size(self) -> str:
        return str(self.pip_size())

    def public_dict(self) -> dict[str, Any]:
        return {
            "base": self.base,
            "quote": self.quote,
            "symbol": self.symbol,
            "pipSize": str(self.pip_size()),
            "truth": {
                "fx_pair_is_not_equity_ticker": True,
                "ohlcv_is_not_orderbook": True,
            },
        }


def fx_notional(qty: Any, price: Any, *, pair: CurrencyPair | None = None) -> Decimal:
    """Spot FX notional in quote currency (qty × price). No leverage invented."""
    _ = pair
    return Decimal(str(qty)) * Decimal(str(price))


def is_likely_fx_symbol(symbol: str) -> bool:
    try:
        pair = CurrencyPair.parse(symbol)
    except ValueError:
        return False
    return pair.base in MAJOR_CCY and pair.quote in MAJOR_CCY and pair.base != pair.quote
