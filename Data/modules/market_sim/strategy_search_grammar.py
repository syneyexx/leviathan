"""Strategy search grammar — composable structure for discovery (Wave 5).

Separates hypothesis generation from parameter optimization. Candidates carry
falsifiable contracts; fitness is multi-objective (not Sharpe-only).
Extends existing strategy_families / research_cycle / learning_candidates —
does not duplicate Brain / Fleet / JobSystem / MarketSim.
"""

from __future__ import annotations

import copy
import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from Data.modules.common.hashing import sha256_text

from .strategy_families import (
    SUPPORTED_STRATEGY_FAMILIES,
    get_family,
    research_generatable_families,
)


class SearchPrimitive(str, Enum):
    """Composable building blocks the search grammar may assemble."""

    PRICE_TRANSFORM = "price_transform"
    RETURNS = "returns"
    TREND = "trend"
    MOMENTUM = "momentum"
    VOLATILITY = "volatility"
    MEAN_REVERSION = "mean_reversion"
    VOLUME = "volume"
    LIQUIDITY = "liquidity"
    CROSS_SECTIONAL_RANK = "cross_sectional_rank"
    SPREAD = "spread"
    TERM_STRUCTURE = "term_structure"
    CARRY = "carry"
    MACRO = "macro"
    FUNDAMENTAL = "fundamental"
    EVENT = "event"
    REGIME_FILTER = "regime_filter"
    RISK_SCALING = "risk_scaling"
    PORTFOLIO_CONSTRAINT = "portfolio_constraint"
    EXECUTION_RULE = "execution_rule"


class SearchPhase(str, Enum):
    """Hypothesis generation is distinct from parameter optimization."""

    HYPOTHESIS_GENERATION = "HYPOTHESIS_GENERATION"
    PARAMETER_OPTIMIZATION = "PARAMETER_OPTIMIZATION"


class LeakageRisk(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


# Family → default primitives (advisory; not exclusive).
_FAMILY_PRIMITIVES: dict[str, tuple[SearchPrimitive, ...]] = {
    "ma_cross": (SearchPrimitive.TREND, SearchPrimitive.PRICE_TRANSFORM, SearchPrimitive.REGIME_FILTER),
    "mean_reversion": (SearchPrimitive.MEAN_REVERSION, SearchPrimitive.VOLATILITY, SearchPrimitive.RETURNS),
    "breakout": (SearchPrimitive.TREND, SearchPrimitive.VOLATILITY, SearchPrimitive.VOLUME),
    "rsi": (SearchPrimitive.MEAN_REVERSION, SearchPrimitive.MOMENTUM, SearchPrimitive.RETURNS),
    "momentum": (SearchPrimitive.MOMENTUM, SearchPrimitive.RETURNS, SearchPrimitive.CROSS_SECTIONAL_RANK),
    "volatility": (SearchPrimitive.VOLATILITY, SearchPrimitive.RISK_SCALING, SearchPrimitive.REGIME_FILTER),
}


@dataclass(frozen=True)
class GrammarNode:
    """One node in a composable search structure."""

    primitive: SearchPrimitive
    params: dict[str, Any] = field(default_factory=dict)
    children: tuple["GrammarNode", ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "primitive": self.primitive.value,
            "params": dict(self.params),
            "children": [c.public_dict() for c in self.children],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> "GrammarNode":
        raw = dict(raw or {})
        prim = SearchPrimitive(str(raw.get("primitive") or SearchPrimitive.RETURNS.value))
        children_raw = raw.get("children") or []
        children = tuple(cls.from_dict(c) for c in children_raw if isinstance(c, Mapping))
        return cls(primitive=prim, params=dict(raw.get("params") or {}), children=children)


@dataclass
class StrategySearchStructure:
    """Composable strategy structure used during discovery."""

    structure_id: str
    family: str
    nodes: list[GrammarNode] = field(default_factory=list)
    phase: str = SearchPhase.HYPOTHESIS_GENERATION.value
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "structure_id": self.structure_id,
            "family": self.family,
            "nodes": [n.public_dict() for n in self.nodes],
            "phase": self.phase,
            "metadata": dict(self.metadata),
            "truth": {
                "hypothesis_generation_separate_from_parameter_optimization": True,
                "composable_primitives": True,
            },
        }

    def structure_hash(self) -> str:
        body = {
            "family": self.family,
            "nodes": [n.public_dict() for n in self.nodes],
            "phase": self.phase,
        }
        return sha256_text(json.dumps(body, sort_keys=True, separators=(",", ":")))


@dataclass
class StrategyCandidateContract:
    """Full discovery candidate contract (Wave 5).

    Rationale / hypothesis / mechanism are public structured fields —
    never private chain-of-thought.
    """

    candidate_id: str
    family: str
    rationale: str
    falsifiable_hypothesis: str
    expected_mechanism: str
    expected_failure_regimes: list[str] = field(default_factory=list)
    required_data: list[str] = field(default_factory=list)
    expected_turnover: str = "unknown"
    capacity_considerations: str = ""
    parameter_bounds: dict[str, dict[str, float]] = field(default_factory=dict)
    leakage_risk: str = LeakageRisk.UNKNOWN.value
    leakage_assessment: str = ""
    structure: StrategySearchStructure | None = None
    phase: str = SearchPhase.HYPOTHESIS_GENERATION.value
    parameters: dict[str, Any] = field(default_factory=dict)
    entry_rules: dict[str, Any] = field(default_factory=dict)
    exit_rules: dict[str, Any] = field(default_factory=dict)
    risk_rules: dict[str, Any] = field(default_factory=dict)
    hypothesis_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "family": self.family,
            "rationale": self.rationale,
            "falsifiable_hypothesis": self.falsifiable_hypothesis,
            "expected_mechanism": self.expected_mechanism,
            "expected_failure_regimes": list(self.expected_failure_regimes),
            "required_data": list(self.required_data),
            "expected_turnover": self.expected_turnover,
            "capacity_considerations": self.capacity_considerations,
            "parameter_bounds": {k: dict(v) for k, v in self.parameter_bounds.items()},
            "leakage_risk": self.leakage_risk,
            "leakage_assessment": self.leakage_assessment,
            "structure": self.structure.public_dict() if self.structure else None,
            "phase": self.phase,
            "parameters": dict(self.parameters),
            "entry_rules": dict(self.entry_rules),
            "exit_rules": dict(self.exit_rules),
            "risk_rules": dict(self.risk_rules),
            "hypothesis_id": self.hypothesis_id,
            "metadata": dict(self.metadata),
            "truth": {
                "no_private_cot": True,
                "hypothesis_before_optimization": self.phase
                == SearchPhase.HYPOTHESIS_GENERATION.value,
                "parameter_optimization_is_separate_phase": True,
            },
        }

    def to_proposal_metadata(self) -> dict[str, Any]:
        """Fields safe to attach onto CandidateProposal.metadata."""
        return {
            "rationale": self.rationale,
            "falsifiable_hypothesis": self.falsifiable_hypothesis,
            "expected_mechanism": self.expected_mechanism,
            "expected_failure_regimes": list(self.expected_failure_regimes),
            "required_data": list(self.required_data),
            "expected_turnover": self.expected_turnover,
            "capacity_considerations": self.capacity_considerations,
            "parameter_bounds": {k: dict(v) for k, v in self.parameter_bounds.items()},
            "leakage_risk": self.leakage_risk,
            "leakage_assessment": self.leakage_assessment,
            "search_phase": self.phase,
            "structure_id": self.structure.structure_id if self.structure else None,
            "structure_hash": self.structure.structure_hash() if self.structure else None,
            "hypothesis_id": self.hypothesis_id,
        }


