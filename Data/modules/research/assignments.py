"""Specialized research lane assignments for multi-worker runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .gaps import ResearchGap
from .types import ResearchPlan, ResearchWorker


WORKER_ROLES = (
    "primary_source_hunter",
    "independent_confirmation",
    "contradiction_hunter",
    "historical_context",
    "quantitative_data",
    "technical_docs",
    "academic_sources",
    "freshness_latest",
)


_ROLE_SOURCE_TYPES: dict[str, list[str]] = {
    "primary_source_hunter": ["official_primary", "technical_docs", "seed"],
    "independent_confirmation": ["web_page", "journalism", "peer_reviewed"],
    "contradiction_hunter": ["journalism", "peer_reviewed", "forum", "blog"],
    "historical_context": ["web_page", "knowledge", "journalism"],
    "quantitative_data": ["peer_reviewed", "official_primary", "technical_docs"],
    "technical_docs": ["technical_docs", "knowledge"],
    "academic_sources": ["peer_reviewed", "official_primary"],
    "freshness_latest": ["web_page", "journalism", "technical_docs"],
}

_ROLE_EXCLUSIONS: dict[str, list[str]] = {
    "primary_source_hunter": ["Do not rely solely on secondary summaries"],
    "independent_confirmation": ["Avoid sources in the same independence cluster as existing support"],
    "contradiction_hunter": ["Do not suppress conflicting accounts"],
    "historical_context": ["Do not overwrite newer dated facts with undated lore"],
    "quantitative_data": ["Reject unsourced numeric claims"],
    "technical_docs": ["Skip marketing landing pages"],
    "academic_sources": ["Prefer peer-reviewed or preprint venues over blogs"],
    "freshness_latest": ["Deprioritize undated or clearly stale pages"],
}

_GAP_ROLE_AFFINITY: dict[str, tuple[str, ...]] = {
    "NO_EVIDENCE": ("primary_source_hunter", "technical_docs", "academic_sources"),
    "INSUFFICIENT_EVIDENCE": ("independent_confirmation", "academic_sources"),
    "SINGLE_SOURCE": ("independent_confirmation", "primary_source_hunter"),
    "LOW_AUTHORITY": ("primary_source_hunter", "academic_sources"),
    "CONTRADICTION": ("contradiction_hunter", "independent_confirmation", "primary_source_hunter"),
    "OUTDATED": ("freshness_latest", "historical_context"),
    "MISSING_PRIMARY_SOURCE": ("primary_source_hunter", "technical_docs"),
    "MISSING_COUNTEREVIDENCE": ("contradiction_hunter",),
    "MISSING_TIME_CONTEXT": ("historical_context", "freshness_latest"),
    "MISSING_QUANTITATIVE_DATA": ("quantitative_data", "academic_sources"),
    "AMBIGUOUS_CLAIM": ("technical_docs", "academic_sources"),
    "CITATION_FAILURE": ("primary_source_hunter", "independent_confirmation"),
}


@dataclass
class ResearchAssignment:
    worker_id: str
    role: str
    objective: str
    target_questions: list[str]
    target_claim_ids: list[str]
    target_gap_ids: list[str]
    query_candidates: list[str]
    preferred_source_types: list[str]
    exclusions: list[str]
    max_queries: int
    max_sources: int
    success_criteria: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "role": self.role,
            "objective": self.objective,
            "target_questions": list(self.target_questions),
            "target_claim_ids": list(self.target_claim_ids),
            "target_gap_ids": list(self.target_gap_ids),
            "query_candidates": list(self.query_candidates),
            "preferred_source_types": list(self.preferred_source_types),
            "exclusions": list(self.exclusions),
            "max_queries": self.max_queries,
            "max_sources": self.max_sources,
            "success_criteria": list(self.success_criteria),
            "metadata": dict(self.metadata),
        }


def _role_objective(role: str) -> str:
    return {
        "primary_source_hunter": "Locate official or primary materials that ground unresolved claims",
        "independent_confirmation": "Find independent corroboration outside existing source clusters",
        "contradiction_hunter": "Surface counterevidence and reconcile apparent contradictions",
        "historical_context": "Establish timelines and historical framing for contested facts",
        "quantitative_data": "Gather measurable / numeric evidence with clear denominators",
        "technical_docs": "Retrieve specifications, APIs, and technical documentation",
        "academic_sources": "Prioritize scholarly and peer-reviewed material",
        "freshness_latest": "Capture the newest dated changes relevant to freshness requirements",
    }.get(role, f"Advance research under role {role}")


def _success_criteria(role: str, gaps: list[ResearchGap]) -> list[str]:
    base = [
        f"Produce evidence addressing assigned gaps ({len(gaps)} linked)",
        "All new citations must resolve in the evidence ledger",
    ]
    if role == "contradiction_hunter":
        base.append("Document both sides without auto-choosing a winner")
    if role == "independent_confirmation":
        base.append("New support must come from a distinct independence cluster")
    if role == "freshness_latest":
        base.append("Prefer sources with explicit recent dates")
    if role == "primary_source_hunter":
        base.append("At least one official_primary or technical_docs source when available")
    return base


def _select_roles(gaps: list[ResearchGap], worker_count: int, deepen_focus: str | None) -> list[str]:
    if worker_count <= 0:
        return []

    scores: dict[str, float] = {role: 0.0 for role in WORKER_ROLES}
    severity_w = {"critical": 4.0, "high": 3.0, "medium": 2.0, "low": 1.0}

    for gap in gaps:
        affinity = _GAP_ROLE_AFFINITY.get(gap.gap_type, ("primary_source_hunter",))
        weight = severity_w.get(gap.severity, 1.0) * float(gap.expected_information_gain)
        for idx, role in enumerate(affinity):
            scores[role] = scores.get(role, 0.0) + weight / float(idx + 1)

    if deepen_focus:
        focus = deepen_focus.lower()
        if "conflict" in focus or "contradict" in focus:
            scores["contradiction_hunter"] += 5.0
            scores["independent_confirmation"] += 2.0
        if "weak" in focus or "single" in focus:
            scores["independent_confirmation"] += 4.0
            scores["primary_source_hunter"] += 2.0
        if "fresh" in focus or "latest" in focus:
            scores["freshness_latest"] += 4.0
        if "primary" in focus:
            scores["primary_source_hunter"] += 4.0
        if "quant" in focus or "number" in focus:
            scores["quantitative_data"] += 4.0

    # Only keep roles that scored — do not spawn unused specialists.
    ranked = sorted(
        ((role, score) for role, score in scores.items() if score > 0),
        key=lambda item: item[1],
        reverse=True,
    )
    if not ranked:
        # Fallback when no gaps: still useful complementary pair.
        fallback = ["primary_source_hunter", "independent_confirmation"]
        return fallback[:worker_count]

    selected = [role for role, _score in ranked[:worker_count]]
    return selected


def plan_assignments(
    workers: list[ResearchWorker] | list[dict[str, Any]],
    gaps: list[ResearchGap],
    plan: ResearchPlan | None,
    *,
    deepen_focus: str | None = None,
) -> list[ResearchAssignment]:
    """Assign complementary roles based on top gaps.

    If 2 workers, pick the 2 most useful roles. Deepen focuses on unresolved
    gaps / conflicts / weak claims. Unused specialists are not spawned.
    """
    if not workers:
        return []

    # Normalize worker identities.
    worker_ids: list[str] = []
    for w in workers:
        if isinstance(w, dict):
            worker_ids.append(str(w.get("worker_id") or w.get("id") or f"worker_{len(worker_ids)}"))
        else:
            worker_ids.append(str(getattr(w, "worker_id", f"worker_{len(worker_ids)}")))

    roles = _select_roles(gaps, len(worker_ids), deepen_focus)
    budget = plan.budget if plan else None
    max_queries = max(1, (budget.search_queries if budget else 2) // max(1, len(roles)))
    max_sources = max(1, (budget.max_sources if budget else 4) // max(1, len(roles)))

    # Attach top gaps to roles by affinity.
    role_gaps: dict[str, list[ResearchGap]] = {r: [] for r in roles}
    for gap in gaps:
        affinity = _GAP_ROLE_AFFINITY.get(gap.gap_type, ("primary_source_hunter",))
        placed = False
        for role in affinity:
            if role in role_gaps:
                role_gaps[role].append(gap)
                placed = True
                break
        if not placed and roles:
            role_gaps[roles[0]].append(gap)

    plan_queries = list(plan.retrieval_queries) if plan else []
    assignments: list[ResearchAssignment] = []

    for idx, worker_id in enumerate(worker_ids):
        if idx >= len(roles):
            break
        role = roles[idx]
        linked = role_gaps.get(role) or []
        # When deepen_focus set, prefer unresolved / conflict / weak gaps.
        if deepen_focus:
            linked = sorted(
                linked,
                key=lambda g: (
                    1 if g.gap_type in {"CONTRADICTION", "SINGLE_SOURCE", "NO_EVIDENCE"} else 0,
                    g.expected_information_gain,
                ),
                reverse=True,
            )

        queries: list[str] = []
        for gap in linked:
            for q in gap.suggested_queries:
                if q not in queries:
                    queries.append(q)
        # Fall back to plan queries with role flavor.
        if not queries:
            flavor = role.replace("_", " ")
            for pq in plan_queries:
                queries.append(f"{pq} {flavor}")
            if plan and plan.interpreted_question:
                queries.insert(0, f"{plan.interpreted_question} {flavor}")

        questions = [g.target_question for g in linked if g.target_question]
        claim_ids = [g.target_claim_id for g in linked if g.target_claim_id]
        gap_ids = [g.gap_id for g in linked]

        assignments.append(
            ResearchAssignment(
                worker_id=worker_id,
                role=role,
                objective=_role_objective(role),
                target_questions=list(dict.fromkeys(questions)),
                target_claim_ids=list(dict.fromkeys(claim_ids)),
                target_gap_ids=list(dict.fromkeys(gap_ids)),
                query_candidates=queries[: max(1, max_queries * 3)],
                preferred_source_types=list(_ROLE_SOURCE_TYPES.get(role, ["web_page", "knowledge"])),
                exclusions=list(_ROLE_EXCLUSIONS.get(role, [])),
                max_queries=max_queries,
                max_sources=max_sources,
                success_criteria=_success_criteria(role, linked),
                metadata={
                    "deepen_focus": deepen_focus,
                    "gap_types": sorted({g.gap_type for g in linked}),
                },
            )
        )

    return assignments
