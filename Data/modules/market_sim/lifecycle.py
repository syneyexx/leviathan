"""Strategy drift / degradation helpers (Master Program T15)."""

from __future__ import annotations

from typing import Any, Sequence

from .strategy_library import PROMOTION_STATES, PROMOTION_TRANSITIONS, assert_promotion_allowed
from .types import MarketSimError, StrategyStatus


# Extend promotion machine with degradation path (T15).
DEGRADATION_STATES: frozenset[str] = frozenset({"DEGRADED", "REVIEW"})

EXTENDED_PROMOTION_STATES = PROMOTION_STATES | DEGRADATION_STATES

EXTENDED_TRANSITIONS: dict[str, frozenset[str]] = {
    StrategyStatus.DRAFT.value: frozenset({"RESEARCH", StrategyStatus.ARCHIVED.value}),
    "RESEARCH": frozenset(
        {"CANDIDATE", "REJECTED", StrategyStatus.ARCHIVED.value, StrategyStatus.DRAFT.value}
    ),
    "CANDIDATE": frozenset(
        {"PAPER_READY", "REJECTED", "RESEARCH", StrategyStatus.ARCHIVED.value}
    ),
    "PAPER_READY": frozenset(
        {
            StrategyStatus.ACTIVE.value,
            "REJECTED",
            StrategyStatus.ARCHIVED.value,
            "DEGRADED",
        }
    ),
    StrategyStatus.ACTIVE.value: frozenset(
        {
            StrategyStatus.ARCHIVED.value,
            "PAPER_READY",
            "RESEARCH",
            "DEGRADED",
        }
    ),
    "REJECTED": frozenset({"RESEARCH", StrategyStatus.ARCHIVED.value}),
    StrategyStatus.ARCHIVED.value: frozenset(),
    "DEGRADED": frozenset({"REVIEW", "RESEARCH", StrategyStatus.ARCHIVED.value}),
    "REVIEW": frozenset(
        {
            StrategyStatus.ACTIVE.value,
            "PAPER_READY",
            "RESEARCH",
            StrategyStatus.ARCHIVED.value,
            "DEGRADED",
        }
    ),
}


def can_transition(from_status: str, to_status: str) -> bool:
    src = str(from_status or "").upper()
    dst = str(to_status or "").upper()
    if dst not in EXTENDED_PROMOTION_STATES:
        return False
    allowed = EXTENDED_TRANSITIONS.get(src)
    if allowed is None:
        return False
    return dst in allowed


def assert_lifecycle_transition(from_status: str, to_status: str) -> None:
    if can_transition(from_status, to_status):
        return
    # Fall back to original promotion rules for non-degradation paths.
    try:
        assert_promotion_allowed(from_status, to_status)
    except MarketSimError:
        raise MarketSimError(
            "INVALID_LIFECYCLE",
            f"Cannot transition {from_status} → {to_status}",
            http_status=409,
        ) from None


def compute_performance_drift(
    *,
    expected_returns: Sequence[float],
    actual_returns: Sequence[float],
    band: float = 0.05,
) -> dict[str, Any]:
    """Compare paper/shadow returns vs historical expectation (sample-size honest)."""
    n = min(len(expected_returns), len(actual_returns))
    if n < 5:
        return {
            "points": n,
            "within_band": False,
            "status": "UNMEASURED",
            "reason": "insufficient_sample",
            "mean_expected": None,
            "mean_actual": None,
            "abs_drift": None,
            "truth": {"no_fake_significance": True},
        }
    mean_e = sum(float(x) for x in expected_returns[:n]) / n
    mean_a = sum(float(x) for x in actual_returns[:n]) / n
    abs_drift = abs(mean_a - mean_e)
    within = abs_drift <= band
    return {
        "points": n,
        "within_band": within,
        "status": "OK" if within else "DRIFT",
        "mean_expected": mean_e,
        "mean_actual": mean_a,
        "abs_drift": abs_drift,
        "band": band,
        "recommend_degrade": (not within) and n >= 20,
        "truth": {"no_fake_significance": True, "sample_size_checked": True},
    }
