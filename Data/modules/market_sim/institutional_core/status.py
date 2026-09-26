"""Shared institutional status vocabulary and measurement honesty (W37+).

Truthful states only — never invent PASS/green health from absence of data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class MeasurementState(str, Enum):
    """Honest measurement labels for metrics and capability claims."""

    UNMEASURED = "UNMEASURED"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    EMPTY = "EMPTY"
    BLOCKED = "BLOCKED"
    ASSUMED = "ASSUMED"
    ESTIMATED = "ESTIMATED"
    OBSERVED = "OBSERVED"
    MEASURED = "MEASURED"
    INFEASIBLE = "INFEASIBLE"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    FEATURE_GATED = "FEATURE_GATED"
    DEGRADED = "DEGRADED"
    PASS = "PASS"
    FAIL = "FAIL"


# Canonical vocabulary used across institutional_core reports.
STATUS_VOCABULARY: tuple[str, ...] = tuple(m.value for m in MeasurementState)

TRUTHFUL_NON_GREEN: frozenset[str] = frozenset(
    {
        MeasurementState.UNMEASURED.value,
        MeasurementState.UNAVAILABLE.value,
        MeasurementState.NOT_IMPLEMENTED.value,
        MeasurementState.EMPTY.value,
        MeasurementState.BLOCKED.value,
        MeasurementState.ASSUMED.value,
        MeasurementState.ESTIMATED.value,
        MeasurementState.INFEASIBLE.value,
        MeasurementState.INSUFFICIENT_HISTORY.value,
        MeasurementState.FEATURE_GATED.value,
        MeasurementState.DEGRADED.value,
        MeasurementState.FAIL.value,
    }
)


def is_green_claim(state: str | MeasurementState | None) -> bool:
    """True only for explicit MEASURED/PASS/OBSERVED — never for ASSUMED/ESTIMATED."""
    if state is None:
        return False
    value = state.value if isinstance(state, MeasurementState) else str(state)
    return value in {
        MeasurementState.MEASURED.value,
        MeasurementState.PASS.value,
        MeasurementState.OBSERVED.value,
    }


def coerce_measurement(raw: Any, default: MeasurementState = MeasurementState.UNMEASURED) -> MeasurementState:
    text = str(raw or "").strip().upper()
    if not text:
        return default
    try:
        return MeasurementState(text)
    except ValueError:
        return default


@dataclass(frozen=True)
class TruthFlags:
    """Reusable honesty markers attached to public payloads."""

    live_trading_blocked: bool = True
    no_fabricated_metrics: bool = True
    no_aladdin_parity_claim: bool = True
    notes: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "live_trading_blocked": self.live_trading_blocked,
            "no_fabricated_metrics": self.no_fabricated_metrics,
            "no_aladdin_parity_claim": self.no_aladdin_parity_claim,
        }
        if self.notes:
            out["notes"] = list(self.notes)
        return out


DEFAULT_TRUTH = TruthFlags()


@dataclass
class StatusedValue:
    """A numeric or object value always paired with an honest measurement state."""

    value: Any
    state: MeasurementState = MeasurementState.UNMEASURED
    unit: str | None = None
    methodology: str | None = None
    notes: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "state": self.state.value,
            "unit": self.unit,
            "methodology": self.methodology,
            "notes": list(self.notes),
            "truth": {
                "is_green_claim": is_green_claim(self.state),
                "assumed_or_estimated_is_not_measured": self.state
                in {MeasurementState.ASSUMED, MeasurementState.ESTIMATED},
            },
        }


def rollup_states(states: Sequence[str | MeasurementState]) -> MeasurementState:
    """Conservative rollup: worst non-pass wins; empty → EMPTY."""
    if not states:
        return MeasurementState.EMPTY
    values = [coerce_measurement(s) for s in states]
    priority = (
        MeasurementState.FAIL,
        MeasurementState.BLOCKED,
        MeasurementState.INFEASIBLE,
        MeasurementState.NOT_IMPLEMENTED,
        MeasurementState.UNAVAILABLE,
        MeasurementState.INSUFFICIENT_HISTORY,
        MeasurementState.DEGRADED,
        MeasurementState.FEATURE_GATED,
        MeasurementState.EMPTY,
        MeasurementState.UNMEASURED,
        MeasurementState.ASSUMED,
        MeasurementState.ESTIMATED,
        MeasurementState.OBSERVED,
        MeasurementState.MEASURED,
        MeasurementState.PASS,
    )
    for candidate in priority:
        if candidate in values:
            return candidate
    return MeasurementState.UNMEASURED


def attach_truth(payload: Mapping[str, Any], **extra: Any) -> dict[str, Any]:
    out = dict(payload)
    truth = dict(DEFAULT_TRUTH.public_dict())
    truth.update(extra)
    out["truth"] = truth
    return out
