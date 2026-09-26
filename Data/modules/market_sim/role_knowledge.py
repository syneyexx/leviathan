"""Role-aware trading knowledge retrieval intents.

Extends TradingBrainAdapter — does not create a second Knowledge graph owner.
Knowledge is hypothesis source; only measured experiments qualify strategies.
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

    def public_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "focusTerms": list(self.focus_terms),
            "knowledgeDomains": list(self.knowledge_domains),
            "asksFor": list(self.asks_for),
            "mayCiteAsProofOfProfit": self.may_cite_as_proof_of_profit,
            "truth": {
                "knowledge_is_hypothesis_source": True,
                "only_measured_experiments_qualify": True,
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
        ),
        knowledge_domains=("risk_concept", "methodology", "failure_mode"),
        asks_for=(
            "counter-evidence",
            "overfitting concerns",
            "data-mining risks",
            "contradictory research",
            "transaction-cost sensitivity",
        ),
    ),
    "risk_agent": RoleKnowledgeIntent(
        role="risk_agent",
        focus_terms=("tail risk", "leverage", "concentration", "liquidity", "correlation", "drawdown"),
        knowledge_domains=("risk_concept", "portfolio_concept", "liquidity"),
        asks_for=(
            "tail risk",
            "leverage",
            "concentration",
            "liquidity",
            "regime failure",
            "correlation",
        ),
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
        focus_terms=("failed trial", "lesson", "failure category", "regime break"),
        knowledge_domains=("failure_mode", "lesson", "trial_data"),
        asks_for=(
            "similar failed trials",
            "validated lessons",
            "prior failure categories",
        ),
    ),
}


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
    )


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
    ) -> dict[str, Any]:
        intent = intent_for_role(role)
        request = build_role_retrieval_request(
            role,
            query,
            symbols=symbols,
            decision_as_of=decision_as_of,
            max_hits=max_hits,
        )
        result: TradingRetrievalResult = self.adapter.retrieve(request, firewall=firewall)
        citations: list[CitedKnowledgeHit] = []
        for hit in result.hits:
            pub = hit.public_dict()
            citations.append(
                CitedKnowledgeHit(
                    role=request.role or role,
                    query=query,
                    hit=pub,
                    citation={
                        "documentId": pub.get("documentId"),
                        "datasetId": pub.get("datasetId"),
                        "chunkId": pub.get("chunkId"),
                        "title": pub.get("title"),
                        "score": pub.get("score"),
                        "availableAt": pub.get("availableAt"),
                        "retrievalMode": pub.get("retrievalMode"),
                    },
                    hypothesis_only=True,
                )
            )
        return {
            "role": request.role or role,
            "intent": intent.public_dict() if intent else None,
            "request": request.public_dict(),
            "result": result.public_dict(),
            "citations": [c.public_dict() for c in citations],
            "truth": {
                "knowledge_is_hypothesis_source": True,
                "only_leviathan_measured_experiments_qualify": True,
                "agents_must_carry_references": True,
            },
        }
