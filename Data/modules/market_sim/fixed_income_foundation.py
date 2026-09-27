"""Fixed-income research foundation — accrual, clean/dirty, yield, DV01 honesty.

Paper support remains NOT_IMPLEMENTED until pricing/data semantics are proven.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .fixed_income import FixedIncomeSpec


DAY_COUNT_CONVENTIONS = frozenset(
    {
        "ACT/360",
        "ACT/365",
        "30/360",
        "ACT/ACT",
        "UNMEASURED",
    }
)


@dataclass(frozen=True)
class BondAnalytics:
    symbol: str
    clean_price: str | None
    dirty_price: str | None
    yield_to_maturity: float | None
    duration: float | None
    modified_duration: float | None
    dv01: float | None
    convexity: float | None
    accrued_interest: float | None
    day_count: str
    status: str
    gaps: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "cleanPrice": self.clean_price,
            "dirtyPrice": self.dirty_price,
            "yieldToMaturity": self.yield_to_maturity,
            "duration": self.duration,
            "modifiedDuration": self.modified_duration,
            "dv01": self.dv01,
            "convexity": self.convexity,
            "accruedInterest": self.accrued_interest,
            "dayCount": self.day_count,
            "status": self.status,
            "gaps": list(self.gaps),
            "metadata": dict(self.metadata),
            "truth": {
                "unset_is_UNMEASURED_not_zero": True,
                "fixed_income_paper": "NOT_IMPLEMENTED",
                "live_money": "BLOCKED",
            },
        }


def compute_bond_analytics(
    spec: FixedIncomeSpec,
    *,
    clean_price: Any | None = None,
) -> BondAnalytics:
    """Compute what can be measured; leave gaps as UNMEASURED (never invent zeros)."""
    gaps: list[str] = []
    day_count = spec.day_count if spec.day_count in DAY_COUNT_CONVENTIONS else "UNMEASURED"
    if day_count == "UNMEASURED":
        gaps.append("day_count_UNMEASURED")

    accrued = spec.accrued_interest
    if accrued is None:
        gaps.append("accrued_interest_UNMEASURED")

    dirty = None
    clean_s = None
    if clean_price is not None:
        clean_s = str(clean_price)
        dirty_res = spec.dirty_price(clean_price)
        dirty = dirty_res.get("dirtyPrice")
        if dirty_res.get("status") != "MEASURED":
            gaps.append("dirty_price_UNMEASURED")
    else:
        gaps.append("clean_price_UNMEASURED")

    ytm = spec.yield_to_maturity
    if ytm is None:
        gaps.append("yield_UNMEASURED")

    duration = spec.duration
    if duration is None:
        gaps.append("duration_UNMEASURED")

    mod_dur = None
    dv01 = None
    if duration is not None and ytm is not None:
        # Modified duration ≈ MacD / (1+y) — approximate; labeled as such.
        mod_dur = float(duration) / (1.0 + float(ytm))
        if clean_price is not None:
            try:
                dv01 = mod_dur * float(Decimal(str(clean_price))) * 0.0001
            except Exception:  # noqa: BLE001
                gaps.append("dv01_UNMEASURED")
        else:
            gaps.append("dv01_requires_clean_price")
    else:
        gaps.append("dv01_UNMEASURED")
        gaps.append("modified_duration_UNMEASURED")

    convexity = None
    if "convexity" in (spec.metadata or {}):
        try:
            convexity = float(spec.metadata["convexity"])
        except (TypeError, ValueError):
            gaps.append("convexity_UNMEASURED")
    else:
        gaps.append("convexity_UNMEASURED")

    status = "MEASURED" if not gaps else ("PARTIAL" if clean_s or ytm is not None else "UNMEASURED")
    return BondAnalytics(
        symbol=spec.symbol,
        clean_price=clean_s,
        dirty_price=str(dirty) if dirty is not None else None,
        yield_to_maturity=ytm,
        duration=duration,
        modified_duration=mod_dur,
        dv01=dv01,
        convexity=convexity,
        accrued_interest=accrued,
        day_count=day_count,
        status=status,
        gaps=tuple(gaps),
        metadata={"callability": (spec.metadata or {}).get("callability", "UNMEASURED")},
    )


def fixed_income_paper_capability() -> dict[str, Any]:
    return {
        "HISTORICAL_RESEARCH": "NOT_IMPLEMENTED",
        "SHADOW": "NOT_IMPLEMENTED",
        "AUTONOMOUS_PAPER": "NOT_IMPLEMENTED",
        "reason": "pricing_data_semantics_not_proven_for_paper",
        "truth": {
            "identity_exists": True,
            "analytics_unset_UNMEASURED": True,
            "no_fake_paper_support": True,
            "live_money": "BLOCKED",
        },
    }
