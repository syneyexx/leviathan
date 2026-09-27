"""Capacity evidence for Q09 — wraps institutional liquidity owner.

Does not invent exact market impact from volume-only data.
Uncalibrated impact remains ASSUMED/ESTIMATED, never MEASURED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .institutional_core.liquidity import days_to_liquidate, evaluate_liquidity
from .institutional_core.status import MeasurementState


@dataclass(frozen=True)
class CapacityEvidence:
    state: str
    participation_pct: float | None
    days_to_liquidate: float | None
    adv: float | None
    order_notional: float | None
    turnover: float | None
    liquidity_bucket: str | None
    impact_method: str
    impact_state: str
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "participation_pct": self.participation_pct,
            "days_to_liquidate": self.days_to_liquidate,
            "adv": self.adv,
            "order_notional": self.order_notional,
            "turnover": self.turnover,
            "liquidity_bucket": self.liquidity_bucket,
            "impact_method": self.impact_method,
            "impact_state": self.impact_state,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "evidence": dict(self.evidence),
            "truth": {
                "volume_only_not_exact_impact": True,
                "uncalibrated_impact_not_measured": True,
            },
        }


def estimate_bar_capacity(
    *,
    capital: float,
    avg_daily_volume: float | None,
    price: float | None,
    turnover: float | None = None,
    max_participation_pct: float = 10.0,
    max_days_to_liquidate: float | None = 5.0,
    impact_calibrated: bool = False,
) -> CapacityEvidence:
    """Estimate capacity at qualification capital scale from OHLCV volume."""
    blockers: list[str] = []
    warnings: list[str] = []
    if avg_daily_volume is None or avg_daily_volume <= 0 or price is None or price <= 0:
        return CapacityEvidence(
            state=MeasurementState.UNMEASURED.value,
            participation_pct=None,
            days_to_liquidate=None,
            adv=avg_daily_volume,
            order_notional=capital if capital else None,
            turnover=turnover,
            liquidity_bucket=None,
            impact_method="bar_volume_participation_v1",
            impact_state=MeasurementState.UNMEASURED.value,
            blockers=["CAPACITY_UNMEASURED"],
            warnings=["missing_adv_or_price"],
        )

    notional = float(capital)
    share_qty = notional / float(price) if price else 0.0
    dtl = days_to_liquidate(
        share_qty,
        float(avg_daily_volume),
        participation_limit=max_participation_pct / 100.0,
    )
    dtl_val = dtl.value
    participation = (
        (share_qty / float(avg_daily_volume)) * 100.0 if avg_daily_volume else None
    )
    impact_state = (
        MeasurementState.ESTIMATED.value
        if impact_calibrated
        else MeasurementState.ASSUMED.value
    )
    if not impact_calibrated:
        warnings.append("impact_uncalibrated_ASSUMED")

    bucket = "deep"
    if participation is not None:
        if participation > max_participation_pct:
            bucket = "constrained"
            blockers.append("CAPACITY_EXCEEDED")
        elif participation > max_participation_pct * 0.5:
            bucket = "moderate"

    if (
        max_days_to_liquidate is not None
        and dtl_val is not None
        and float(dtl_val) > float(max_days_to_liquidate)
    ):
        blockers.append("CAPACITY_EXCEEDED")

    if blockers:
        state = MeasurementState.FAIL.value
    elif dtl.state in {
        MeasurementState.UNMEASURED,
        MeasurementState.INSUFFICIENT_HISTORY,
    }:
        state = dtl.state.value
        blockers.append("CAPACITY_UNMEASURED")
    else:
        state = MeasurementState.OBSERVED.value

    return CapacityEvidence(
        state=state,
        participation_pct=participation,
        days_to_liquidate=float(dtl_val) if dtl_val is not None else None,
        adv=float(avg_daily_volume),
        order_notional=notional,
        turnover=turnover,
        liquidity_bucket=bucket,
        impact_method="bar_volume_participation_v1",
        impact_state=impact_state,
        blockers=blockers,
        warnings=warnings,
        evidence={
            "dtl": dtl.public_dict() if hasattr(dtl, "public_dict") else str(dtl),
            "max_participation_pct": max_participation_pct,
            "max_days_to_liquidate": max_days_to_liquidate,
        },
    )


def capacity_from_liquidity_inputs(
    positions: Sequence[Mapping[str, Any]],
    *,
    capital: float,
    max_participation_pct: float = 10.0,
) -> CapacityEvidence:
    """Aggregate multi-symbol liquidity into qualification capacity evidence."""
    report = evaluate_liquidity(list(positions))
    worst = None
    for item in report.items:
        dtl = item.days_to_liquidate
        if dtl.value is None:
            continue
        if worst is None or float(dtl.value) > float(worst):
            worst = float(dtl.value)
    if worst is None:
        return CapacityEvidence(
            state=MeasurementState.UNMEASURED.value,
            participation_pct=None,
            days_to_liquidate=None,
            adv=None,
            order_notional=capital,
            turnover=None,
            liquidity_bucket=None,
            impact_method="liquidity_report_aggregate_v1",
            impact_state=MeasurementState.UNMEASURED.value,
            blockers=["CAPACITY_UNMEASURED"],
        )
    blockers = []
    if worst > 5.0:
        blockers.append("CAPACITY_EXCEEDED")
    return CapacityEvidence(
        state=MeasurementState.FAIL.value if blockers else MeasurementState.OBSERVED.value,
        participation_pct=max_participation_pct,
        days_to_liquidate=worst,
        adv=None,
        order_notional=capital,
        turnover=None,
        liquidity_bucket="aggregated",
        impact_method="liquidity_report_aggregate_v1",
        impact_state=MeasurementState.ASSUMED.value,
        blockers=blockers,
        warnings=["impact_uncalibrated_ASSUMED"],
        evidence={"liquidity_report": report.public_dict()},
    )
