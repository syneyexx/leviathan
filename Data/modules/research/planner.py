"""Deterministic research planner — inspectable, editable, no hidden decisions."""

from __future__ import annotations

import re

from .budgets import budget_for_depth, clamp_budget, merge_budget_overrides
from .types import ResearchBudget, ResearchDepth, ResearchPlan, ResearchProject


_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "about",
        "what",
        "how",
        "why",
        "when",
        "where",
        "is",
        "are",
        "was",
        "were",
        "do",
        "does",
        "did",
        "can",
        "could",
        "should",
        "would",
        "vs",
        "versus",
    }
)


def _tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{1,}", text.lower()) if t not in _STOP]


def _subquestions(topic: str, objective: str, limit: int) -> list[str]:
    base = topic.strip().rstrip("?")
    seeds = [
        f"What is established about {base}?",
        f"What evidence supports claims related to {base}?",
        f"What contradictory or alternative accounts exist for {base}?",
        f"What open questions remain about {base}?",
    ]
    if objective.strip():
        seeds.insert(1, f"How does evidence address the objective: {objective.strip()}?")
    return seeds[: max(1, limit)]


def build_plan(
    project: ResearchProject,
    *,
    budget_overrides: dict | None = None,
) -> ResearchPlan:
    budget = merge_budget_overrides(
        project.budget if project.budget else budget_for_depth(project.depth),
        budget_overrides,
    )
    budget = clamp_budget(budget)
    tokens = _tokenize(f"{project.topic} {project.objective}")
    key = " ".join(tokens[:8]) or project.topic.strip()

    queries: list[str] = []
    if project.topic.strip():
        queries.append(project.topic.strip())
    if key and key.lower() != project.topic.strip().lower():
        queries.append(key)
    # Diversify with entity-like tokens without inventing external sources.
    for token in tokens[: budget.search_queries + 2]:
        candidate = f"{token} {project.topic}".strip()
        if candidate not in queries:
            queries.append(candidate)
        if len(queries) >= budget.search_queries:
            break
    queries = queries[: budget.search_queries] or [project.topic.strip() or "research"]

    preferred = ["knowledge"]
    if project.allow_web:
        preferred.append("web_page")
    if project.seed_sources:
        preferred.append("seed")

    assumptions = [
        "Local KnowledgeStore retrieval is authoritative for offline research.",
        "Citations must resolve to stored evidence spans; unresolved markers are invalid.",
    ]
    if not project.allow_web:
        assumptions.append("Web discovery is disabled for this project.")
    else:
        assumptions.append(
            "Web discovery runs only when a provider is configured and outbound network is allowed."
        )

    exclusions = [
        "Do not fabricate sources or citations.",
        "Do not silently drop contradictory evidence.",
    ]

    return ResearchPlan(
        interpreted_question=project.topic.strip(),
        scope=(
            "local_knowledge"
            if not project.allow_web
            else "local_knowledge+web_when_available"
        ),
        assumptions=assumptions,
        subquestions=_subquestions(project.topic, project.objective, budget.search_queries + 1),
        retrieval_queries=queries,
        preferred_source_types=preferred,
        local_scopes=list(project.local_scopes),
        exclusion_criteria=exclusions,
        rounds=budget.rounds,
        budget=budget,
        notes=(
            f"Depth preset={project.depth.value}; "
            f"workers={budget.research_workers}; "
            f"max_sources={budget.max_sources}."
        ),
        stopping_criteria=[
            "All planned subquestions answered or explicitly unresolved",
            f"At least {max(1, budget.max_sources // 2)} sources ingested or blocked honestly",
            "Contradictions preserved rather than dropped",
        ],
        evidence_coverage_targets={
            "min_sources": max(1, budget.max_sources // 2),
            "min_supported_claims": 1,
            "require_citation_resolution": True,
            "prefer_primary_sources": True,
        },
    )


def apply_plan_edits(plan: ResearchPlan, edits: dict) -> ResearchPlan:
    """Merge operator edits into a stored plan (visible decisions)."""
    data = plan.public_dict()
    for key in (
        "interpreted_question",
        "scope",
        "notes",
    ):
        if key in edits and edits[key] is not None:
            data[key] = str(edits[key])
    for key in (
        "assumptions",
        "subquestions",
        "retrieval_queries",
        "preferred_source_types",
        "local_scopes",
        "exclusion_criteria",
        "stopping_criteria",
    ):
        if key in edits and edits[key] is not None:
            data[key] = list(edits[key])
    if "evidence_coverage_targets" in edits and isinstance(edits["evidence_coverage_targets"], dict):
        data["evidence_coverage_targets"] = dict(edits["evidence_coverage_targets"])
    if "rounds" in edits and edits["rounds"] is not None:
        data["rounds"] = int(edits["rounds"])
    if "budget" in edits and isinstance(edits["budget"], dict):
        data["budget"] = merge_budget_overrides(
            ResearchBudget.from_dict(data.get("budget")), edits["budget"]
        ).public_dict()
    return ResearchPlan.from_dict(data)  # type: ignore[return-value]