# Multi-objective fitness axes beyond Sharpe (consumed by learning_fitness).
MULTI_OBJECTIVE_AXES: tuple[str, ...] = (
    "return_quality",
    "risk_adjusted_return",
    "drawdown_quality",
    "tail_risk_quality",
    "turnover_quality",
    "concentration_quality",
    "execution_cost_quality",
    "cost_sensitivity_quality",
    "regime_stability",
    "regime_robustness",
    "trade_sufficiency",
    "complexity_quality",
)


def default_multi_objective_weights() -> dict[str, float]:
    return {
        "return_quality": 0.12,
        "risk_adjusted_return": 0.14,
        "drawdown_quality": 0.14,
        "tail_risk_quality": 0.10,
        "turnover_quality": 0.08,
        "concentration_quality": 0.06,
        "execution_cost_quality": 0.08,
        "cost_sensitivity_quality": 0.08,
        "regime_stability": 0.10,
        "trade_sufficiency": 0.06,
        "complexity_quality": 0.04,
    }


def assess_leakage_risk(
    *,
    required_data: Sequence[str] | None = None,
    uses_fundamentals: bool = False,
    uses_events: bool = False,
    uses_macro: bool = False,
    as_of_aligned: bool = True,
) -> tuple[str, str]:
    """Conservative leakage risk assessment for a candidate structure."""
    data = {str(d).lower() for d in (required_data or [])}
    flags: list[str] = []
    if uses_fundamentals or any("fundament" in d for d in data):
        flags.append("fundamentals_require_available_at")
    if uses_events or any(tok in d for d in data for tok in ("event", "news", "filing")):
        flags.append("events_require_publication_lag")
    if uses_macro or any("macro" in d for d in data):
        flags.append("macro_vintages_must_be_point_in_time")
    if not as_of_aligned:
        flags.append("as_of_misaligned")
    if not flags:
        return LeakageRisk.LOW.value, "ohlcv/price-only structure; standard bar causality"
    if "as_of_misaligned" in flags:
        return LeakageRisk.HIGH.value, "; ".join(flags)
    if len(flags) >= 2:
        return LeakageRisk.HIGH.value, "; ".join(flags)
    return LeakageRisk.MEDIUM.value, "; ".join(flags)


