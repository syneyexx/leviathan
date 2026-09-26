"""Scenario and stress engine (W18)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_id: str
    name: str
    shocks: Mapping[str, float]  # symbol -> return shock (e.g. -0.1 = -10%)
    description: str = ""
    status: str = "ASSUMED"  # ASSUMED until calibrated to history

    def public_dict(self) -> dict[str, Any]:
        return {
            "scenarioId": self.scenario_id,
            "name": self.name,
            "shocks": dict(self.shocks),
            "description": self.description,
            "status": self.status,
            "truth": {
                "scenario_is_ASSUMED_unless_calibrated": self.status != "CALIBRATED",
                "not_live_trading": True,
            },
        }


@dataclass
class ScenarioResult:
    scenario_id: str
    base_equity: float
    shocked_equity: float
    pnl: float
    pnl_pct: float
    position_impacts: list[dict[str, Any]] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "scenarioId": self.scenario_id,
            "baseEquity": self.base_equity,
            "shockedEquity": self.shocked_equity,
            "pnl": self.pnl,
            "pnlPct": self.pnl_pct,
            "positionImpacts": self.position_impacts,
            "truth": {"deterministic_shock_application": True},
        }


def apply_scenario(
    *,
    positions: Mapping[str, Mapping[str, Any]],
    marks: Mapping[str, float],
    cash: float,
    scenario: ScenarioSpec,
) -> ScenarioResult:
    """Apply price shocks to marks; long qty*px, short uses side if provided."""
    base_mv = 0.0
    shocked_mv = 0.0
    impacts: list[dict[str, Any]] = []
    for sym, pos in positions.items():
        qty = float(pos.get("qty") or 0)
        if qty == 0:
            continue
        side = str(pos.get("side") or "LONG").upper()
        px = float(marks.get(sym, pos.get("avg_entry") or 0))
        shock = float(scenario.shocks.get(sym, 0.0))
        shocked_px = px * (1.0 + shock)
        sign = 1.0 if side == "LONG" else -1.0
        base = sign * qty * px
        shocked = sign * qty * shocked_px
        base_mv += base
        shocked_mv += shocked
        impacts.append(
            {
                "symbol": sym,
                "side": side,
                "shock": shock,
                "baseValue": base,
                "shockedValue": shocked,
                "delta": shocked - base,
            }
        )
    base_eq = float(cash) + base_mv
    shocked_eq = float(cash) + shocked_mv
    pnl = shocked_eq - base_eq
    pnl_pct = (pnl / base_eq * 100.0) if base_eq else 0.0
    return ScenarioResult(
        scenario_id=scenario.scenario_id,
        base_equity=base_eq,
        shocked_equity=shocked_eq,
        pnl=pnl,
        pnl_pct=pnl_pct,
        position_impacts=impacts,
    )


# Built-in examples — ASSUMED
EQUITY_CRASH_10 = ScenarioSpec(
    scenario_id="equity_crash_10",
    name="Broad equity -10%",
    shocks={},
    description="Apply -10% to all provided equity marks via caller-supplied shocks",
)
