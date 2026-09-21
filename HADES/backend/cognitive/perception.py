"""Pillar 2 — Active Perception.

Decide what to observe next by expected information gain vs cost.
Extends reasoning.information_gain; integrates SharedBudgetPool ceilings.
"""

from __future__ import annotations

from typing import Any

from .contracts import AdaptiveDecision
from .modes import CognitiveMode, mode_allows_influence


def _budget_remaining(pool_snapshot: dict[str, Any] | None) -> dict[str, int | None]:
    if not pool_snapshot:
        return {"tool_calls": None, "model_calls": None}
    def _rem(cur: str, mx: str) -> int | None:
        ceiling = pool_snapshot.get(mx)
        if ceiling is None:
            return None
        return max(0, int(ceiling) - int(pool_snapshot.get(cur) or 0) - int(pool_snapshot.get(f"leased_{cur}") or 0))
    return {
        "tool_calls": _rem("tool_calls", "max_tool_calls"),
        "model_calls": _rem("model_calls", "max_model_calls"),
    }


def select_observation(
    *,
    candidates: list[dict[str, Any]],
    belief_state: dict[str, Any] | None = None,
    uncertainties: list[dict[str, Any]] | None = None,
    known_evidence_text: str = "",
    searched_queries: list[str] | None = None,
    budget_pool: dict[str, Any] | None = None,
    acceptance_satisfied: bool = False,
    mode: CognitiveMode = CognitiveMode.SHADOW,
) -> dict[str, Any]:
    """Choose the cheapest useful observation, or stop if unjustified."""
    belief_state = belief_state or {}
    remaining = _budget_remaining(budget_pool)

    # Reuse deterministic information-gain ranking.
    from reasoning.information_gain import rank_research_steps

    open_questions = []
    contradictions = []
    for u in uncertainties or []:
        cls = str(u.get("uncertainty_class") or "")
        detail = str(u.get("detail") or u.get("uncertainty_class") or "")
        if cls in {"missing_information", "insufficient_coverage", "unverified_assumption"}:
            open_questions.append(detail)
        if cls == "conflicting_evidence":
            contradictions.append(detail)
    if belief_state.get("open_questions"):
        open_questions.extend(str(x) for x in belief_state["open_questions"])

    ranked = rank_research_steps(
        candidates=candidates,
        searched_queries=searched_queries,
        known_evidence_text=known_evidence_text or str(belief_state.get("known_evidence") or ""),
        open_questions=open_questions,
        contradictions=contradictions,
        remaining_tool_budget=remaining.get("tool_calls"),
        remaining_token_budget=None,
        acceptance_satisfied=acceptance_satisfied,
    )

    selected = list(ranked.get("selected") or [])
    # Prefer single cheapest high-gain step (active perception = not consume everything).
    chosen = None
    if selected:
        # ResearchStepProposal.to_dict already has information_gain_score + cost
        def _efficiency(item: dict[str, Any]) -> float:
            gain = float(item.get("information_gain_score") or 0.0)
            cost = item.get("cost") if isinstance(item.get("cost"), dict) else {}
            tool_cost = max(1, int(cost.get("tool_calls") or 1))
            token_cost = max(1, int(cost.get("tokens_est") or 400))
            return gain / (tool_cost + token_cost / 1000.0)

        chosen = max(selected, key=_efficiency)

    influence = mode_allows_influence(mode)
    stop_reason = ranked.get("stop_reason")
    if chosen is None and not stop_reason:
        stop_reason = "no_justified_observation"

    decision = AdaptiveDecision(
        controller="cognitive.perception",
        decision="observe" if chosen and influence else ("recommend_observe" if chosen else "stop"),
        reason_code="HIGH_INFORMATION_GAIN" if chosen else "NO_JUSTIFIED_GAIN",
        mode=mode.value,
        budget=remaining,
        input_refs=[str(c.get("step_id") or c.get("query") or "") for c in candidates[:8]],
        confidence=float(chosen.get("information_gain_score")) if chosen else None,
    )

    # Benchmark helper fields: compare selective vs broad.
    broad_cost = sum(
        int((c.get("cost_tool_calls") if "cost_tool_calls" in c else (c.get("cost") or {}).get("tool_calls") or 1))
        for c in candidates
    )
    selective_cost = 0
    if chosen:
        cost = chosen.get("cost") if isinstance(chosen.get("cost"), dict) else {}
        selective_cost = int(cost.get("tool_calls") or 1)

    return {
        "chosen": chosen if influence else None,
        "recommendation": chosen,
        "skipped": ranked.get("skipped") or [],
        "ranked": selected,
        "stop_reason": stop_reason,
        "remaining_uncertainty": ranked.get("remaining_uncertainty") or open_questions,
        "influence": influence,
        "decision": decision.to_dict(),
        "efficiency": {
            "broad_tool_calls": broad_cost,
            "selective_tool_calls": selective_cost,
            "tool_calls_saved": max(0, broad_cost - selective_cost),
            "mandatory_verification_preserved": bool(ranked.get("mandatory_verification_preserved", True)),
        },
    }


def compare_perception_strategies(
    *,
    candidates: list[dict[str, Any]],
    belief_state: dict[str, Any] | None = None,
    uncertainties: list[dict[str, Any]] | None = None,
    known_evidence_text: str = "",
) -> dict[str, Any]:
    """Benchmark active perception vs broad retrieval on the same candidate set."""
    selective = select_observation(
        candidates=candidates,
        belief_state=belief_state,
        uncertainties=uncertainties,
        known_evidence_text=known_evidence_text,
        mode=CognitiveMode.ACTIVE,
    )
    broad = {
        "observations": len(candidates),
        "tool_calls": selective["efficiency"]["broad_tool_calls"],
        "strategy": "broad_retrieval",
    }
    return {
        "selective": {
            "observations": 1 if selective.get("recommendation") else 0,
            "tool_calls": selective["efficiency"]["selective_tool_calls"],
            "strategy": "active_perception",
            "chosen": selective.get("recommendation"),
        },
        "broad": broad,
        "tool_calls_saved": selective["efficiency"]["tool_calls_saved"],
        "quality_note": "Equal or better verified quality expected when high-gain step addresses the uncertainty; measured per task suite.",
        "mandatory_verification_preserved": selective["efficiency"]["mandatory_verification_preserved"],
    }
