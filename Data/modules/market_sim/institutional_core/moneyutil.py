"""Currency-safe monetary helpers for institutional accounting.

Reuses market_sim.accounting Decimal semantics — does not invent a second money type.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any, Mapping

from ..accounting import D, MONEY_QUANT, ZERO, money


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", money(self.amount))
        object.__setattr__(self, "currency", str(self.currency or "").upper())
        if not self.currency:
            raise ValueError("currency required")

    def public_dict(self) -> dict[str, Any]:
        return {"amount": str(self.amount), "currency": self.currency}

    def __add__(self, other: "Money") -> "Money":
        _same_ccy(self, other)
        return Money(money(self.amount + other.amount), self.currency)

    def __sub__(self, other: "Money") -> "Money":
        _same_ccy(self, other)
        return Money(money(self.amount - other.amount), self.currency)

    def __neg__(self) -> "Money":
        return Money(money(-self.amount), self.currency)


def _same_ccy(a: Money, b: Money) -> None:
    if a.currency != b.currency:
        raise ValueError(f"currency mismatch: {a.currency} vs {b.currency}")


def as_money(amount: Any, currency: str) -> Money:
    return Money(money(amount), currency)


def require_currency(value: str | None, *, default: str | None = None) -> str:
    ccy = str(value or default or "").upper().strip()
    if not ccy:
        raise ValueError("currency required — silent USD default forbidden for accounting")
    return ccy


def convert(
    amount: Any,
    *,
    from_currency: str,
    to_currency: str,
    fx_rate: Any | None,
) -> Money:
    """Convert with explicit FX. Missing FX never silently becomes 1.0."""
    src = require_currency(from_currency)
    dst = require_currency(to_currency)
    amt = money(amount)
    if src == dst:
        return Money(amt, dst)
    if fx_rate is None:
        raise ValueError(f"missing FX rate {src}/{dst}")
    rate = D(fx_rate)
    if rate <= ZERO:
        raise ValueError(f"invalid FX rate {src}/{dst}: {fx_rate}")
    return Money(money(amt * rate), dst)


def round_money(amount: Any, *, quant: Decimal = MONEY_QUANT) -> Decimal:
    return D(amount).quantize(quant, rounding=ROUND_HALF_EVEN)


def money_map_add(
    balances: dict[str, Decimal],
    currency: str,
    delta: Any,
) -> dict[str, Decimal]:
    ccy = require_currency(currency)
    out = dict(balances)
    out[ccy] = money(out.get(ccy, ZERO) + money(delta))
    return out


def assert_no_silent_mix(
    left_currency: str,
    right_currency: str,
    *,
    context: str = "operation",
) -> None:
    if require_currency(left_currency) != require_currency(right_currency):
        raise ValueError(
            f"currency mix refused in {context}: "
            f"{left_currency} vs {right_currency}"
        )


def parse_money_fields(payload: Mapping[str, Any], *keys: str) -> dict[str, Decimal]:
    return {k: money(payload.get(k) or 0) for k in keys}
