"""Portfolio risk-setting governance — classify mutations before persist.

Loosening risk limits requires an approval identity
``market_sim.portfolio_risk.loosen`` (same pattern as mandate.loosen).
Tightening / neutral mutations commit without approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class RiskMutationClass(str, Enum):
    TIGHTENING = "TIGHTENING"
    NEUTRAL = "NEUTRAL"
    LOOSENING = "LOOSENING"


@dataclass(frozen=True)
class RiskMutationAssessment:
    classification: RiskMutationClass
    loosening_axes: tuple[str, ...]
    tightening_axes: tuple[str, ...]
    neutral_axes: tuple[str, ...]
    before: dict[str, Any]
    after: dict[str, Any]

    def public_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification.value,
            "looseningAxes": list(self.loosening_axes),
            "tighteningAxes": list(self.tightening_axes),
            "neutralAxes": list(self.neutral_axes),
            "before": dict(self.before),
            "after": dict(self.after),
        }


# Higher numeric value = more room to take risk (loosening when increased).
_HIGHER_IS_LOOSER: frozenset[str] = frozenset(
    {
        "max_leverage",
        "max_gross_exposure_pct",
        "max_net_exposure_pct",
        "max_position_pct",
        "max_symbol_exposure_pct",
        "asset_concentration_pct",
        "max_drawdown_pct",
        "daily_loss_limit_pct",
        "strategy_allocation_ceiling_pct",
        "agent_allocation_ceiling_pct",
        "max_orders_per_day",
        "per_trade_risk_pct",
        "max_order_notional",
        "max_concurrent_positions",
        "max_participation_pct",
        "capacity_cap_pct",
        "participation_cap_pct",
    }
)

# Higher numeric value = safer (tightening when increased).
_HIGHER_IS_TIGHTER: frozenset[str] = frozenset(
    {
        "cash_reserve_pct",
        "initial_margin_pct",
        "min_order_notional",
    }
)

_BOOL_ENABLE_IS_LOOSER: frozenset[str] = frozenset(
    {
        "shorting_enabled",
        "leverage_allowed",
        "allow_new_positions",
    }
)

_RISK_KEYS = _HIGHER_IS_LOOSER | _HIGHER_IS_TIGHTER | _BOOL_ENABLE_IS_LOOSER


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_risk_mutation(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> RiskMutationAssessment:
    """Pure classification of risk-setting delta.

    Directionality:
    - increasing allowed loss / drawdown / leverage / exposure / position size = LOOSENING
    - increasing cash reserve / margin = TIGHTENING
    - enabling shorting = LOOSENING; disabling = TIGHTENING
    """
    b = dict(before or {})
    a = dict(after or {})
    loosening: list[str] = []
    tightening: list[str] = []
    neutral: list[str] = []

    keys = sorted(set(b) | set(a) | _RISK_KEYS)
    for key in keys:
        if key not in _RISK_KEYS:
            continue
        bv = b.get(key)
        av = a.get(key)
        if bv == av:
            if key in b or key in a:
                neutral.append(key)
            continue

        if key in _BOOL_ENABLE_IS_LOOSER:
            before_on = bool(bv)
            after_on = bool(av)
            if after_on and not before_on:
                loosening.append(key)
            elif before_on and not after_on:
                tightening.append(key)
            else:
                neutral.append(key)
            continue

        bf = _as_float(bv)
        af = _as_float(av)
        if bf is None and af is None:
            neutral.append(key)
            continue
        if bf is None:
            bf = 0.0
        if af is None:
            af = 0.0
        if abs(af - bf) < 1e-12:
            neutral.append(key)
            continue

        if key in _HIGHER_IS_LOOSER:
            if af > bf:
                loosening.append(key)
            else:
                tightening.append(key)
        elif key in _HIGHER_IS_TIGHTER:
            if af > bf:
                tightening.append(key)
            else:
                loosening.append(key)

    if loosening:
        classification = RiskMutationClass.LOOSENING
    elif tightening:
        classification = RiskMutationClass.TIGHTENING
    else:
        classification = RiskMutationClass.NEUTRAL

    risk_before = {k: b.get(k) for k in _RISK_KEYS if k in b}
    risk_after = {k: a.get(k) for k in _RISK_KEYS if k in a}
    return RiskMutationAssessment(
        classification=classification,
        loosening_axes=tuple(loosening),
        tightening_axes=tuple(tightening),
        neutral_axes=tuple(neutral),
        before=risk_before,
        after=risk_after,
    )


PORTFOLIO_RISK_LOOSEN_CAPABILITY = "market_sim.portfolio_risk.loosen"
