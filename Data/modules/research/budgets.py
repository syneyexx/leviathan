"""Configurable research depth budgets — defaults, not architectural constants.

TEAM mode uses completion_policy=quality_contract with rounds=None (unbounded
cumulative work). NORMAL/CUSTOM retain fixed integer round semantics.
"""

from __future__ import annotations

from typing import Any

from .types import ResearchBudget, ResearchDepth, ResearchExecutionMode


_PRESETS: dict[ResearchDepth, ResearchBudget] = {
    ResearchDepth.QUICK: ResearchBudget(
        search_queries=1,
        urls_per_query=3,
        max_sources=5,
        rounds=1,
        research_workers=1,
        max_local_hits=6,
        max_evidence_per_source=3,
        completion_policy="fixed_budget",
    ),
    ResearchDepth.STANDARD: ResearchBudget(
        search_queries=2,
        urls_per_query=4,
        max_sources=10,
        rounds=1,
        research_workers=1,
        max_local_hits=12,
        max_evidence_per_source=4,
        completion_policy="fixed_budget",
    ),
    ResearchDepth.DEEP: ResearchBudget(
        search_queries=3,
        urls_per_query=5,
        max_sources=20,
        rounds=2,
        research_workers=2,
        max_local_hits=20,
        max_evidence_per_source=5,
        completion_policy="fixed_budget",
    ),
    ResearchDepth.EXPERT: ResearchBudget(
        search_queries=5,
        urls_per_query=6,
        max_sources=40,
        rounds=3,
        research_workers=3,
        max_local_hits=30,
        max_evidence_per_source=6,
        completion_policy="fixed_budget",
    ),
}

# Operator ceilings for FIXED-BUDGET modes. TEAM does not use rounds as a success gate.
_CEILINGS = ResearchBudget(
    search_queries=12,
    urls_per_query=10,
    max_sources=80,
    rounds=100,
    research_workers=16,
    max_local_hits=50,
    max_evidence_per_source=10,
    completion_policy="fixed_budget",
)

_LIMITS = {
    "research_workers": {"min": 1, "max": 16},
    "rounds": {"min": 1, "max": 100},
    "search_queries": {"min": 1, "max": 12},
    "urls_per_query": {"min": 1, "max": 10},
    "max_sources": {"min": 1, "max": 80},
    "max_local_hits": {"min": 1, "max": 50},
    "max_evidence_per_source": {"min": 1, "max": 10},
}

NORMAL_WORKERS = 2
NORMAL_ROUNDS = 10

# Per-batch resource bounds for TEAM (not cumulative success gates).
TEAM_DEFAULT_WORKERS = 2
TEAM_BATCH_QUERIES = 5
TEAM_BATCH_SOURCES = 20


def budget_for_depth(depth: ResearchDepth | str) -> ResearchBudget:
    if isinstance(depth, str):
        depth = ResearchDepth(depth.lower())
    return _PRESETS[depth]


def clamp_budget(budget: ResearchBudget) -> ResearchBudget:
    """Clamp fixed-budget fields. Preserves rounds=None for quality_contract."""
    rounds = budget.rounds
    if rounds is not None:
        ceiling_rounds = int(_CEILINGS.rounds or 100)
        rounds = max(1, min(int(rounds), ceiling_rounds))
    max_iter = budget.max_iterations
    if max_iter is not None and max_iter < 0:
        raise ValueError("max_iterations must be null or non-negative")
    max_total = budget.max_total_sources
    if max_total is not None and max_total < 0:
        raise ValueError("max_total_sources must be null or non-negative")
    return ResearchBudget(
        search_queries=max(1, min(budget.search_queries, _CEILINGS.search_queries)),
        urls_per_query=max(1, min(budget.urls_per_query, _CEILINGS.urls_per_query)),
        max_sources=max(1, min(budget.max_sources, _CEILINGS.max_sources)),
        rounds=rounds,
        research_workers=max(1, min(budget.research_workers, _CEILINGS.research_workers)),
        max_local_hits=max(1, min(budget.max_local_hits, _CEILINGS.max_local_hits)),
        max_evidence_per_source=max(
            1, min(budget.max_evidence_per_source, _CEILINGS.max_evidence_per_source)
        ),
        completion_policy=str(budget.completion_policy or "fixed_budget"),
        max_iterations=max_iter,
        max_total_sources=max_total,
    )


def merge_budget_overrides(
    base: ResearchBudget,
    overrides: dict | None,
) -> ResearchBudget:
    if not overrides:
        return clamp_budget(base)
    rounds_raw = overrides["rounds"] if "rounds" in overrides else base.rounds
    if rounds_raw is None:
        rounds: int | None = None
    else:
        rounds = int(rounds_raw)
    max_iter = (
        overrides["max_iterations"]
        if "max_iterations" in overrides
        else base.max_iterations
    )
    max_total = (
        overrides["max_total_sources"]
        if "max_total_sources" in overrides
        else base.max_total_sources
    )
    policy = str(
        overrides.get("completion_policy")
        or base.completion_policy
        or "fixed_budget"
    )
    merged = ResearchBudget(
        search_queries=int(overrides.get("search_queries", base.search_queries)),
        urls_per_query=int(overrides.get("urls_per_query", base.urls_per_query)),
        max_sources=int(overrides.get("max_sources", base.max_sources)),
        rounds=rounds,
        research_workers=int(overrides.get("research_workers", base.research_workers)),
        max_local_hits=int(overrides.get("max_local_hits", base.max_local_hits)),
        max_evidence_per_source=int(
            overrides.get("max_evidence_per_source", base.max_evidence_per_source)
        ),
        completion_policy=policy,
        max_iterations=None if max_iter is None else int(max_iter),
        max_total_sources=None if max_total is None else int(max_total),
    )
    return clamp_budget(merged)


