from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TradingOrderResult:
    accepted: bool
    detail: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "detail": self.detail,
            "truth": {
                "trading_disabled_by_default": True,
                "no_fabricated_fills": True,
            },
        }


class TradingStub:
    """Trading domain stub — always refused unless explicitly implemented later."""

    def place_order(self, *, symbol: str, side: str, quantity: float) -> TradingOrderResult:
        return TradingOrderResult(
            accepted=False,
            detail=(
                f"Trading runtime not implemented; refused {side} {quantity} {symbol}. "
                "No fills fabricated."
            ),
        )
