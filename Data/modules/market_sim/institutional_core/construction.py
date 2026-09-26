"""W50 — Portfolio construction / optimization with INFEASIBLE honesty.

Never returns approximate success when constraints cannot be met.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, DEFAULT_TRUTH


@dataclass(frozen=True)
class WeightBound:
    instrument_id: str
    lower: float = 0.0
    upper: float = 1.0

    def public_dict(self) -> dict[str, Any]:
        return {
            "instrumentId": self.instrument_id,
            "lower": self.lower,
            "upper": self.upper,
        }


@dataclass(frozen=True)
class ConstructionConstraints:
    bounds: tuple[WeightBound, ...] = ()
    sum_weights: float = 1.0
    max_gross: float = 1.0
    long_only: bool = True
    require_full_invest: bool = True

    def public_dict(self) -> dict[str, Any]:
        return {
            "bounds": [b.public_dict() for b in self.bounds],
            "sumWeights": self.sum_weights,
            "maxGross": self.max_gross,
            "longOnly": self.long_only,
            "requireFullInvest": self.require_full_invest,
        }


@dataclass
class ConstructionResult:
    status: str
    weights: dict[str, float]
    objective_value: float | None
    violations: list[str] = field(default_factory=list)
    method: str = "greedy_score_normalize"
    notes: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "weights": dict(self.weights),
            "objectiveValue": self.objective_value,
            "violations": list(self.violations),
            "method": self.method,
            "notes": list(self.notes),
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "infeasible_is_not_approximate_success": True,
            },
        }


def _bound_map(constraints: ConstructionConstraints) -> dict[str, WeightBound]:
    return {b.instrument_id: b for b in constraints.bounds}


def check_feasibility(
    weights: Mapping[str, float],
    constraints: ConstructionConstraints,
) -> list[str]:
    violations: list[str] = []
    bounds = _bound_map(constraints)
    gross = sum(abs(w) for w in weights.values())
    total = sum(weights.values())

    if constraints.long_only and any(w < -1e-12 for w in weights.values()):
        violations.append("long_only")
    if gross - constraints.max_gross > 1e-9:
        violations.append("max_gross")
    if constraints.require_full_invest and abs(total - constraints.sum_weights) > 1e-8:
        violations.append("sum_weights")

    for inst, weight in weights.items():
        b = bounds.get(inst)
        if b is None:
            continue
        if weight < b.lower - 1e-12 or weight > b.upper + 1e-12:
            violations.append(f"bound:{inst}")

    # Instruments with positive lower bound must appear.
    for inst, b in bounds.items():
        if b.lower > 0 and inst not in weights:
            violations.append(f"missing_required:{inst}")
        # Lower bounds must be jointly feasible with sum/max_gross.
    lower_sum = sum(max(0.0, b.lower) for b in constraints.bounds)
    if lower_sum - constraints.sum_weights > 1e-9:
        violations.append("lower_bounds_exceed_sum")
    if lower_sum - constraints.max_gross > 1e-9:
        violations.append("lower_bounds_exceed_max_gross")
    upper_sum = sum(b.upper for b in constraints.bounds) if constraints.bounds else None
    if (
        constraints.require_full_invest
        and upper_sum is not None
        and upper_sum + 1e-9 < constraints.sum_weights
        and set(weights) <= set(bounds)
    ):
        violations.append("upper_bounds_below_sum")
    return sorted(set(violations))


def optimize_scores(
    scores: Mapping[str, float],
    constraints: ConstructionConstraints | None = None,
) -> ConstructionResult:
    """Deterministic greedy construction: clip to bounds, normalize to sum.

    If constraints are jointly infeasible, returns status INFEASIBLE (never fake success).
    """
    cons = constraints or ConstructionConstraints()
    bounds = _bound_map(cons)
    notes: list[str] = ["method_ASSUMED_greedy_not_qp"]

    # Pre-check bound aggregate feasibility independent of scores.
    pre = check_feasibility({}, cons)
    structural = [v for v in pre if v.startswith("lower_bounds") or v.startswith("upper_bounds")]
    if structural:
        return ConstructionResult(
            status=MeasurementState.INFEASIBLE.value,
            weights={},
            objective_value=None,
            violations=structural,
            notes=notes + ["structural_infeasibility"],
        )

    if not scores:
        return ConstructionResult(
            status=MeasurementState.EMPTY.value,
            weights={},
            objective_value=None,
            notes=notes + ["empty_scores"],
        )

    # Long-only path: drop non-positive scores when long_only.
    working = dict(scores)
    if cons.long_only:
        working = {k: max(0.0, float(v)) for k, v in working.items()}
        working = {k: v for k, v in working.items() if v > 0}
        if not working:
            # Still may need to meet lower bounds — if any lower>0 without score, infeasible.
            if any(b.lower > 0 for b in cons.bounds):
                return ConstructionResult(
                    status=MeasurementState.INFEASIBLE.value,
                    weights={},
                    objective_value=None,
                    violations=["no_positive_scores_with_lower_bounds"],
                    notes=notes,
                )
            return ConstructionResult(
                status=MeasurementState.EMPTY.value,
                weights={},
                objective_value=None,
                notes=notes + ["no_positive_scores"],
            )

    # Seed with lower bounds then distribute residual by score.
    weights: dict[str, float] = {}
    for inst in set(working) | set(bounds):
        lo = bounds[inst].lower if inst in bounds else 0.0
        weights[inst] = lo

    residual = cons.sum_weights - sum(weights.values())
    if residual < -1e-9:
        return ConstructionResult(
            status=MeasurementState.INFEASIBLE.value,
            weights={},
            objective_value=None,
            violations=["lower_bounds_exceed_sum"],
            notes=notes,
        )

    score_sum = sum(max(0.0, float(working.get(i, 0.0))) for i in working)
    if residual > 1e-12 and score_sum > 0:
        for inst, score in working.items():
            if score <= 0:
                continue
            add = residual * (float(score) / score_sum)
            weights[inst] = weights.get(inst, 0.0) + add

    # Clip to upper bounds; if mass remains, attempt redistribute — else INFEASIBLE.
    for _ in range(len(weights) + 1):
        overflow = 0.0
        room: dict[str, float] = {}
        for inst, w in list(weights.items()):
            up = bounds[inst].upper if inst in bounds else (1.0 if cons.long_only else cons.max_gross)
            if w > up:
                overflow += w - up
                weights[inst] = up
            else:
                room[inst] = up - w
        if overflow <= 1e-12:
            break
        room_total = sum(room.values())
        if room_total <= 1e-12:
            return ConstructionResult(
                status=MeasurementState.INFEASIBLE.value,
                weights={},
                objective_value=None,
                violations=["upper_bounds_block_residual"],
                notes=notes,
            )
        for inst, r in room.items():
            weights[inst] += overflow * (r / room_total)

    # Drop zeros for cleanliness.
    weights = {k: v for k, v in weights.items() if abs(v) > 1e-15}
    violations = check_feasibility(weights, cons)
    if violations:
        return ConstructionResult(
            status=MeasurementState.INFEASIBLE.value,
            weights={},
            objective_value=None,
            violations=violations,
            notes=notes,
        )

    objective = sum(float(scores.get(k, 0.0)) * v for k, v in weights.items())
    return ConstructionResult(
        status=MeasurementState.OBSERVED.value,
        weights=weights,
        objective_value=objective,
        violations=[],
        notes=notes,
    )
