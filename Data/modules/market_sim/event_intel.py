"""Fundamental / corporate / event intelligence (institutional W15).

PIT observations with available_at fail-closed filtering. Does not invent
fundamentals or auto-adjust prices — labels honesty only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .epistemic import is_available, resolve_available_at
from .universe import CorporateAction


@dataclass(frozen=True)
class FundamentalObservation:
    symbol: str
    metric: str  # e.g. eps, revenue, pe
    value: float | None
    event_ts: str
    available_at: str
    source: str = "UNMEASURED"
    unit: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "metric": self.metric,
            "value": self.value,
            "eventTs": self.event_ts,
            "availableAt": self.available_at,
            "source": self.source,
            "unit": self.unit,
            "metadata": dict(self.metadata),
            "truth": {
                "available_at_is_primary_boundary": True,
                "fundamentals_not_invented": self.value is None or self.source != "invented",
            },
        }


@dataclass(frozen=True)
class EarningsEvent:
    symbol: str
    period: str
    event_ts: str
    available_at: str
    eps_actual: float | None = None
    eps_estimate: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "period": self.period,
            "eventTs": self.event_ts,
            "availableAt": self.available_at,
            "epsActual": self.eps_actual,
            "epsEstimate": self.eps_estimate,
            "surprise": (
                None
                if self.eps_actual is None or self.eps_estimate is None
                else self.eps_actual - self.eps_estimate
            ),
            "metadata": dict(self.metadata),
            "truth": {"available_at_is_primary_boundary": True},
        }


def filter_fundamentals_as_of(
    rows: Sequence[FundamentalObservation],
    *,
    as_of: str,
) -> list[FundamentalObservation]:
    kept: list[FundamentalObservation] = []
    for row in rows:
        if not row.available_at:
            continue
        if is_available(available_at=row.available_at, as_of=as_of):
            kept.append(row)
    return kept


def filter_earnings_as_of(
    rows: Sequence[EarningsEvent],
    *,
    as_of: str,
) -> list[EarningsEvent]:
    return [
        r
        for r in rows
        if r.available_at and is_available(available_at=r.available_at, as_of=as_of)
    ]


def corporate_actions_as_of(
    actions: Sequence[CorporateAction],
    *,
    symbol: str,
    as_of: str,
) -> list[CorporateAction]:
    return [
        a
        for a in actions
        if a.symbol == symbol and a.effective_at <= as_of
    ]


def build_event_intelligence_bundle(
    *,
    as_of: str,
    fundamentals: Sequence[FundamentalObservation] | None = None,
    earnings: Sequence[EarningsEvent] | None = None,
    corporate_actions: Sequence[CorporateAction] | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Operator-facing PIT event pack for MarketState.events."""
    funds = filter_fundamentals_as_of(list(fundamentals or []), as_of=as_of)
    earns = filter_earnings_as_of(list(earnings or []), as_of=as_of)
    cas = list(corporate_actions or [])
    if symbol:
        funds = [f for f in funds if f.symbol == symbol]
        earns = [e for e in earns if e.symbol == symbol]
        cas = corporate_actions_as_of(cas, symbol=symbol, as_of=as_of)
    else:
        cas = [a for a in cas if a.effective_at <= as_of]
    return {
        "asOf": as_of,
        "fundamentals": [f.public_dict() for f in funds],
        "earnings": [e.public_dict() for e in earns],
        "corporateActions": [a.public_dict() for a in cas],
        "counts": {
            "fundamentals": len(funds),
            "earnings": len(earns),
            "corporateActions": len(cas),
        },
        "truth": {
            "available_at_fail_closed": True,
            "no_auto_price_adjustment": True,
            "fundamentals_pipeline_partial": True,
        },
    }


def filter_news_records_as_of(
    records: Sequence[dict[str, Any]],
    *,
    as_of: str,
) -> list[dict[str, Any]]:
    """Fail-closed news/event dict filter via available_at."""
    kept: list[dict[str, Any]] = []
    for row in records:
        available = resolve_available_at(row)
        if available is None:
            continue
        if is_available(available_at=available, as_of=as_of):
            kept.append(dict(row))
    return kept
