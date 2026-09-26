"""Options contract model (institutional W11).

Greeks and vol surface are UNMEASURED unless explicitly supplied.
Trading stays NOT_IMPLEMENTED — this module is identity/spec only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OptionContractSpec:
    symbol: str
    underlying: str
    right: str  # call | put
    strike: str
    expiry: str  # ISO date
    venue: str = "UNKNOWN"
    multiplier: str = "100"
    quote_currency: str = "USD"
    style: str = "american"  # american | european
    implied_vol: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def greeks_status(self) -> str:
        if any(v is not None for v in (self.delta, self.gamma, self.theta, self.vega, self.implied_vol)):
            return "PARTIAL" if None in (self.delta, self.gamma, self.theta, self.vega, self.implied_vol) else "MEASURED"
        return "UNMEASURED"

    def public_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "underlying": self.underlying,
            "right": self.right.lower(),
            "strike": self.strike,
            "expiry": self.expiry,
            "venue": self.venue,
            "multiplier": self.multiplier,
            "quoteCurrency": self.quote_currency,
            "style": self.style,
            "impliedVol": self.implied_vol,
            "delta": self.delta,
            "gamma": self.gamma,
            "theta": self.theta,
            "vega": self.vega,
            "greeksStatus": self.greeks_status(),
            "metadata": dict(self.metadata),
            "truth": {
                "greeks_unset_is_UNMEASURED": self.greeks_status() == "UNMEASURED",
                "options_require_contract_rules": True,
                "enum_exists_is_not_market_support": True,
            },
        }


def parse_option_right(raw: str) -> str:
    text = (raw or "").strip().lower()
    if text in {"c", "call"}:
        return "call"
    if text in {"p", "put"}:
        return "put"
    raise ValueError(f"unknown option right: {raw!r}")
