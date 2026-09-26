"""W44 — Performance: TWR / MWR / attribution with honest methodology labels.

Extends portefeuille.attribution — contribution ≠ Brinson.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, StatusedValue, DEFAULT_TRUTH


@dataclass(frozen=True)
class Cashflow:
    ts: str
    amount: float  # positive = contribution in; negative = withdrawal

    def public_dict(self) -> dict[str, Any]:
        return {"ts": self.ts, "amount": self.amount}


@dataclass
class PerformanceReport:
    method: str
    twr: StatusedValue
    mwr: StatusedValue
    simple_return: StatusedValue
    attribution: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "twr": self.twr.public_dict(),
            "mwr": self.mwr.public_dict(),
            "simpleReturn": self.simple_return.public_dict(),
            "attribution": dict(self.attribution),
            "notes": list(self.notes),
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "not_brinson_factor_attribution": True,
                "methodology_labelled": True,
            },
        }


def simple_period_return(start_value: float, end_value: float) -> StatusedValue:
    if start_value == 0:
        return StatusedValue(
            None,
            MeasurementState.INFEASIBLE,
            methodology="simple_return",
            notes=["start_value_zero"],
        )
    return StatusedValue(
        (end_value - start_value) / start_value,
        MeasurementState.MEASURED,
        unit="fraction",
        methodology="simple_return",
    )


def time_weighted_return(
    period_returns: Sequence[float],
) -> StatusedValue:
    """Geometric chain of sub-period returns: Π(1+r_i) - 1."""
    if not period_returns:
        return StatusedValue(
            None,
            MeasurementState.EMPTY,
            methodology="TWR_geometric_chain",
            notes=["no_period_returns"],
        )
    growth = 1.0
    for r in period_returns:
        growth *= 1.0 + float(r)
    return StatusedValue(
        growth - 1.0,
        MeasurementState.MEASURED,
        unit="fraction",
        methodology="TWR_geometric_chain",
    )


def money_weighted_return(
    *,
    start_value: float,
    end_value: float,
    cashflows: Sequence[Cashflow | Mapping[str, Any]],
    max_iter: int = 64,
    tol: float = 1e-8,
) -> StatusedValue:
    """IRR / MWR via Newton on NPV = 0.

    Cashflows are treated as occurring at unit time fractions ordered by ts.
    Labels ESTIMATED when cashflow timing is coarse (equal spacing assumption).
    """
    flows: list[tuple[str, float]] = []
    for raw in cashflows:
        if isinstance(raw, Cashflow):
            flows.append((raw.ts, raw.amount))
        else:
            flows.append((str(raw.get("ts") or ""), float(raw.get("amount") or 0)))
    flows.sort(key=lambda x: x[0])

    if start_value == 0 and end_value == 0 and not flows:
        return StatusedValue(None, MeasurementState.EMPTY, methodology="MWR_irr")

    # Build timeline: t=0 start, equally spaced cashflows, t=1 end.
    n = len(flows)
    timed: list[tuple[float, float]] = [(0.0, -float(start_value))]
    for i, (_, amt) in enumerate(flows):
        t = (i + 1) / (n + 1) if n else 0.5
        timed.append((t, -float(amt)))  # contribution in reduces needed IRR capital sign
    timed.append((1.0, float(end_value)))

    def npv(rate: float) -> float:
        total = 0.0
        for t, cf in timed:
            total += cf / ((1.0 + rate) ** t)
        return total

    def d_npv(rate: float) -> float:
        total = 0.0
        for t, cf in timed:
            if t == 0:
                continue
            total += -t * cf / ((1.0 + rate) ** (t + 1))
        return total

    rate = 0.0
    for _ in range(max_iter):
        f = npv(rate)
        df = d_npv(rate)
        if abs(df) < 1e-12:
            return StatusedValue(
                None,
                MeasurementState.INFEASIBLE,
                methodology="MWR_irr",
                notes=["derivative_near_zero"],
            )
        new_rate = rate - f / df
        if abs(new_rate - rate) < tol:
            state = MeasurementState.ESTIMATED if flows else MeasurementState.MEASURED
            return StatusedValue(
                new_rate,
                state,
                unit="fraction",
                methodology="MWR_irr_equal_spacing_assumption",
                notes=["cashflow_timing_ASSUMED_equal_spacing"] if flows else [],
            )
        rate = new_rate

    return StatusedValue(
        rate,
        MeasurementState.ESTIMATED,
        unit="fraction",
        methodology="MWR_irr_equal_spacing_assumption",
        notes=["max_iter_reached"],
    )


def attribute_position_contributions(
    positions: Sequence[Mapping[str, Any]],
    *,
    total_pnl: float | None = None,
) -> dict[str, Any]:
    """Reuse portefeuille attribution semantics with honest labels."""
    try:
        from ..portefeuille.attribution import attribute_contributions

        result = attribute_contributions(positions=positions, total_pnl=total_pnl)
        result = dict(result)
        result["methodology"] = "position_contribution"
        result.setdefault("truth", {})
        result["truth"]["not_brinson_factor_attribution"] = True
        return result
    except Exception:  # noqa: BLE001
        by_symbol: dict[str, float] = {}
        for pos in positions:
            sym = str(pos.get("symbol") or "?")
            pnl = float(pos.get("unrealized_pnl") or pos.get("realized_pnl") or 0.0)
            by_symbol[sym] = by_symbol.get(sym, 0.0) + pnl
        return {
            "bySymbol": by_symbol,
            "method": "position_contribution",
            "methodology": "position_contribution",
            "truth": {"not_brinson_factor_attribution": True},
        }


def compute_performance(
    *,
    start_value: float,
    end_value: float,
    period_returns: Sequence[float] | None = None,
    cashflows: Sequence[Cashflow | Mapping[str, Any]] | None = None,
    positions: Sequence[Mapping[str, Any]] | None = None,
    total_pnl: float | None = None,
) -> PerformanceReport:
    notes: list[str] = []
    twr = (
        time_weighted_return(period_returns)
        if period_returns is not None
        else StatusedValue(None, MeasurementState.UNMEASURED, methodology="TWR_geometric_chain")
    )
    if period_returns is None:
        notes.append("twr_UNMEASURED_no_period_returns")
    mwr = money_weighted_return(
        start_value=start_value,
        end_value=end_value,
        cashflows=cashflows or (),
    )
    simple = simple_period_return(start_value, end_value)
    attribution = (
        attribute_position_contributions(positions or (), total_pnl=total_pnl)
        if positions is not None
        else {"status": MeasurementState.EMPTY.value, "methodology": "position_contribution"}
    )
    return PerformanceReport(
        method="TWR_MWR_contribution",
        twr=twr,
        mwr=mwr,
        simple_return=simple,
        attribution=attribution,
        notes=notes,
    )