def team_budget_from_depth(base: ResearchBudget) -> ResearchBudget:
    """TEAM: quality_contract policy, null rounds, batch resource bounds retained."""
    return clamp_budget(
        ResearchBudget(
            search_queries=max(base.search_queries, TEAM_BATCH_QUERIES),
            urls_per_query=base.urls_per_query,
            max_sources=max(base.max_sources, TEAM_BATCH_SOURCES),
            rounds=None,
            research_workers=min(
                max(base.research_workers, TEAM_DEFAULT_WORKERS),
                _CEILINGS.research_workers,
            ),
            max_local_hits=base.max_local_hits,
            max_evidence_per_source=base.max_evidence_per_source,
            completion_policy="quality_contract",
            max_iterations=None,
            max_total_sources=None,
        )
    )


def resolve_execution_budget(
    *,
    execution_mode: ResearchExecutionMode | str,
    base: ResearchBudget,
    overrides: dict | None = None,
) -> ResearchBudget:
    """Apply Normal/Custom/TEAM mode semantics on top of depth/override budgets."""
    mode = (
        execution_mode
        if isinstance(execution_mode, ResearchExecutionMode)
        else ResearchExecutionMode(str(execution_mode).lower())
    )
    if mode == ResearchExecutionMode.NORMAL:
        return clamp_budget(
            ResearchBudget(
                search_queries=base.search_queries,
                urls_per_query=base.urls_per_query,
                max_sources=base.max_sources,
                rounds=NORMAL_ROUNDS,
                research_workers=NORMAL_WORKERS,
                max_local_hits=base.max_local_hits,
                max_evidence_per_source=base.max_evidence_per_source,
                completion_policy="fixed_budget",
            )
        )
    if mode == ResearchExecutionMode.TEAM:
        merged = merge_budget_overrides(base, overrides) if overrides else base
        # TEAM forces quality_contract + null rounds unless user set an explicit cap
        # via max_iterations (optional). rounds stays None.
        team = team_budget_from_depth(merged)
        if overrides:
            # Allow optional user caps only.
            max_iter = overrides.get("max_iterations", team.max_iterations)
            max_total = overrides.get("max_total_sources", team.max_total_sources)
            workers = int(overrides.get("research_workers", team.research_workers))
            return clamp_budget(
                ResearchBudget(
                    search_queries=team.search_queries,
                    urls_per_query=team.urls_per_query,
                    max_sources=team.max_sources,
                    rounds=None,
                    research_workers=workers,
                    max_local_hits=team.max_local_hits,
                    max_evidence_per_source=team.max_evidence_per_source,
                    completion_policy="quality_contract",
                    max_iterations=None if max_iter is None else int(max_iter),
                    max_total_sources=None if max_total is None else int(max_total),
                )
            )
        return team
    return merge_budget_overrides(base, overrides)


def effective_round_ceiling(budget: ResearchBudget) -> int | None:
    """Fixed-budget ceiling, or None when quality-driven (TEAM)."""
    if budget.completion_policy == "quality_contract" or budget.rounds is None:
        return None
    return int(budget.rounds)


def list_presets() -> dict[str, dict]:
    return {depth.value: budget.public_dict() for depth, budget in _PRESETS.items()}


def budget_catalog() -> dict:
    """Full budget + execution-mode catalog for the Research UI."""
    return {
        "presets": list_presets(),
        "ceilings": _CEILINGS.public_dict(),
        "limits": dict(_LIMITS),
        "execution_modes": {
            ResearchExecutionMode.NORMAL.value: {
                "research_workers": NORMAL_WORKERS,
                "rounds": NORMAL_ROUNDS,
                "locked": True,
                "completion_policy": "fixed_budget",
                "description": "2 workers × 10 rounds each (20 worker-rounds)",
            },
            ResearchExecutionMode.CUSTOM.value: {
                "limits": {
                    "research_workers": dict(_LIMITS["research_workers"]),
                    "rounds": dict(_LIMITS["rounds"]),
                },
                "locked": False,
                "completion_policy": "fixed_budget",
                "description": "Operator-selected workers and rounds per worker",
            },
            ResearchExecutionMode.TEAM.value: {
                "research_workers": {"min": 1, "max": 16, "default": TEAM_DEFAULT_WORKERS},
                "rounds": None,
                "locked": False,
                "completion_policy": "quality_contract",
                "description": (
                    "Continues until the quality criteria are met, or shows exactly "
                    "what prevents completion. No fixed cumulative round total."
                ),
                "optional_caps": {
                    "max_iterations": {"null_means_unbounded": True},
                    "max_total_sources": {"null_means_unbounded": True},
                },
            },
        },
    }


def validate_budget_input(raw: dict[str, Any] | None, *, execution_mode: str) -> None:
    """Reject negative limits and incompatible combinations."""
    if not raw:
        return
    mode = str(execution_mode or "").lower()
    for key in (
        "search_queries",
        "urls_per_query",
        "max_sources",
        "research_workers",
        "max_local_hits",
        "max_evidence_per_source",
    ):
        if key in raw and raw[key] is not None and int(raw[key]) < 0:
            raise ValueError(f"{key} must be non-negative")
    if "rounds" in raw and raw["rounds"] is not None:
        if int(raw["rounds"]) < 0:
            raise ValueError("rounds must be null or non-negative")
        if mode == ResearchExecutionMode.TEAM.value and raw["rounds"] is not None:
            # TEAM ignores fixed rounds; reject incompatible attempt to force success via rounds.
            pass  # silently coerced to None in resolve_execution_budget
    for key in ("max_iterations", "max_total_sources"):
        if key in raw and raw[key] is not None and int(raw[key]) < 0:
            raise ValueError(f"{key} must be null or non-negative")
