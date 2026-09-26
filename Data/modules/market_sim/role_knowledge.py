"""Role-aware trading knowledge retrieval intents.

Extends TradingBrainAdapter — does not create a second Knowledge graph owner.
Knowledge is hypothesis source; only measured experiments qualify strategies.
Negative / contradictory StrategyMemory is first-class for critic/risk/postmortem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .trading_brain import TradingBrainAdapter, TradingRetrievalRequest, TradingRetrievalResult


@dataclass(frozen=True)
class RoleKnowledgeIntent:
    role: str
    focus_terms: tuple[str, ...]
    knowledge_domains: tuple[str, ...]
    asks_for: tuple[str, ...]
    may_cite_as_proof_of_profit: bool = False
    prefer_negative_experience: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "focusTerms": list(self.focus_terms),
            "knowledgeDomains": list(self.knowledge_domains),
            "asksFor": list(self.asks_for),
            "mayCiteAsProofOfProfit": self.may_cite_as_proof_of_profit,
            "preferNegativeExperience": self.prefer_negative_experience,
            "truth": {
                "knowledge_is_hypothesis_source": True,
                "only_measured_experiments_qualify": True,
                "negative_results_are_first_class": True,
            },
        }


ROLE_KNOWLEDGE_INTENTS: dict[str, RoleKnowledgeIntent] = {
    "market_analyst": RoleKnowledgeIntent(
        role="market_analyst",
        focus_terms=("regime", "market structure", "event", "liquidity", "volatility"),
        knowledge_domains=("market_regime", "macro", "asset_context"),
        asks_for=("regime", "market structure", "events", "asset context", "causal market facts"),
    ),
    "strategy_researcher": RoleKnowledgeIntent(
        role="strategy_researcher",
        focus_terms=("strategy structure", "signal", "parameter range", "failure mode", "edge"),
        knowledge_domains=("strategy_family", "indicator", "execution_concept"),
        asks_for=(
            "candidate strategy structures",
            "historically studied signals",
            "parameter ranges as hypotheses",
            "known failure modes",
        ),
    ),
    "critic": RoleKnowledgeIntent(
        role="critic",
        focus_terms=(
            "overfitting",
            "data mining",
            "leakage",
            "transaction cost",
            "survivorship",
            "contradiction",
            "rejected",
            "failure",
        ),
        knowledge_domains=("risk_concept", "methodology", "failure_mode", "strategy_memory"),
        asks_for=(
            "counter-evidence",
            "overfitting concerns",
            "data-mining risks",
            "contradictory research",
            "transaction-cost sensitivity",
            "prior rejected trials",
        ),
        prefer_negative_experience=True,
    ),
    "risk_agent": RoleKnowledgeIntent(
        role="risk_agent",
        focus_terms=("tail risk", "leverage", "concentration", "liquidity", "correlation", "drawdown", "rejected"),
        knowledge_domains=("risk_concept", "portfolio_concept", "liquidity", "strategy_memory"),
        asks_for=(
            "tail risk",
            "leverage",
            "concentration",
            "liquidity",
            "regime failure",
            "correlation",
            "prior rejected regimes",
        ),
        prefer_negative_experience=True,
    ),
    "portfolio_manager": RoleKnowledgeIntent(
        role="portfolio_manager",
        focus_terms=("diversification", "factor overlap", "capital constraint", "allocation"),
        knowledge_domains=("portfolio_concept", "factor", "asset_class"),
        asks_for=(
            "cross-strategy exposure",
            "diversification",
            "factor overlap",
            "capital constraints",
        ),
    ),
    "evaluator": RoleKnowledgeIntent(
        role="evaluator",
        focus_terms=("benchmark", "robustness", "sample size", "multiple testing", "walk forward"),
        knowledge_domains=("methodology", "statistics"),
        asks_for=(
            "methodological risks",
            "benchmark requirements",
            "robustness expectations",
        ),
    ),
    "postmortem": RoleKnowledgeIntent(
        role="postmortem",
        focus_terms=("failed trial", "lesson", "failure category", "regime break", "rejected"),
        knowledge_domains=("failure_mode", "lesson", "trial_data", "strategy_memory"),
        asks_for=(
            "similar failed trials",
            "validated lessons",
            "prior failure categories",
        ),
        prefer_negative_experience=True,
    ),
}

# Roles that must surface contradictory / negative StrategyMemory.
NEGATIVE_SURFACE_ROLES = frozenset({"critic", "risk_agent", "postmortem"})


@dataclass
class CitedKnowledgeHit:
    role: str
    query: str
    hit: dict[str, Any]
    citation: dict[str, Any]
    hypothesis_only: bool = True

    def public_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "query": self.query,
            "hit": self.hit,
            "citation": self.citation,
            "hypothesisOnly": self.hypothesis_only,
            "truth": {
                "knowledge_not_proof_of_profitability": True,
                "citation_required_for_agent_claim": True,
            },
        }


def intent_for_role(role: str) -> RoleKnowledgeIntent | None:
    key = str(role or "").strip().lower()
    aliases = {
        "strategy_critic": "critic",
        "risk_officer": "risk_agent",
        "postmortem_agent": "postmortem",
        "researcher": "strategy_researcher",
        "signal_analyst": "strategy_researcher",
    }
    key = aliases.get(key, key)
    return ROLE_KNOWLEDGE_INTENTS.get(key)


def build_role_retrieval_request(
    role: str,
    query: str,
    *,
    symbols: list[str] | None = None,
    decision_as_of: str | None = None,
    max_hits: int = 5,
    extra_terms: list[str] | None = None,
    regime: str | None = None,
    strategy_family: str | None = None,
) -> TradingRetrievalRequest:
    intent = intent_for_role(role)
    focus = list(intent.focus_terms) if intent else []
    if extra_terms:
        focus.extend(extra_terms)
    expanded = query.strip()
    if focus:
        expanded = f"{expanded} " + " ".join(focus[:6])
    return TradingRetrievalRequest(
        query=expanded,
        role=intent.role if intent else role,
        symbols=list(symbols or []),
        decision_as_of=decision_as_of,
        knowledge_domains=list(intent.knowledge_domains) if intent else [],
        max_hits=max_hits,
        objective="; ".join(intent.asks_for[:3]) if intent else None,
        prefer_semantic=True,
        regime=regime,
        strategy_family=strategy_family,
    )


def evidence_refs_from_role_payload(payload: dict[str, Any]) -> list[str]:
    """Extract durable memory / document IDs suitable for DecisionRecord evidenceRefs."""
    refs: list[str] = []
    seen: set[str] = set()
    for cite in payload.get("citations") or []:
        citation = cite.get("citation") if isinstance(cite, dict) else None
        hit = cite.get("hit") if isinstance(cite, dict) else None
        candidates = []
        if isinstance(citation, dict):
            candidates.extend(
                [
                    citation.get("memoryId"),
                    citation.get("documentId"),
                    citation.get("strategyMemoryId"),
                ]
            )
            for er in citation.get("evidenceRefs") or []:
                candidates.append(er)
        if isinstance(hit, dict):
            candidates.extend(
                [
                    hit.get("documentId"),
                    hit.get("document_id"),
                    hit.get("memoryId"),
                ]
            )
            for er in hit.get("evidenceRefs") or hit.get("evidence_refs") or []:
                candidates.append(er)
        for c in candidates:
            if not c:
                continue
            s = str(c)
            if s not in seen:
                seen.add(s)
                refs.append(s)
    return refs


class RoleAwareTradingKnowledge:
    """Retrieve + cite trading knowledge for institutional agent roles."""

    def __init__(self, adapter: TradingBrainAdapter) -> None:
        self.adapter = adapter

    def retrieve_for_role(
        self,
        role: str,
        query: str,
        *,
        symbols: list[str] | None = None,
        decision_as_of: str | None = None,
        max_hits: int = 5,
        firewall: Any | None = None,
        regime: str | None = None,
        strategy_family: str | None = None,
        extra_terms: list[str] | None = None,
    ) -> dict[str, Any]:
        intent = intent_for_role(role)
        prefer_negative = bool(intent and intent.prefer_negative_experience)
        request = build_role_retrieval_request(
            role,
            query,
            symbols=symbols,
            decision_as_of=decision_as_of,
            max_hits=max_hits,
            extra_terms=extra_terms,
            regime=regime,
            strategy_family=strategy_family,
        )
        result: TradingRetrievalResult = self.adapter.retrieve(
            request,
            firewall=firewall,
            prefer_negative=prefer_negative,
        )
        citations: list[CitedKnowledgeHit] = []
        negative_count = 0
        for hit in result.hits:
            pub = hit.public_dict()
            if pub.get("rejected") or pub.get("contradictory"):
                negative_count += 1
            citations.append(
                CitedKnowledgeHit(
                    role=request.role or role,
                    query=query,
                    hit=pub,
                    citation={
                        "documentId": pub.get("documentId"),
                        "memoryId": pub.get("documentId") if pub.get("sourceKind") == "strategy_memory" else None,
                        "strategyMemoryId": pub.get("documentId")
                        if pub.get("sourceKind") == "strategy_memory"
                        else None,
                        "datasetId": pub.get("datasetId"),
                        "chunkId": pub.get("chunkId"),
                        "title": pub.get("title"),
                        "score": pub.get("score"),
                        "availableAt": pub.get("availableAt"),
                        "retrievalMode": pub.get("retrievalMode"),
                        "origin": pub.get("origin"),
                        "epistemicState": pub.get("epistemicState"),
                        "validationStage": pub.get("validationStage"),
                        "strategyId": pub.get("strategyId"),
                        "strategyVersion": pub.get("strategyVersion"),
                        "rejected": pub.get("rejected"),
                        "contradictory": pub.get("contradictory"),
                        "evidenceRefs": list(pub.get("evidenceRefs") or []),
                    },
                    hypothesis_only=True,
                )
            )
        payload = {
            "role": request.role or role,
            "intent": intent.public_dict() if intent else None,
            "request": request.public_dict(),
            "result": result.public_dict(),
            "citations": [c.public_dict() for c in citations],
            "evidenceRefs": evidence_refs_from_role_payload(
                {"citations": [c.public_dict() for c in citations]}
            ),
            "negativeExperienceCount": negative_count,
            "truth": {
                "knowledge_is_hypothesis_source": True,
                "only_leviathan_measured_experiments_qualify": True,
                "agents_must_carry_references": True,
                "negative_results_are_first_class": True,
                "knowledge_is_not_execution_authority": True,
            },
        }
        return payload