def build_structure_for_family(
    family: str,
    *,
    extra_primitives: Iterable[SearchPrimitive | str] | None = None,
    phase: str = SearchPhase.HYPOTHESIS_GENERATION.value,
    structure_id: str | None = None,
) -> StrategySearchStructure:
    """Compose a default grammar for a known strategy family."""
    fam = family if family in SUPPORTED_STRATEGY_FAMILIES else "ma_cross"
    base = list(_FAMILY_PRIMITIVES.get(fam, (SearchPrimitive.RETURNS, SearchPrimitive.TREND)))
    for raw in extra_primitives or ():
        prim = raw if isinstance(raw, SearchPrimitive) else SearchPrimitive(str(raw))
        if prim not in base:
            base.append(prim)
    # Always allow risk scaling + execution overlay composition.
    for required in (SearchPrimitive.RISK_SCALING, SearchPrimitive.EXECUTION_RULE, SearchPrimitive.PORTFOLIO_CONSTRAINT):
        if required not in base:
            base.append(required)
    nodes = [GrammarNode(primitive=p) for p in base]
    return StrategySearchStructure(
        structure_id=structure_id or str(uuid.uuid4()),
        family=fam,
        nodes=nodes,
        phase=str(phase),
        metadata={"source": "strategy_search_grammar"},
    )


def generate_hypothesis_candidate(
    *,
    family: str | None = None,
    rationale: str = "",
    falsifiable_hypothesis: str = "",
    expected_mechanism: str = "",
    expected_failure_regimes: Sequence[str] | None = None,
    perception: Mapping[str, Any] | None = None,
    hypothesis_id: str | None = None,
    prior_lessons: Sequence[Mapping[str, Any]] | None = None,
) -> StrategyCandidateContract:
    """Hypothesis-generation phase — structure + claim, not parameter search."""
    perception = dict(perception or {})
    families = research_generatable_families() or list(SUPPORTED_STRATEGY_FAMILIES)
    fam = family if family in families else (families[0] if families else "ma_cross")
    desc = get_family(fam)
    regime = str(perception.get("regime") or "unknown")
    structure = build_structure_for_family(fam, phase=SearchPhase.HYPOTHESIS_GENERATION.value)
    required = list(desc.required_data) if desc else ["ohlcv"]
    params = dict(desc.default_parameters) if desc else {}
    bounds = {k: dict(v) for k, v in (desc.parameter_ranges if desc else {}).items()}
    failure = list(expected_failure_regimes or ["high_volatility_chop", "cost_spike", "regime_shift"])
    for lesson in list(prior_lessons or [])[:4]:
        claim = str(lesson.get("claim") or "").strip()
        if claim and claim not in failure:
            failure.append(claim[:160])
    leakage, assessment = assess_leakage_risk(required_data=required)
    statement = falsifiable_hypothesis or (
        f"A {fam} structure yields positive net expectancy after costs in regime={regime}."
    )
    mechanism = expected_mechanism or (
        f"{fam} exploits {', '.join(n.primitive.value for n in structure.nodes[:3])} under {regime}."
    )
    rationale_text = rationale or (
        f"Grammar-composed {fam} hypothesis from perception (regime={regime})."
    )
    entry = copy.deepcopy(desc.entry_template) if desc else {"kind": fam, "version": 3, "parameters": params}
    exit_rules = copy.deepcopy(desc.exit_template) if desc else {"kind": fam}
    turnover = "medium"
    if fam in {"momentum", "breakout"}:
        turnover = "medium_high"
    elif fam in {"mean_reversion", "rsi"}:
        turnover = "high"
    elif fam == "ma_cross":
        turnover = "low_medium"
    return StrategyCandidateContract(
        candidate_id=str(uuid.uuid4()),
        family=fam,
        rationale=rationale_text,
        falsifiable_hypothesis=statement,
        expected_mechanism=mechanism,
        expected_failure_regimes=failure[:12],
        required_data=required,
        expected_turnover=turnover,
        capacity_considerations=(
            "Capacity limited by liquidity of target universe and participation caps; "
            "high-turnover families degrade first under thin books."
        ),
        parameter_bounds=bounds,
        leakage_risk=leakage,
        leakage_assessment=assessment,
        structure=structure,
        phase=SearchPhase.HYPOTHESIS_GENERATION.value,
        parameters=params,
        entry_rules=entry,
        exit_rules=exit_rules,
        risk_rules={"max_position_pct": 25},
        hypothesis_id=hypothesis_id,
        metadata={"origin": "strategy_search_grammar.hypothesis"},
    )


