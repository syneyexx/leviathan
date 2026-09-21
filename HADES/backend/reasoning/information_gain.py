"""Deterministic information-gain ranking for optional research/tool steps.

Uses simple, explainable rules — no invented probabilities and no per-step critic LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_WORD = re.compile(r"[a-z0-9]{3,}", re.I)


@dataclass
class ResearchStepProposal:
    step_id: str
    open_question: str
    query: str
    expected_decision_change: str
    already_available: bool
    cost_tool_calls: int = 1
    cost_tokens_est: int = 400
    cost_time_ms_est: int = 1500
    information_gain_score: float = 0.0
    skip_reason: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "open_question": self.open_question,
            "query": self.query,
            "expected_decision_change": self.expected_decision_change,
            "already_available": self.already_available,
            "cost": {
                "tool_calls": self.cost_tool_calls,
                "tokens_est": self.cost_tokens_est,
                "time_ms_est": self.cost_time_ms_est,
            },
            "information_gain_score": self.information_gain_score,
            "skip_reason": self.skip_reason,
            "notes": list(self.notes),
        }


def _normalize_query(text: str) -> str:
    return " ".join(_WORD.findall(str(text or "").lower()))


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(str(text or "").lower()))


def rank_research_steps(
    *,
    candidates: list[dict[str, Any]],
    searched_queries: list[str] | None = None,
    known_evidence_text: str = "",
    open_questions: list[str] | None = None,
    contradictions: list[str] | None = None,
    remaining_tool_budget: int | None = None,
    remaining_token_budget: int | None = None,
    acceptance_satisfied: bool = False,
) -> dict[str, Any]:
    """Rank optional research steps by explainable expected information gain.

    Rules:
    - Skip exact/normalized duplicates of already searched queries.
    - Skip questions whose tokens are already covered by known evidence.
    - Prefer steps that address open questions or contradictions.
    - Respect remaining tool/token budgets; never disable mandatory verification.
    - Stop entirely when acceptance criteria are already satisfied.
    """
    searched = {_normalize_query(q) for q in (searched_queries or []) if q}
    known = _tokens(known_evidence_text)
    open_qs = list(open_questions or [])
    contras = list(contradictions or [])
    ranked: list[ResearchStepProposal] = []
    skipped: list[ResearchStepProposal] = []

    if acceptance_satisfied:
        return {
            "selected": [],
            "skipped": [],
            "stop_reason": "acceptance_criteria_satisfied",
            "remaining_uncertainty": [],
            "ask_for_budget_expansion": False,
            "mandatory_verification_preserved": True,
        }

    for index, raw in enumerate(candidates):
        query = str(raw.get("query") or raw.get("text") or "").strip()
        question = str(raw.get("open_question") or raw.get("question") or query).strip()
        step_id = str(raw.get("step_id") or f"step_{index+1}")
        decision = str(
            raw.get("expected_decision_change")
            or raw.get("decision_impact")
            or "May change whether more evidence is required."
        )
        cost_tools = int(raw.get("cost_tool_calls") or 1)
        cost_tokens = int(raw.get("cost_tokens_est") or 400)
        cost_time = int(raw.get("cost_time_ms_est") or 1500)
        norm = _normalize_query(query)
        q_tokens = _tokens(query + " " + question)
        already = bool(norm and norm in searched)
        coverage = len(q_tokens & known) / max(1, len(q_tokens)) if q_tokens else 0.0
        already_available = already or coverage >= 0.85

        proposal = ResearchStepProposal(
            step_id=step_id,
            open_question=question,
            query=query,
            expected_decision_change=decision,
            already_available=already_available,
            cost_tool_calls=cost_tools,
            cost_tokens_est=cost_tokens,
            cost_time_ms_est=cost_time,
        )

        if not query:
            proposal.skip_reason = "empty_query"
            skipped.append(proposal)
            continue
        if already:
            proposal.skip_reason = "duplicate_searched_query"
            skipped.append(proposal)
            continue
        if already_available:
            proposal.skip_reason = "information_already_available"
            skipped.append(proposal)
            continue
        if remaining_tool_budget is not None and cost_tools > remaining_tool_budget:
            proposal.skip_reason = "exceeds_tool_budget"
            skipped.append(proposal)
            continue
        if remaining_token_budget is not None and cost_tokens > remaining_token_budget:
            proposal.skip_reason = "exceeds_token_budget"
            skipped.append(proposal)
            continue

        score = 1.0
        # Open-question overlap boosts gain.
        for oq in open_qs:
            overlap = len(q_tokens & _tokens(oq)) / max(1, len(_tokens(oq)))
            score += 2.0 * overlap
        # Contradiction addressing boosts gain.
        for c in contras:
            overlap = len(q_tokens & _tokens(c)) / max(1, len(_tokens(c)))
            score += 1.5 * overlap
        # Novelty vs known evidence.
        novelty = 1.0 - coverage
        score += 1.25 * novelty
        # Cheap steps slightly preferred when gain similar (explainable efficiency).
        score -= 0.05 * cost_tools + 0.00005 * cost_tokens
        proposal.information_gain_score = round(score, 4)
        proposal.notes.append("ranked_by_open_question_contradiction_novelty_and_cost")
        ranked.append(proposal)

    ranked.sort(key=lambda item: item.information_gain_score, reverse=True)

    # Budget gate for necessary research that could not be scheduled.
    blocked_for_budget = [s for s in skipped if s.skip_reason in {"exceeds_tool_budget", "exceeds_token_budget"}]
    remaining_uncertainty = [
        s.open_question for s in ranked[1:]  # after selecting top step(s)
    ] + [s.open_question for s in blocked_for_budget]

    selected = ranked[:1]  # one optional step at a time
    if remaining_tool_budget is not None:
        affordable: list[ResearchStepProposal] = []
        used = 0
        for item in ranked:
            if used + item.cost_tool_calls <= remaining_tool_budget:
                affordable.append(item)
                used += item.cost_tool_calls
            if len(affordable) >= 2:
                break
        selected = affordable

    return {
        "selected": [s.to_dict() for s in selected],
        "skipped": [s.to_dict() for s in skipped],
        "stop_reason": None if selected else ("no_valuable_steps" if not ranked else "budget_exhausted"),
        "remaining_uncertainty": remaining_uncertainty[:12],
        "ask_for_budget_expansion": bool(blocked_for_budget),
        "mandatory_verification_preserved": True,
        "ranking_policy": "deterministic_information_gain_v1",
    }


def compare_efficiency(
    *,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    quality_preserved: bool,
) -> dict[str, Any]:
    """Compare tool/token/time totals; fewer calls count as a win only if quality holds."""
    b_tools = int(baseline.get("tool_calls") or 0)
    c_tools = int(candidate.get("tool_calls") or 0)
    b_tokens = int(baseline.get("tokens") or 0)
    c_tokens = int(candidate.get("tokens") or 0)
    b_ms = int(baseline.get("duration_ms") or 0)
    c_ms = int(candidate.get("duration_ms") or 0)
    fewer_tools = c_tools < b_tools
    win = bool(quality_preserved and fewer_tools)
    return {
        "quality_preserved": quality_preserved,
        "fewer_tool_calls": fewer_tools,
        "tool_calls_delta": c_tools - b_tools,
        "tokens_delta": c_tokens - b_tokens,
        "duration_ms_delta": c_ms - b_ms,
        "efficiency_win": win,
        "note": (
            "Fewer calls count as a win only when required quality is preserved."
            if not quality_preserved
            else ("Efficiency improved with quality preserved." if win else "No efficiency win.")
        ),
    }
