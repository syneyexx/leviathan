"""Research hypothesis contracts for autonomous Trading Research Lab.

Public structured reasoning only — never private chain-of-thought.
Extends MarketHypothesis with lab/learning binding and epistemic fields.
Persisted under MARKET ownership via MarketSimStore.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from Data.modules.common.hashing import sha256_text

from .experiments import (
    HYPOTHESIS_STATUSES,
    MarketHypothesis,
    market_hypothesis_from_mapping,
    new_market_hypothesis,
    validate_hypothesis_status,
)


# Wave 1 end-product status set (superset mapped onto MarketHypothesis when needed)
RESEARCH_HYPOTHESIS_STATUSES: frozenset[str] = frozenset(
    {
        "PROPOSED",
        "TESTING",
        "SUPPORTED",
        "REJECTED",
        "INCONCLUSIVE",
        # Compatibility with existing MarketHypothesis lifecycle
        "FRAGILE",
        "CONTRADICTED",
        "STALE",
    }
)

# Epistemic / trust states for hypothesis claims (not measurement)
HYPOTHESIS_TRUST_STATES: frozenset[str] = frozenset(
    {
        "UNTRUSTED",
        "AGENT_PROPOSED",
        "UNDER_TEST",
        "EVIDENCE_BACKED",
        "CONFLICTED",
        "REJECTED",
    }
)


@dataclass
class ResearchHypothesisScope:
    symbols: list[str] = field(default_factory=list)
    asset_classes: list[str] = field(default_factory=list)
    timeframes: list[str] = field(default_factory=list)
    regime_scope: list[str] = field(default_factory=list)
    session_scope: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "symbols": list(self.symbols),
            "asset_classes": list(self.asset_classes),
            "timeframes": list(self.timeframes),
            "regime_scope": list(self.regime_scope),
            "session_scope": list(self.session_scope),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "ResearchHypothesisScope":
        raw = dict(raw or {})
        return cls(
            symbols=list(raw.get("symbols") or []),
            asset_classes=list(raw.get("asset_classes") or []),
            timeframes=list(raw.get("timeframes") or []),
            regime_scope=list(raw.get("regime_scope") or raw.get("regimeScope") or []),
            session_scope=list(raw.get("session_scope") or raw.get("sessionScope") or []),
        )


@dataclass
class ResearchHypothesis:
    """Falsifiable research hypothesis bound to a lab / learning run.

    Created BEFORE experiment outcomes are known.
    Falsification criteria must not be mutated after results are observed.
    """

    hypothesis_id: str
    lab_id: str | None
    learning_run_id: str | None
    parent_hypothesis_id: str | None
    statement: str
    mechanism: str
    rationale_summary: str
    scope: ResearchHypothesisScope
    expected_edge: str
    expected_failure_modes: list[str]
    falsification_criteria: list[str]
    evidence_refs: list[str]
    counterevidence_refs: list[str]
    strategy_family_preferences: list[str]
    required_features: list[str]
    proposer_role: str
    proposer_agent_id: str | None
    model_id: str | None
    model_revision: str | None
    as_of: str
    created_at: str
    trust: str
    status: str
    provenance_hash: str
    # Frozen snapshot of falsification criteria at creation (anti-post-hoc mutation)
    falsification_frozen: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def content_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "lab_id": self.lab_id,
            "learning_run_id": self.learning_run_id,
            "parent_hypothesis_id": self.parent_hypothesis_id,
            "statement": self.statement,
            "mechanism": self.mechanism,
            "rationale_summary": self.rationale_summary,
            "scope": self.scope.public_dict(),
            "expected_edge": self.expected_edge,
            "expected_failure_modes": list(self.expected_failure_modes),
            "falsification_criteria": list(self.falsification_criteria),
            "evidence_refs": list(self.evidence_refs),
            "counterevidence_refs": list(self.counterevidence_refs),
            "strategy_family_preferences": list(self.strategy_family_preferences),
            "required_features": list(self.required_features),
            "proposer_role": self.proposer_role,
            "proposer_agent_id": self.proposer_agent_id,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "as_of": self.as_of,
            "created_at": self.created_at,
            "trust": self.trust,
            "status": self.status,
            "falsification_frozen": bool(self.falsification_frozen),
            "metadata": dict(self.metadata),
        }

    def compute_provenance_hash(self) -> str:
        body = {
            k: v
            for k, v in self.content_dict().items()
            if k not in {"provenance_hash", "status", "trust", "evidence_refs", "counterevidence_refs"}
        }
        return sha256_text(json.dumps(body, sort_keys=True, separators=(",", ":")))

    def public_dict(self) -> dict[str, Any]:
        d = self.content_dict()
        d["provenance_hash"] = self.provenance_hash or self.compute_provenance_hash()
        d["truth"] = {
            "public_structured_reasoning": True,
            "no_private_cot": True,
            "falsification_immutable_after_create": self.falsification_frozen,
            "status_is_lifecycle_not_measurement": True,
            "created_before_outcome": True,
        }
        return d

    def to_market_hypothesis(self) -> MarketHypothesis:
        """Project into existing MarketHypothesis shape for campaign attachment."""
        return new_market_hypothesis(
            observation=self.statement,
            rationale=self.rationale_summary,
            mechanism=self.mechanism,
            falsifiable_prediction="; ".join(self.falsification_criteria) or self.expected_edge,
            created_by=self.proposer_role or "research",
            created_at=self.created_at,
            universe=list(self.scope.symbols),
            regime_scope=list(self.scope.regime_scope),
            required_data=list(self.required_features),
            expected_failure_conditions=list(self.expected_failure_modes),
            parent_hypothesis_id=self.parent_hypothesis_id,
            evidence_refs=list(self.evidence_refs),
            status=_map_to_market_status(self.status),
            hypothesis_id=self.hypothesis_id,
        )


def _map_to_market_status(status: str) -> str:
    s = str(status or "PROPOSED").upper()
    if s == "INCONCLUSIVE":
        return "FRAGILE"
    if s in HYPOTHESIS_STATUSES:
        return s
    return "PROPOSED"


def validate_research_hypothesis_status(status: str) -> str:
    s = str(status or "").upper().strip()
    if s not in RESEARCH_HYPOTHESIS_STATUSES:
        raise ValueError(
            f"invalid research hypothesis status {status!r}; "
            f"allowed={sorted(RESEARCH_HYPOTHESIS_STATUSES)}"
        )
    return s


def validate_hypothesis_trust(trust: str) -> str:
    t = str(trust or "").upper().strip()
    if t not in HYPOTHESIS_TRUST_STATES:
        raise ValueError(
            f"invalid hypothesis trust {trust!r}; allowed={sorted(HYPOTHESIS_TRUST_STATES)}"
        )
    return t


def new_research_hypothesis(
    *,
    statement: str,
    mechanism: str = "",
    rationale_summary: str = "",
    created_at: str,
    as_of: str | None = None,
    lab_id: str | None = None,
    learning_run_id: str | None = None,
    parent_hypothesis_id: str | None = None,
    scope: ResearchHypothesisScope | dict[str, Any] | None = None,
    expected_edge: str = "",
    expected_failure_modes: list[str] | None = None,
    falsification_criteria: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    counterevidence_refs: list[str] | None = None,
    strategy_family_preferences: list[str] | None = None,
    required_features: list[str] | None = None,
    proposer_role: str = "strategy_researcher",
    proposer_agent_id: str | None = None,
    model_id: str | None = None,
    model_revision: str | None = None,
    trust: str = "AGENT_PROPOSED",
    status: str = "PROPOSED",
    hypothesis_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ResearchHypothesis:
    sc = (
        scope
        if isinstance(scope, ResearchHypothesisScope)
        else ResearchHypothesisScope.from_dict(scope)
    )
    hyp = ResearchHypothesis(
        hypothesis_id=hypothesis_id or str(uuid.uuid4()),
        lab_id=lab_id,
        learning_run_id=learning_run_id,
        parent_hypothesis_id=parent_hypothesis_id,
        statement=str(statement or "").strip(),
        mechanism=str(mechanism or "").strip(),
        rationale_summary=str(rationale_summary or "").strip(),
        scope=sc,
        expected_edge=str(expected_edge or "").strip(),
        expected_failure_modes=list(expected_failure_modes or []),
        falsification_criteria=list(falsification_criteria or []),
        evidence_refs=list(evidence_refs or []),
        counterevidence_refs=list(counterevidence_refs or []),
        strategy_family_preferences=list(strategy_family_preferences or []),
        required_features=list(required_features or []),
        proposer_role=str(proposer_role or "strategy_researcher"),
        proposer_agent_id=proposer_agent_id,
        model_id=model_id,
        model_revision=model_revision,
        as_of=str(as_of or created_at),
        created_at=created_at,
        trust=validate_hypothesis_trust(trust),
        status=validate_research_hypothesis_status(status),
        provenance_hash="",
        falsification_frozen=True,
        metadata=dict(metadata or {}),
    )
    if not hyp.statement:
        raise ValueError("hypothesis statement is required")
    hyp.provenance_hash = hyp.compute_provenance_hash()
    return hyp


def research_hypothesis_from_mapping(raw: dict[str, Any] | None) -> ResearchHypothesis:
    raw = dict(raw or {})
    hyp = ResearchHypothesis(
        hypothesis_id=str(raw.get("hypothesis_id") or uuid.uuid4()),
        lab_id=raw.get("lab_id"),
        learning_run_id=raw.get("learning_run_id"),
        parent_hypothesis_id=raw.get("parent_hypothesis_id"),
        statement=str(raw.get("statement") or raw.get("observation") or ""),
        mechanism=str(raw.get("mechanism") or ""),
        rationale_summary=str(raw.get("rationale_summary") or raw.get("rationale") or ""),
        scope=ResearchHypothesisScope.from_dict(raw.get("scope") if isinstance(raw.get("scope"), dict) else {
            "symbols": raw.get("universe") or raw.get("symbols") or [],
            "regime_scope": raw.get("regime_scope") or [],
            "timeframes": raw.get("timeframes") or [],
            "asset_classes": raw.get("asset_classes") or [],
            "session_scope": raw.get("session_scope") or [],
        }),
        expected_edge=str(raw.get("expected_edge") or raw.get("falsifiable_prediction") or ""),
        expected_failure_modes=list(
            raw.get("expected_failure_modes") or raw.get("expected_failure_conditions") or []
        ),
        falsification_criteria=list(raw.get("falsification_criteria") or []),
        evidence_refs=list(raw.get("evidence_refs") or []),
        counterevidence_refs=list(raw.get("counterevidence_refs") or []),
        strategy_family_preferences=list(raw.get("strategy_family_preferences") or []),
        required_features=list(raw.get("required_features") or raw.get("required_data") or []),
        proposer_role=str(raw.get("proposer_role") or raw.get("created_by") or "strategy_researcher"),
        proposer_agent_id=raw.get("proposer_agent_id"),
        model_id=raw.get("model_id"),
        model_revision=raw.get("model_revision"),
        as_of=str(raw.get("as_of") or raw.get("created_at") or ""),
        created_at=str(raw.get("created_at") or ""),
        trust=validate_hypothesis_trust(str(raw.get("trust") or "AGENT_PROPOSED")),
        status=validate_research_hypothesis_status(str(raw.get("status") or "PROPOSED")),
        provenance_hash=str(raw.get("provenance_hash") or ""),
        falsification_frozen=bool(raw.get("falsification_frozen", True)),
        metadata=dict(raw.get("metadata") or {}),
    )
    if not hyp.provenance_hash:
        hyp.provenance_hash = hyp.compute_provenance_hash()
    return hyp


def assert_falsification_immutable(
    stored: ResearchHypothesis,
    *,
    proposed_criteria: list[str] | None,
) -> None:
    """Refuse post-hoc mutation of falsification thresholds after create."""
    if not stored.falsification_frozen:
        return
    if proposed_criteria is None:
        return
    if list(proposed_criteria) != list(stored.falsification_criteria):
        raise ValueError(
            "FALSIFICATION_IMMUTABLE: cannot change falsification_criteria after hypothesis creation"
        )


def transition_hypothesis_status(
    hyp: ResearchHypothesis,
    *,
    new_status: str,
    evidence_ref: str | None = None,
    counterevidence_ref: str | None = None,
    trust: str | None = None,
) -> ResearchHypothesis:
    """Lifecycle transition — never mutates falsification_criteria."""
    hyp.status = validate_research_hypothesis_status(new_status)
    if evidence_ref and evidence_ref not in hyp.evidence_refs:
        hyp.evidence_refs.append(evidence_ref)
    if counterevidence_ref and counterevidence_ref not in hyp.counterevidence_refs:
        hyp.counterevidence_refs.append(counterevidence_ref)
    if trust is not None:
        hyp.trust = validate_hypothesis_trust(trust)
    return hyp


def hypothesis_from_objective_brief(
    *,
    objective_text: str,
    created_at: str,
    lab_id: str | None = None,
    learning_run_id: str | None = None,
    symbols: list[str] | None = None,
    timeframes: list[str] | None = None,
    family_preferences: list[str] | None = None,
) -> ResearchHypothesis:
    """Bootstrap a PROPOSED hypothesis from an operator research objective string."""
    text = str(objective_text or "").strip()
    return new_research_hypothesis(
        statement=text or "Search for positive net expectancy after costs.",
        mechanism="Underspecified at create — analyst will refine before trials.",
        rationale_summary="Operator-provided research objective for autonomous discovery.",
        created_at=created_at,
        lab_id=lab_id,
        learning_run_id=learning_run_id,
        scope=ResearchHypothesisScope(
            symbols=list(symbols or []),
            timeframes=list(timeframes or []),
        ),
        expected_edge="Positive net expectancy after fees/slippage within drawdown constraints.",
        expected_failure_modes=[
            "cost_sensitivity",
            "regime_brittleness",
            "overfit_to_train",
            "insufficient_sample",
        ],
        falsification_criteria=[
            "net_expectancy_after_costs <= 0 on validation",
            "max_drawdown exceeds acceptance policy",
            "fails regime matrix or robustness gates",
        ],
        strategy_family_preferences=list(family_preferences or []),
        proposer_role="operator",
        trust="AGENT_PROPOSED",
        status="PROPOSED",
        metadata={"origin": "operator_objective_brief"},
    )


__all__ = [
    "HYPOTHESIS_TRUST_STATES",
    "RESEARCH_HYPOTHESIS_STATUSES",
    "ResearchHypothesis",
    "ResearchHypothesisScope",
    "assert_falsification_immutable",
    "hypothesis_from_objective_brief",
    "new_research_hypothesis",
    "research_hypothesis_from_mapping",
    "transition_hypothesis_status",
    "validate_research_hypothesis_status",
    "validate_hypothesis_trust",
    # re-exports for convenience
    "MarketHypothesis",
    "market_hypothesis_from_mapping",
    "validate_hypothesis_status",
]