def optimize_parameters(
    candidate: StrategyCandidateContract,
    *,
    suggested: Mapping[str, Any] | None = None,
    clamp_to_bounds: bool = True,
) -> StrategyCandidateContract:
    """Parameter-optimization phase — mutates parameters only, preserves hypothesis."""
    if candidate.phase != SearchPhase.HYPOTHESIS_GENERATION.value and candidate.phase != SearchPhase.PARAMETER_OPTIMIZATION.value:
        raise ValueError(f"unexpected search phase: {candidate.phase}")
    params = dict(candidate.parameters)
    for key, value in dict(suggested or {}).items():
        if clamp_to_bounds and key in candidate.parameter_bounds:
            bounds = candidate.parameter_bounds[key]
            lo = float(bounds.get("min", value))
            hi = float(bounds.get("max", value))
            try:
                num = float(value)
                value = max(lo, min(hi, num))
                if isinstance(candidate.parameters.get(key), int) or key in {
                    "fast_ma",
                    "slow_ma",
                    "period",
                    "lookback",
                }:
                    value = int(round(value))
            except (TypeError, ValueError):
                pass
        params[key] = value
    structure = candidate.structure
    if structure is not None:
        structure = StrategySearchStructure(
            structure_id=structure.structure_id,
            family=structure.family,
            nodes=list(structure.nodes),
            phase=SearchPhase.PARAMETER_OPTIMIZATION.value,
            metadata={**dict(structure.metadata), "optimized": True},
        )
    entry = copy.deepcopy(candidate.entry_rules)
    if isinstance(entry.get("parameters"), dict):
        entry["parameters"] = {**dict(entry["parameters"]), **params}
    return StrategyCandidateContract(
        candidate_id=candidate.candidate_id,
        family=candidate.family,
        rationale=candidate.rationale,
        falsifiable_hypothesis=candidate.falsifiable_hypothesis,
        expected_mechanism=candidate.expected_mechanism,
        expected_failure_regimes=list(candidate.expected_failure_regimes),
        required_data=list(candidate.required_data),
        expected_turnover=candidate.expected_turnover,
        capacity_considerations=candidate.capacity_considerations,
        parameter_bounds={k: dict(v) for k, v in candidate.parameter_bounds.items()},
        leakage_risk=candidate.leakage_risk,
        leakage_assessment=candidate.leakage_assessment,
        structure=structure,
        phase=SearchPhase.PARAMETER_OPTIMIZATION.value,
        parameters=params,
        entry_rules=entry,
        exit_rules=copy.deepcopy(candidate.exit_rules),
        risk_rules=copy.deepcopy(candidate.risk_rules),
        hypothesis_id=candidate.hypothesis_id,
        metadata={**dict(candidate.metadata), "optimized_from_hypothesis": True},
    )


def enrich_proposal_with_contract(
    proposal: Mapping[str, Any],
    *,
    contract: StrategyCandidateContract | None = None,
    perception: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach Wave-5 contract fields onto an author proposal / candidate dict."""
    out = dict(proposal or {})
    family = str(out.get("family") or (out.get("entry_rules") or {}).get("kind") or "ma_cross")
    c = contract or generate_hypothesis_candidate(
        family=family,
        perception=perception,
        hypothesis_id=out.get("hypothesis_id"),
        falsifiable_hypothesis=str(out.get("hypothesis") or out.get("falsifiable_hypothesis") or ""),
        rationale=str(out.get("rationale") or ""),
        expected_mechanism=str(out.get("expected_mechanism") or ""),
    )
    meta = dict(out.get("metadata") or {})
    meta.update(c.to_proposal_metadata())
    out["metadata"] = meta
    out.setdefault("rationale", c.rationale)
    out.setdefault("falsifiable_hypothesis", c.falsifiable_hypothesis)
    out.setdefault("expected_mechanism", c.expected_mechanism)
    out.setdefault("expected_failure_regimes", list(c.expected_failure_regimes))
    out.setdefault("required_data", list(c.required_data))
    out.setdefault("expected_turnover", c.expected_turnover)
    out.setdefault("capacity_considerations", c.capacity_considerations)
    out.setdefault("parameter_bounds", dict(c.parameter_bounds))
    out.setdefault("leakage_risk", c.leakage_risk)
    out.setdefault("leakage_assessment", c.leakage_assessment)
    out.setdefault("search_phase", c.phase)
    if c.hypothesis_id and not out.get("hypothesis_id"):
        out["hypothesis_id"] = c.hypothesis_id
    return out


def list_primitives() -> list[dict[str, str]]:
    return [{"id": p.value, "label": p.value.replace("_", " ")} for p in SearchPrimitive]
