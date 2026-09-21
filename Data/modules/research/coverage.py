"""Honest research coverage summary — no magical truth scores."""

from __future__ import annotations

from urllib.parse import urlparse

from .store import ResearchStore
from .types import ClaimStatus, CoverageSummary, ResearchPlan, ResearchProject


def build_coverage(
    store: ResearchStore,
    project: ResearchProject,
    *,
    web_status: str,
    rounds_completed: int | None = None,
) -> CoverageSummary:
    plan: ResearchPlan | None = project.plan
    planned = list(plan.subquestions) if plan else [project.topic]
    claims = store.list_claims(project.project_id)
    conflicts = store.list_conflicts(project.project_id)
    evidence = store.list_evidence(project.project_id)
    sources = store.list_sources(project.project_id)

    supported = sum(1 for c in claims if c.status == ClaimStatus.SUPPORTED)
    weakly = sum(1 for c in claims if c.status == ClaimStatus.WEAKLY_SUPPORTED)
    disputed = sum(1 for c in claims if c.status == ClaimStatus.DISPUTED)
    unsupported = sum(
        1 for c in claims if c.status in {ClaimStatus.UNSUPPORTED, ClaimStatus.UNRESOLVED}
    )

    answered: list[str] = []
    unresolved: list[str] = []
    for q in planned:
        # A planned question is "answered" only if we have any evidence at all related by keyword overlap.
        tokens = {t.lower() for t in q.split() if len(t) > 3}
        hit = False
        for ev in evidence:
            span_tokens = {t.lower() for t in ev.span_text.split() if len(t) > 3}
            if tokens & span_tokens:
                hit = True
                break
        if hit:
            answered.append(q)
        else:
            unresolved.append(q)

    for conflict in conflicts:
        unresolved.extend(conflict.unresolved_questions)

    domains: list[str] = []
    for src in sources:
        uri = src.canonical_uri or src.original_uri or ""
        host = urlparse(uri).hostname
        if host:
            domains.append(host.lower())
        elif uri.startswith("knowledge://"):
            domains.append("local.knowledge")
        elif uri.startswith("seed://"):
            domains.append("local.seed")

    unique_domains = sorted(set(domains))
    notes: list[str] = []
    if web_status not in {"not_requested", "ok", "not_applicable"}:
        notes.append(f"Web research unavailable: {web_status}")
    if disputed:
        notes.append(f"{disputed} disputed claim(s) preserved with conflict records")
    if not evidence:
        notes.append("No evidence collected yet")

    return CoverageSummary(
        planned_questions=planned,
        answered_questions=list(dict.fromkeys(answered)),
        unresolved_questions=list(dict.fromkeys(unresolved)),
        source_count=len(sources),
        unique_domains=unique_domains,
        claims_supported=supported + weakly,
        claims_with_conflicts=disputed,
        claims_unsupported=unsupported,
        rounds_completed=rounds_completed if rounds_completed is not None else project.current_round,
        web_status=web_status,
        notes=notes,
    )
