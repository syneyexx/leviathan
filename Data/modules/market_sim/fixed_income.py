"""Fixed income instrument model (institutional W12).

Yield/duration/accrual remain UNMEASURED unless supplied. No silent equity
treatment of bonds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class FixedIncomeSpec:
    symbol: str
    venue: str = "OTC"
    face_value: str = "1000"
    coupon_rate: float | None = None
    maturity: str | None = None  # ISO date
    yield_to_maturity: float | None = None
    duration: float | None = None
    accrued_interest: float | None = None
    quote_currency: str = "USD"
    day_count: str = "UNMEASURED"
    metadata: dict[str, Any] = field(default_factory=dict)

    def analytics_status(self) -> str:
        measured = [
            self.coupon_rate is not None,
            self.yield_to_maturity is not None,
            self.duration is not None,
            self.accrued_interest is not None,
        ]
        if all(measured):
            return "MEASURED"
        if any(measured):
            return "PARTIAL"
        return "UNMEASURED"

    def dirty_price(self, clean_price: Any) -> dict[str, Any]:
        if self.accrued_interest is None:
            return {
                "cleanPrice": str(clean_price),
                "dirtyPrice": None,
                "status": "UNMEASURED",
                "reason": "accrued_interest_UNMEASURED",
            }
        dirty = Decimal(str(clean_price)) + Decimal(str(self.accrued_interest))
        return {
            "cleanPrice": str(clean_price),
            "dirtyPrice": str(dirty),
            "status": "MEASURED",
            "reason": "accrued_added",
        }

    def public_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "venue": self.venue,
            "faceValue": self.face_value,
            "couponRate": self.coupon_rate,
            "maturity": self.maturity,
            "yieldToMaturity": self.yield_to_maturity,
            "duration": self.duration,
            "accruedInterest": self.accrued_interest,
            "quoteCurrency": self.quote_currency,
            "dayCount": self.day_count,
            "analyticsStatus": self.analytics_status(),
            "metadata": dict(self.metadata),
            "truth": {
                "fixed_income_is_not_equity": True,
                "unset_yield_duration_is_UNMEASURED": self.analytics_status() != "MEASURED",
                "enum_exists_is_not_market_support": True,
            },
        }


US10Y = FixedIncomeSpec(
    symbol="US10Y",
    venue="OTC",
    face_value="1000",
    coupon_rate=None,
    maturity=None,
)
