"""Adaptive compute — calibrate expected gain and adapt the neural axis.

Orchestration-mode adaptation already exists in MetaController._adapt_mode.
This module adds the missing neural-axis / expected_gain calibration (R08).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .neural_compute import NativeEffort, NeuralComputeBudget
from .types import ReasoningMode


_EFFORT_ORDER = (
    NativeEffort.MINIMAL,
    NativeEffort.LOW,
    NativeEffort.MEDIUM,
    NativeEffort.HIGH,
    NativeEffort.MAXIMUM,
)


@dataclass(frozen=True)
class ExpectedGainEstimate:
    """Calibrated public estimate of remaining useful compute gain (0..1)."""

    total: float
    information_gap: float
    contradiction_pressure: float
    freshness_pressure: float
    diminishing_returns: float
    notes: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "information_gap": self.information_gap,
            "contradiction_pressure": self.contradiction_pressure,
            "freshness_pressure": self.freshness_pressure,
            "diminishing_returns": self.diminishing_returns,
            "notes": list(self.notes),
            "truth": {
                "expected_gain_is_heuristic_not_bayesian": True,
                "calibrated_for_neural_axis": True,
                "not_private_cot": True,
            },
        }


def calibrate_expected_gain(
    *,
    uncertainty: float = 0.5,
    evidence_coverage: float = 0.0,
    contradiction_density: float = 0.0,
    information_gain_recent: float | None = None,
    plan_progress: float = 0.0,
    requires_current_information: bool = False,
    requires_research: bool = False,
    tool_failures: int = 0,
) -> ExpectedGainEstimate:
    """Map run signals → remaining expected gain for more neural compute."""
    unc = max(0.0, min(1.0, float(uncertainty)))
    evidence = max(0.0, min(1.0, float(evidence_coverage)))
    contra = max(0.0, min(1.0, float(contradiction_density)))
    progress = max(0.0, min(1.0, float(plan_progress)))
    notes: list[str] = []

    information_gap = round(unc * (1.0 - evidence), 4)
    contradiction_pressure = round(min(1.0, contra * 1.25), 4)
    freshness_pressure = 0.0
    if requires_current_information:
        freshness_pressure = 0.35 if evidence < 0.6 else 0.15
        notes.append("freshness_pressure")
    if requires_research and evidence < 0.4:
        freshness_pressure = min(1.0, freshness_pressure + 0.2)
        notes.append("research_gap")

    diminishing = 0.0
    if information_gain_recent is not None:
        ig = max(0.0, min(1.0, float(information_gain_recent)))
        if ig < 0.08 and progress >= 0.4:
            diminishing = round(0.45 + (0.4 - ig) * 0.5, 4)
            notes.append("diminishing_returns_low_info_gain")
        elif ig < 0.05:
            diminishing = 0.25
            notes.append("flat_info_gain")
    if tool_failures >= 2:
        # Failures raise expected gain of *deeper* strategy, not of blind retries.
        information_gap = min(1.0, information_gap + 0.15)
        notes.append("tool_failures_raise_gap")

    raw = (
        0.45 * information_gap
        + 0.25 * contradiction_pressure
        + 0.2 * freshness_pressure
        + 0.15 * unc
        - 0.35 * diminishing
        - 0.1 * progress
    )
    total = round(max(0.0, min(1.0, raw)), 4)
    if total >= 0.55:
        notes.append("high_expected_gain")
    elif total <= 0.25:
        notes.append("low_expected_gain")
    else:
        notes.append("moderate_expected_gain")
    return ExpectedGainEstimate(
        total=total,
        information_gap=information_gap,
        contradiction_pressure=contradiction_pressure,
        freshness_pressure=round(freshness_pressure, 4),
        diminishing_returns=round(diminishing, 4),
        notes=tuple(notes),
    )


def _bump_effort(effort: NativeEffort, delta: int) -> NativeEffort:
    if effort in {NativeEffort.UNSUPPORTED, NativeEffort.UNMEASURED}:
        return effort
    try:
        idx = _EFFORT_ORDER.index(effort)
    except ValueError:
        idx = 2
    idx = max(0, min(len(_EFFORT_ORDER) - 1, idx + delta))
    return _EFFORT_ORDER[idx]


def adapt_neural_budget(
    budget: NeuralComputeBudget,
    *,
    gain: ExpectedGainEstimate,
    resource_pressure: float = 0.0,
    mode: ReasoningMode | str | None = None,
    clamp_threshold: float = 0.8,
) -> tuple[NeuralComputeBudget, str, tuple[str, ...]]:
    """Escalate/de-escalate neural candidates/effort from calibrated gain.

    Returns (budget, adaptation_label, notes).
    Labels: escalated | deescalated | held | clamped
    """
    notes: list[str] = [f"expected_gain={gain.total}"]
    pressure = max(0.0, min(1.0, float(resource_pressure)))
    candidates = max(1, int(budget.candidate_count))
    parallel = max(1, int(budget.max_parallel_candidates))
    diversity = float(budget.diversity_temperature)
    effort = budget.native_effort
    samples = max(1, int(budget.self_consistency_samples))
    label = "held"

    if gain.total >= 0.55:
        candidates = min(8, candidates + (2 if gain.total >= 0.7 else 1))
        samples = min(7, max(samples, candidates))
        diversity = min(0.6, diversity + 0.1)
        if gain.contradiction_pressure >= 0.4 or gain.total >= 0.7:
            effort = _bump_effort(effort, +1)
        parallel = min(candidates, max(parallel, min(3, candidates)))
        label = "escalated"
        notes.append("neural_axis_escalated_on_expected_gain")
    elif gain.total <= 0.25:
        candidates = max(1, candidates - (2 if gain.total <= 0.15 else 1))
        samples = max(1, min(samples, candidates))
        diversity = max(0.0, diversity - 0.1)
        if gain.diminishing_returns >= 0.4:
            effort = _bump_effort(effort, -1)
        parallel = min(parallel, candidates)
        label = "deescalated"
        notes.append("neural_axis_deescalated_on_low_gain")
    else:
        notes.append("neural_axis_held")

    # Mode ceiling — never jump past MAXIMUM presets wildly.
    mode_key = mode.value if isinstance(mode, ReasoningMode) else str(mode or "").upper()
    if mode_key == ReasoningMode.FAST.value:
        candidates = min(candidates, 2)
        parallel = 1
    elif mode_key == ReasoningMode.STANDARD.value:
        candidates = min(candidates, 4)

    adapted = replace(
        budget,
        native_effort=effort,
        candidate_count=candidates,
        max_parallel_candidates=max(1, parallel),
        self_consistency_samples=samples,
        diversity_temperature=round(diversity, 4),
    )

    if pressure >= clamp_threshold:
        adapted = adapted.clamped(
            max_candidates=max(1, adapted.candidate_count // 2),
            max_parallel=1,
        )
        label = "clamped"
        notes.append(
            f"neural_axis_clamped_under_pressure={pressure:.2f} "
            f"candidates={adapted.candidate_count}"
        )

    return adapted, label, tuple(notes)
