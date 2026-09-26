"""Futures and crypto perpetual contract model (institutional W10).

Multiplier-aware notional; funding rate remains UNMEASURED unless provided.
Family may still be NOT_IMPLEMENTED for live trading — enum ≠ support.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class FuturesContractSpec:
    symbol: str
    venue: str
    multiplier: str = "1"
    tick_size: str = "0.01"
    is_perpetual: bool = False
    quote_currency: str = "USD"
    settlement_currency: str | None = None
    funding_rate_per_8h: float | None = None  # None => UNMEASURED
    underlying: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def funding_status(self) -> str:
        return "MEASURED" if self.funding_rate_per_8h is not None else "UNMEASURED"

    def notional(self, qty: Any, price: Any) -> Decimal:
        return Decimal(str(qty)) * Decimal(str(price)) * Decimal(str(self.multiplier))

    def public_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "venue": self.venue,
            "multiplier": self.multiplier,
            "tickSize": self.tick_size,
            "isPerpetual": self.is_perpetual,
            "quoteCurrency": self.quote_currency,
            "settlementCurrency": self.settlement_currency or self.quote_currency,
            "fundingRatePer8h": self.funding_rate_per_8h,
            "fundingStatus": self.funding_status(),
            "underlying": self.underlying,
            "metadata": dict(self.metadata),
            "truth": {
                "funding_unset_is_UNMEASURED": self.funding_rate_per_8h is None,
                "multiplier_required_for_contract_notional": True,
                "perp_is_not_spot": self.is_perpetual,
            },
        }


ES_CME = FuturesContractSpec(
    symbol="ES",
    venue="CME",
    multiplier="50",
    tick_size="0.25",
    is_perpetual=False,
    underlying="SPX",
)

BTCUSDT_PERP = FuturesContractSpec(
    symbol="BTCUSDT",
    venue="BINANCE",
    multiplier="1",
    tick_size="0.1",
    is_perpetual=True,
    quote_currency="USDT",
    underlying="BTC",
)
