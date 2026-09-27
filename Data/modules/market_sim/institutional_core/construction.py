"""W50 — Portfolio construction / optimization with INFEASIBLE honesty.

Never returns approximate success when constraints cannot be met.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, DEFAULT_TRUTH

_EPS_VAR = 1e-12
_SHRINKAGE_LAMBDA = 0.1


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
    max_strategy_weight: float | None = None
    max_cluster_weight: float | None = None
    max_risk_contribution_pct: float | None = None
    max_pairwise_correlation: float | None = None
    capacity_limits: dict[str, float] = field(default_factory=dict)
    strategy_clusters: dict[str, str] = field(default_factory=dict)  # strategy_id -> cluster_id

    def public_dict(self) -> dict[str, Any]:
        return {
            "bounds": [b.public_dict() for b in self.bounds],
            "sumWeights": self.sum_weights,
            "maxGross": self.max_gross,
            "longOnly": self.long_only,
            "requireFullInvest": self.require_full_invest,
            "maxStrategyWeight": self.max_strategy_weight,
            "maxClusterWeight": self.max_cluster_weight,
            "maxRiskContributionPct": self.max_risk_contribution_pct,
            "maxPairwiseCorrelation": self.max_pairwise_correlation,
            "capacityLimits": dict(self.capacity_limits),
            "strategyClusters": dict(self.strategy_clusters),
        }


@dataclass
class CovarianceEstimate:
    strategy_ids: list[str]
    sample_count: int
    covariance: list[list[float]]
    correlation: list[list[float]]
    methodology: str
    state: str  # MeasurementState value
    warnings: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "strategyIds": list(self.strategy_ids),
            "sampleCount": self.sample_count,
            "covariance": [list(row) for row in self.covariance],
            "correlation": [list(row) for row in self.correlation],
            "methodology": self.methodology,
            "state": self.state,
            "warnings": list(self.warnings),
        }


@dataclass
class RiskContribution:
    strategy_id: str
    marginal_risk: float | None
    component_risk: float | None
    percent_risk: float | None
    state: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "strategyId": self.strategy_id,
            "marginalRisk": self.marginal_risk,
            "componentRisk": self.component_risk,
            "percentRisk": self.percent_risk,
            "state": self.state,
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

    if constraints.max_strategy_weight is not None:
        for inst, weight in weights.items():
            if abs(weight) - constraints.max_strategy_weight > 1e-12:
                violations.append(f"max_strategy_weight:{inst}")

    if constraints.capacity_limits:
        for inst, weight in weights.items():
            cap = constraints.capacity_limits.get(inst)
            if cap is not None and abs(weight) - float(cap) > 1e-12:
                violations.append(f"capacity:{inst}")

    if constraints.max_cluster_weight is not None and constraints.strategy_clusters:
        cluster_weights: dict[str, float] = {}
        for inst, weight in weights.items():
            cluster = constraints.strategy_clusters.get(inst)
            if cluster is None:
                continue
            cluster_weights[cluster] = cluster_weights.get(cluster, 0.0) + abs(weight)
        for cluster, cw in cluster_weights.items():
            if cw - constraints.max_cluster_weight > 1e-12:
                violations.append(f"max_cluster_weight:{cluster}")

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


def optimize_constrained(
    scores: Mapping[str, float],
    constraints: ConstructionConstraints | None = None,
    *,
    allow_approximate: bool = False,
) -> ConstructionResult:
    """Constrained portfolio construction.

    Prefer a projected score optimizer with explicit feasibility. Labels method
    honestly. Falls back to greedy only when constraints are the simple sum-
    to-one long-only case; never claims approximate success unless opted in.
    """
    cons = constraints or ConstructionConstraints()
    # Structural infeasibility short-circuit via greedy precheck path.
    seed = optimize_scores(scores, cons)
    if seed.status == MeasurementState.INFEASIBLE.value:
        return ConstructionResult(
            status=seed.status,
            weights={},
            objective_value=None,
            violations=list(seed.violations),
            method="constrained_projection",
            notes=["structural_or_joint_infeasibility"],
        )
    if seed.status in {MeasurementState.EMPTY.value}:
        return ConstructionResult(
            status=seed.status,
            weights={},
            objective_value=None,
            method="constrained_projection",
            notes=list(seed.notes),
        )

    # Refine with iterative projection onto box + simplex (long-only).
    weights = dict(seed.weights)
    bounds = _bound_map(cons)
    for _ in range(32):
        # Box projection
        for inst, w in list(weights.items()):
            lo = bounds[inst].lower if inst in bounds else 0.0
            up = bounds[inst].upper if inst in bounds else (1.0 if cons.long_only else cons.max_gross)
            weights[inst] = min(up, max(lo, w))
        # Simplex / sum projection
        total = sum(weights.values())
        if cons.require_full_invest and abs(total - cons.sum_weights) > 1e-10 and total != 0:
            scale = cons.sum_weights / total
            weights = {k: v * scale for k, v in weights.items()}
        # Gross cap
        gross = sum(abs(v) for v in weights.values())
        if gross > cons.max_gross + 1e-12 and gross > 0:
            scale = cons.max_gross / gross
            weights = {k: v * scale for k, v in weights.items()}
        violations = check_feasibility(weights, cons)
        if not violations:
            objective = sum(float(scores.get(k, 0.0)) * v for k, v in weights.items())
            return ConstructionResult(
                status=MeasurementState.OBSERVED.value,
                weights={k: v for k, v in weights.items() if abs(v) > 1e-15},
                objective_value=objective,
                violations=[],
                method="constrained_projection",
                notes=["projected_box_simplex"],
            )
    violations = check_feasibility(weights, cons)
    if allow_approximate:
        objective = sum(float(scores.get(k, 0.0)) * v for k, v in weights.items())
        return ConstructionResult(
            status=MeasurementState.ASSUMED.value,
            weights=weights,
            objective_value=objective,
            violations=violations,
            method="constrained_projection_approximate",
            notes=["operator_opted_into_approximation"],
        )
    return ConstructionResult(
        status=MeasurementState.INFEASIBLE.value,
        weights={},
        objective_value=None,
        violations=violations,
        method="constrained_projection",
        notes=["projection_did_not_converge_to_feasible"],
    )


def estimate_covariance(
    returns_by_strategy: Mapping[str, Sequence[float]],
    *,
    methodology: str = "sample_with_ledoit_wolf_shrinkage_ASSUMED",
    min_samples: int = 20,
) -> CovarianceEstimate:
    """Sample covariance with optional diagonal shrinkage.

    Aligns series to the common (minimum) length. Insufficient history yields
    empty matrices and INSUFFICIENT_HISTORY — never fabricated covariances.
    """
    strategy_ids = sorted(str(k) for k in returns_by_strategy.keys())
    warnings: list[str] = []
    if not strategy_ids:
        return CovarianceEstimate(
            strategy_ids=[],
            sample_count=0,
            covariance=[],
            correlation=[],
            methodology=methodology,
            state=MeasurementState.EMPTY.value,
            warnings=["empty_returns_by_strategy"],
        )

    series = {sid: [float(x) for x in returns_by_strategy[sid]] for sid in strategy_ids}
    n = min(len(v) for v in series.values())
    if n < min_samples:
        return CovarianceEstimate(
            strategy_ids=strategy_ids,
            sample_count=n,
            covariance=[],
            correlation=[],
            methodology=methodology,
            state=MeasurementState.INSUFFICIENT_HISTORY.value,
            warnings=["insufficient_history"],
        )

    aligned = {sid: series[sid][-n:] for sid in strategy_ids}
    k = len(strategy_ids)
    means = {sid: sum(aligned[sid]) / n for sid in strategy_ids}

    # Sample covariance (unbiased)
    cov = [[0.0] * k for _ in range(k)]
    for i, si in enumerate(strategy_ids):
        for j, sj in enumerate(strategy_ids):
            acc = 0.0
            mi, mj = means[si], means[sj]
            xi, xj = aligned[si], aligned[sj]
            for t in range(n):
                acc += (xi[t] - mi) * (xj[t] - mj)
            cov[i][j] = acc / (n - 1)

    for i in range(k):
        if cov[i][i] <= _EPS_VAR:
            warnings.append(f"zero_variance:{strategy_ids[i]}")
            cov[i][i] = _EPS_VAR

    use_shrinkage = "sample_only" not in methodology.lower()
    if use_shrinkage:
        # Simple Ledoit-Wolf-style shrink toward diagonal (lambda fixed; ASSUMED).
        shrunk = [[0.0] * k for _ in range(k)]
        for i in range(k):
            for j in range(k):
                target = cov[i][i] if i == j else 0.0
                shrunk[i][j] = (1.0 - _SHRINKAGE_LAMBDA) * cov[i][j] + _SHRINKAGE_LAMBDA * target
        cov = shrunk
        if "ASSUMED" in methodology.upper():
            state = MeasurementState.ASSUMED.value
        else:
            state = MeasurementState.ESTIMATED.value
        method_label = methodology
    else:
        state = MeasurementState.MEASURED.value
        method_label = methodology if methodology else "sample_only"

    # Correlation from (possibly shrunk) covariance
    corr = [[0.0] * k for _ in range(k)]
    for i in range(k):
        for j in range(k):
            denom = math.sqrt(max(cov[i][i], _EPS_VAR) * max(cov[j][j], _EPS_VAR))
            corr[i][j] = cov[i][j] / denom if denom > 0 else 0.0

    return CovarianceEstimate(
        strategy_ids=strategy_ids,
        sample_count=n,
        covariance=cov,
        correlation=corr,
        methodology=method_label,
        state=state,
        warnings=warnings,
    )


def risk_contributions(
    weights: Mapping[str, float],
    cov: CovarianceEstimate,
) -> list[RiskContribution]:
    """Marginal / component / percent risk from w'Σw. Unusable cov → UNMEASURED."""
    if cov.state in {
        MeasurementState.INSUFFICIENT_HISTORY.value,
        MeasurementState.UNMEASURED.value,
        MeasurementState.EMPTY.value,
    } or not cov.covariance:
        return [
            RiskContribution(
                strategy_id=sid,
                marginal_risk=None,
                component_risk=None,
                percent_risk=None,
                state=MeasurementState.UNMEASURED.value
                if cov.state == MeasurementState.UNMEASURED.value
                else cov.state,
            )
            for sid in (cov.strategy_ids or sorted(weights.keys()))
        ]

    ids = list(cov.strategy_ids)
    idx = {sid: i for i, sid in enumerate(ids)}
    w_vec = [float(weights.get(sid, 0.0)) for sid in ids]
    sigma = cov.covariance
    k = len(ids)

    # Σw
    sigma_w = [0.0] * k
    for i in range(k):
        acc = 0.0
        for j in range(k):
            acc += sigma[i][j] * w_vec[j]
        sigma_w[i] = acc

    port_var = sum(w_vec[i] * sigma_w[i] for i in range(k))
    if port_var <= _EPS_VAR:
        return [
            RiskContribution(
                strategy_id=sid,
                marginal_risk=0.0,
                component_risk=0.0,
                percent_risk=0.0,
                state=MeasurementState.ESTIMATED.value,
            )
            for sid in ids
        ]

    port_vol = math.sqrt(port_var)
    out: list[RiskContribution] = []
    for sid in ids:
        i = idx[sid]
        marginal = sigma_w[i] / port_vol
        component = w_vec[i] * marginal
        percent = (component / port_vol) * 100.0 if port_vol > 0 else 0.0
        out.append(
            RiskContribution(
                strategy_id=sid,
                marginal_risk=marginal,
                component_risk=component,
                percent_risk=percent,
                state=MeasurementState.ESTIMATED.value
                if cov.state != MeasurementState.MEASURED.value
                else MeasurementState.MEASURED.value,
            )
        )
    # Include weight keys missing from cov as UNMEASURED
    for sid in weights:
        if sid not in idx:
            out.append(
                RiskContribution(
                    strategy_id=sid,
                    marginal_risk=None,
                    component_risk=None,
                    percent_risk=None,
                    state=MeasurementState.UNMEASURED.value,
                )
            )
    return out


