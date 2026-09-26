"""W47 — Liquidity: ADV / days-to-liquidate with explicit measurement states."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, StatusedValue, DEFAULT_TRUTH


@dataclass
class LiquidityInput:
    instrument_id: str
    qty: float
    adv: float | None = None  # average daily volume in shares/units
    participation_limit: float = 0.1  # fraction of ADV

    def public_dict(self) -> dict[str, Any]:
        return {
            "instrumentId": self.instrument_id,
            "qty": self.qty,
            "adv": self.adv,
            "participationLimit": self.participation_limit,
        }


@dataclass
class LiquidityMetric:
    instrument_id: str
    adv: StatusedValue
    days_to_liquidate: StatusedValue
    notes: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "instrumentId": self.instrument_id,
            "adv": self.adv.public_dict(),
            "daysToLiquidate": self.days_to_liquidate.public_dict(),
            "notes": list(self.notes),
            "truth": DEFAULT_TRUTH.public_dict(),
        }


@dataclass
class LiquidityReport:
    items: list[LiquidityMetric]
    portfolio_days_to_liquidate: StatusedValue
    status: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "items": [i.public_dict() for i in self.items],
            "portfolioDaysToLiquidate": self.portfolio_days_to_liquidate.public_dict(),
            "status": self.status,
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "adv_absence_is_UNMEASURED_not_zero": True,
            },
        }


def days_to_liquidate(
    qty: float,
    adv: float | None,
    *,
    participation_limit: float = 0.1,
) -> StatusedValue:
    if adv is None:
        return StatusedValue(
            None,
            MeasurementState.UNMEASURED,
            methodology="days_to_liquidate_adv_participation",
            notes=["adv_UNMEASURED"],
        )
    if adv <= 0:
        return StatusedValue(
            None,
            MeasurementState.INFEASIBLE,
            methodology="days_to_liquidate_adv_participation",
            notes=["adv_non_positive"],
        )
    if participation_limit <= 0:
        return StatusedValue(
            None,
            MeasurementState.INFEASIBLE,
            methodology="days_to_liquidate_adv_participation",
            notes=["participation_limit_non_positive"],
        )
    capacity = adv * participation_limit
    days = abs(float(qty)) / capacity
    return StatusedValue(
        days,
        MeasurementState.ESTIMATED,
        unit="days",
        methodology="days_to_liquidate_adv_participation",
        notes=["participation_limit_ASSUMED"] if participation_limit == 0.1 else [],
    )


def evaluate_liquidity(
    positions: Sequence[LiquidityInput | Mapping[str, Any]],
) -> LiquidityReport:
    items: list[LiquidityMetric] = []
    day_values: list[float] = []
    states: list[str] = []

    for raw in positions:
        if isinstance(raw, LiquidityInput):
            inp = raw
        else:
            inp = LiquidityInput(
                instrument_id=str(raw.get("instrument_id") or raw.get("instrumentId") or ""),
                qty=float(raw.get("qty") or 0),
                adv=(
                    None
                    if raw.get("adv") is None
                    else float(raw.get("adv"))
                ),
                participation_limit=float(
                    raw.get("participation_limit") or raw.get("participationLimit") or 0.1
                ),
            )
        adv_sv = (
            StatusedValue(inp.adv, MeasurementState.OBSERVED, unit="units/day", methodology="ADV")
            if inp.adv is not None
            else StatusedValue(None, MeasurementState.UNMEASURED, methodology="ADV")
        )
        dtl = days_to_liquidate(inp.qty, inp.adv, participation_limit=inp.participation_limit)
        notes: list[str] = []
        if inp.adv is None:
            notes.append("cannot_compute_days_without_ADV")
        items.append(
            LiquidityMetric(
                instrument_id=inp.instrument_id,
                adv=adv_sv,
                days_to_liquidate=dtl,
                notes=notes,
            )
        )
        states.append(dtl.state.value)
        if dtl.value is not None:
            day_values.append(float(dtl.value))

    if not items:
        portfolio = StatusedValue(None, MeasurementState.EMPTY, methodology="max_days_to_liquidate")
        status = MeasurementState.EMPTY.value
    elif any(s == MeasurementState.UNMEASURED.value for s in states):
        portfolio = StatusedValue(
            max(day_values) if day_values else None,
            MeasurementState.UNMEASURED if not day_values else MeasurementState.ESTIMATED,
            methodology="max_days_to_liquidate",
            notes=["portfolio_rollup_partial_when_some_ADV_missing"],
        )
        status = MeasurementState.UNMEASURED.value
    else:
        portfolio = StatusedValue(
            max(day_values) if day_values else None,
            MeasurementState.ESTIMATED,
            unit="days",
            methodology="max_days_to_liquidate",
        )
        status = MeasurementState.ESTIMATED.value

    return LiquidityReport(items=items, portfolio_days_to_liquidate=portfolio, status=status)
