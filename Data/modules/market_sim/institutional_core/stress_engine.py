"""W46 — Stress engine extensions: what-if + reverse stress.

Extends scenario_risk.apply_scenario — no parallel stress owner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, DEFAULT_TRUTH


@dataclass(frozen=True)
class WhatIfShock:
    symbol: str
    return_shock: float  # e.g. -0.15

    def public_dict(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "returnShock": self.return_shock}


@dataclass
class WhatIfResult:
    scenario_id: str
    base_equity: float
    shocked_equity: float
    pnl: float
    pnl_pct: float
    shocks: list[WhatIfShock]
    position_impacts: list[dict[str, Any]] = field(default_factory=list)
    status: str = MeasurementState.ASSUMED.value

    def public_dict(self) -> dict[str, Any]:
        return {
            "scenarioId": self.scenario_id,
            "baseEquity": self.base_equity,
            "shockedEquity": self.shocked_equity,
            "pnl": self.pnl,
            "pnlPct": self.pnl_pct,
            "shocks": [s.public_dict() for s in self.shocks],
            "positionImpacts": list(self.position_impacts),
            "status": self.status,
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "extends_scenario_risk": True,
                "scenario_is_ASSUMED_unless_calibrated": self.status != "CALIBRATED",
            },
        }


@dataclass
class ReverseStressResult:
    target_loss_pct: float
    required_uniform_shock: float | None
    status: str
    notes: list[str] = field(default_factory=list)
    probed: list[dict[str, Any]] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "targetLossPct": self.target_loss_pct,
            "requiredUniformShock": self.required_uniform_shock,
            "status": self.status,
            "notes": list(self.notes),
            "probed": list(self.probed),
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "reverse_stress_is_ASSUMED_model": True,
                "not_full_historical_calibration": True,
            },
        }


def run_what_if(
    *,
    scenario_id: str,
    positions: Mapping[str, Mapping[str, Any]],
    marks: Mapping[str, float],
    cash: float,
    shocks: Sequence[WhatIfShock | Mapping[str, Any]],
    status: str = MeasurementState.ASSUMED.value,
) -> WhatIfResult:
    """Apply caller shocks via scenario_risk owner."""
    normalized: list[WhatIfShock] = []
    shock_map: dict[str, float] = {}
    for raw in shocks:
        if isinstance(raw, WhatIfShock):
            s = raw
        else:
            s = WhatIfShock(
                symbol=str(raw.get("symbol") or ""),
                return_shock=float(raw.get("return_shock") or raw.get("returnShock") or 0),
            )
        normalized.append(s)
        shock_map[s.symbol] = s.return_shock

    from ..scenario_risk import ScenarioSpec, apply_scenario

    spec = ScenarioSpec(
        scenario_id=scenario_id,
        name=f"what_if:{scenario_id}",
        shocks=shock_map,
        description="institutional_core what-if",
        status=status if status in {"ASSUMED", "CALIBRATED"} else "ASSUMED",
    )
    result = apply_scenario(positions=positions, marks=marks, cash=cash, scenario=spec)
    return WhatIfResult(
        scenario_id=result.scenario_id,
        base_equity=result.base_equity,
        shocked_equity=result.shocked_equity,
        pnl=result.pnl,
        pnl_pct=result.pnl_pct,
        shocks=normalized,
        position_impacts=list(result.position_impacts),
        status=spec.status,
    )


def reverse_stress_uniform(
    *,
    positions: Mapping[str, Mapping[str, Any]],
    marks: Mapping[str, float],
    cash: float,
    target_loss_pct: float,
    shock_grid: Sequence[float] | None = None,
) -> ReverseStressResult:
    """Find smallest uniform negative shock approximating target loss % (ASSUMED model).

    Searches a discrete grid — returns INFEASIBLE if target unreachable on grid.
    """
    if target_loss_pct <= 0:
        return ReverseStressResult(
            target_loss_pct=target_loss_pct,
            required_uniform_shock=0.0,
            status=MeasurementState.OBSERVED.value,
            notes=["non_positive_target_means_zero_shock"],
        )

    grid = list(shock_grid) if shock_grid is not None else [
        -0.01 * i for i in range(1, 51)
    ]
    probed: list[dict[str, Any]] = []
    best: tuple[float, float] | None = None  # (shock, loss_pct)

    symbols = sorted(set(positions) | set(marks))
    for shock in grid:
        shocks = [WhatIfShock(symbol=sym, return_shock=float(shock)) for sym in symbols]
        result = run_what_if(
            scenario_id=f"reverse_{shock}",
            positions=positions,
            marks=marks,
            cash=cash,
            shocks=shocks,
        )
        loss_pct = -result.pnl_pct if result.pnl_pct < 0 else 0.0
        probed.append({"shock": shock, "pnlPct": result.pnl_pct, "lossPct": loss_pct})
        if loss_pct >= target_loss_pct:
            if best is None or abs(shock) < abs(best[0]):
                best = (float(shock), loss_pct)

    if best is None:
        return ReverseStressResult(
            target_loss_pct=target_loss_pct,
            required_uniform_shock=None,
            status=MeasurementState.INFEASIBLE.value,
            notes=["target_unreachable_on_grid"],
            probed=probed,
        )
    return ReverseStressResult(
        target_loss_pct=target_loss_pct,
        required_uniform_shock=best[0],
        status=MeasurementState.ESTIMATED.value,
        notes=["uniform_shock_ASSUMED", "grid_search_ESTIMATED"],
        probed=probed,
    )
