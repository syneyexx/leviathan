"""Configurable research depth budgets — defaults, not architectural constants."""

from __future__ import annotations

from .types import ResearchBudget, ResearchDepth


_PRESETS: dict[ResearchDepth, ResearchBudget] = {
    ResearchDepth.QUICK: ResearchBudget(
        search_queries=1,
        urls_per_query=3,
        max_sources=5,
        rounds=1,
        research_workers=1,
        max_local_hits=6,
        max_evidence_per_source=3,
    ),
    ResearchDepth.STANDARD: ResearchBudget(
        search_queries=2,
        urls_per_query=4,
        max_sources=10,
        rounds=1,
        research_workers=1,
        max_local_hits=12,
        max_evidence_per_source=4,
    ),
    ResearchDepth.DEEP: ResearchBudget(
        search_queries=3,
        urls_per_query=5,
        max_sources=20,
        rounds=2,
        research_workers=2,
        max_local_hits=20,
        max_evidence_per_source=5,
    ),
    ResearchDepth.EXPERT: ResearchBudget(
        search_queries=5,
        urls_per_query=6,
        max_sources=40,
        rounds=3,
        research_workers=3,
        max_local_hits=30,
        max_evidence_per_source=6,
    ),
}

# Hard ceilings so operators cannot accidentally unbounded-crawl.
_CEILINGS = ResearchBudget(
    search_queries=12,
    urls_per_query=10,
    max_sources=80,
    rounds=6,
    research_workers=4,
    max_local_hits=50,
    max_evidence_per_source=10,
)


def budget_for_depth(depth: ResearchDepth | str) -> ResearchBudget:
    if isinstance(depth, str):
        depth = ResearchDepth(depth.lower())
    return _PRESETS[depth]


def clamp_budget(budget: ResearchBudget) -> ResearchBudget:
    return ResearchBudget(
        search_queries=max(1, min(budget.search_queries, _CEILINGS.search_queries)),
        urls_per_query=max(1, min(budget.urls_per_query, _CEILINGS.urls_per_query)),
        max_sources=max(1, min(budget.max_sources, _CEILINGS.max_sources)),
        rounds=max(1, min(budget.rounds, _CEILINGS.rounds)),
        research_workers=max(1, min(budget.research_workers, _CEILINGS.research_workers)),
        max_local_hits=max(1, min(budget.max_local_hits, _CEILINGS.max_local_hits)),
        max_evidence_per_source=max(
            1, min(budget.max_evidence_per_source, _CEILINGS.max_evidence_per_source)
        ),
    )


def merge_budget_overrides(
    base: ResearchBudget,
    overrides: dict | None,
) -> ResearchBudget:
    if not overrides:
        return clamp_budget(base)
    merged = ResearchBudget(
        search_queries=int(overrides.get("search_queries", base.search_queries)),
        urls_per_query=int(overrides.get("urls_per_query", base.urls_per_query)),
        max_sources=int(overrides.get("max_sources", base.max_sources)),
        rounds=int(overrides.get("rounds", base.rounds)),
        research_workers=int(overrides.get("research_workers", base.research_workers)),
        max_local_hits=int(overrides.get("max_local_hits", base.max_local_hits)),
        max_evidence_per_source=int(
            overrides.get("max_evidence_per_source", base.max_evidence_per_source)
        ),
    )
    return clamp_budget(merged)


def list_presets() -> dict[str, dict]:
    return {depth.value: budget.public_dict() for depth, budget in _PRESETS.items()}