def _requires_covariance(constraints: ConstructionConstraints) -> bool:
    return (
        constraints.max_pairwise_correlation is not None
        or constraints.max_risk_contribution_pct is not None
    )


def _correlation_violations(
    weights: Mapping[str, float],
    cov: CovarianceEstimate,
    limit: float,
) -> list[str]:
    ids = list(cov.strategy_ids)
    idx = {sid: i for i, sid in enumerate(ids)}
    active = [sid for sid, w in weights.items() if abs(w) > 1e-12 and sid in idx]
    violations: list[str] = []
    for a_i, sa in enumerate(active):
        for sb in active[a_i + 1 :]:
            corr = cov.correlation[idx[sa]][idx[sb]]
            if abs(corr) - limit > 1e-12:
                violations.append(f"CORRELATION_LIMIT:{sa}:{sb}")
                # Near-perfect redundancy callout
                if abs(corr) >= 0.99:
                    violations.append("PORTFOLIO_REDUNDANT")
    return violations


def optimize_risk_budgeted(
    expected_scores: Mapping[str, float],
    covariance_estimate: CovarianceEstimate,
    constraints: ConstructionConstraints | None = None,
    risk_budgets: Mapping[str, float] | None = None,
) -> ConstructionResult:
    """Score-based construction with risk/correlation constraints.

    Starts from optimize_constrained. Never returns approximate success.
    Unusable covariance with required risk limits → INFEASIBLE.
    """
    cons = constraints or ConstructionConstraints()
    notes: list[str] = ["method_risk_budgeted_from_constrained"]

    if _requires_covariance(cons) and covariance_estimate.state in {
        MeasurementState.INSUFFICIENT_HISTORY.value,
        MeasurementState.UNMEASURED.value,
        MeasurementState.EMPTY.value,
    }:
        return ConstructionResult(
            status=MeasurementState.INFEASIBLE.value,
            weights={},
            objective_value=None,
            violations=["COVARIANCE_UNUSABLE", f"cov_state:{covariance_estimate.state}"],
            method="risk_budgeted",
            notes=notes + ["risk_limits_require_usable_covariance"],
        )

    seed = optimize_constrained(expected_scores, cons)
    if seed.status in {MeasurementState.INFEASIBLE.value, MeasurementState.EMPTY.value}:
        return ConstructionResult(
            status=seed.status,
            weights={},
            objective_value=None,
            violations=list(seed.violations),
            method="risk_budgeted",
            notes=notes + list(seed.notes),
        )

    weights = dict(seed.weights)

    # Enforce max_strategy_weight by clipping then re-check feasibility.
    if cons.max_strategy_weight is not None:
        capped = False
        for sid, w in list(weights.items()):
            if abs(w) > cons.max_strategy_weight + 1e-12:
                weights[sid] = math.copysign(cons.max_strategy_weight, w) if w != 0 else 0.0
                capped = True
        if capped and cons.require_full_invest:
            total = sum(weights.values())
            if abs(total - cons.sum_weights) > 1e-8 and total > 0:
                # Cannot silently rescale past caps — mark infeasible if residual.
                violations = check_feasibility(weights, cons)
                if abs(total - cons.sum_weights) > 1e-8:
                    violations = sorted(set(violations + ["sum_weights"]))
                if violations:
                    return ConstructionResult(
                        status=MeasurementState.INFEASIBLE.value,
                        weights={},
                        objective_value=None,
                        violations=violations,
                        method="risk_budgeted",
                        notes=notes + ["max_strategy_weight_broke_full_invest"],
                    )

    violations = check_feasibility(weights, cons)

    if cons.max_pairwise_correlation is not None:
        if not covariance_estimate.correlation:
            return ConstructionResult(
                status=MeasurementState.INFEASIBLE.value,
                weights={},
                objective_value=None,
                violations=["COVARIANCE_UNUSABLE", "CORRELATION_LIMIT"],
                method="risk_budgeted",
                notes=notes,
            )
        corr_violations = _correlation_violations(
            weights, covariance_estimate, cons.max_pairwise_correlation
        )
        if corr_violations:
            # Prefer the canonical blocker tokens used by qualification Q11.
            blockers = []
            if any(v.startswith("CORRELATION_LIMIT") for v in corr_violations):
                blockers.append("CORRELATION_LIMIT")
            if "PORTFOLIO_REDUNDANT" in corr_violations:
                blockers.append("PORTFOLIO_REDUNDANT")
            return ConstructionResult(
                status=MeasurementState.INFEASIBLE.value,
                weights={},
                objective_value=None,
                violations=sorted(set(blockers + corr_violations + violations)),
                method="risk_budgeted",
                notes=notes + ["pairwise_correlation_limit"],
            )

    if cons.max_risk_contribution_pct is not None or risk_budgets:
        contribs = risk_contributions(weights, covariance_estimate)
        for rc in contribs:
            if rc.percent_risk is None:
                if cons.max_risk_contribution_pct is not None:
                    return ConstructionResult(
                        status=MeasurementState.INFEASIBLE.value,
                        weights={},
                        objective_value=None,
                        violations=["COVARIANCE_UNUSABLE", "RISK_CONTRIBUTION_LIMIT"],
                        method="risk_budgeted",
                        notes=notes,
                    )
                continue
            if (
                cons.max_risk_contribution_pct is not None
                and rc.percent_risk - cons.max_risk_contribution_pct > 1e-9
            ):
                return ConstructionResult(
                    status=MeasurementState.INFEASIBLE.value,
                    weights={},
                    objective_value=None,
                    violations=["RISK_CONTRIBUTION_LIMIT", f"risk_contribution:{rc.strategy_id}"],
                    method="risk_budgeted",
                    notes=notes,
                )
            if risk_budgets and rc.strategy_id in risk_budgets:
                budget = float(risk_budgets[rc.strategy_id])
                if rc.percent_risk - budget > 1e-9:
                    return ConstructionResult(
                        status=MeasurementState.INFEASIBLE.value,
                        weights={},
                        objective_value=None,
                        violations=[
                            "RISK_CONTRIBUTION_LIMIT",
                            f"risk_budget:{rc.strategy_id}",
                        ],
                        method="risk_budgeted",
                        notes=notes,
                    )

    if violations:
        return ConstructionResult(
            status=MeasurementState.INFEASIBLE.value,
            weights={},
            objective_value=None,
            violations=violations,
            method="risk_budgeted",
            notes=notes,
        )

    objective = sum(float(expected_scores.get(k, 0.0)) * v for k, v in weights.items())
    return ConstructionResult(
        status=MeasurementState.OBSERVED.value,
        weights={k: v for k, v in weights.items() if abs(v) > 1e-15},
        objective_value=objective,
        violations=[],
        method="risk_budgeted",
        notes=notes,
    )
