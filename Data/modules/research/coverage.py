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

    # claim_coverage: claims with ≥1 supporting evidence / total claims
    claims_with_support = sum(1 for c in claims if c.supporting_evidence_ids)
    if claims:
        claim_coverage = claims_with_support / float(len(claims))
        notes.append(
            f"claim_coverage={claim_coverage:.2f} "
            f"({claims_with_support}/{len(claims)} claims with ≥1 supporting evidence)"
        )
    else:
        notes.append("claim_coverage=n/a (no claims yet)")

    # Optional enrichment via gaps / source quality (best-effort; keep coverage build resilient).
    critical_gaps_count = 0
    independent_support_ratio: float | None = None
    primary_source_count = 0
    try:
        from .gaps import GapAnalyzer
        from .source_quality import (
            assess_source,
            cluster_dependent_sources,
            independent_support_count,
        )

        # Temporarily attach this partial coverage so gap analysis can use unresolved lists.
        partial = CoverageSummary(
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
            notes=list(notes),
        )
        project_for_gaps = project
        # Avoid mutating caller's project.coverage permanently here; use a shallow swap.
        prev_coverage = project.coverage
        project.coverage = partial
        try:
            gaps = GapAnalyzer().analyze(store, project_for_gaps)
        finally:
            project.coverage = prev_coverage
        critical_gaps_count = sum(1 for g in gaps if g.severity in {"critical", "high"})
        if critical_gaps_count:
            notes.append(f"critical_gaps_count={critical_gaps_count}")

        topic_tokens = [t for t in (plan.interpreted_question if plan else project.topic).lower().split() if len(t) > 2]
        assessments = [assess_source(src, topic_tokens=topic_tokens) for src in sources]
        primary_source_count = sum(
            1
            for a in assessments
            if a.primary_or_secondary == "primary"
            or a.source_class in {"official_primary", "peer_reviewed", "technical_docs"}
        )

        clusters = cluster_dependent_sources(sources)
        if claims:
            ratios: list[float] = []
            for claim in claims:
                support_source_ids: list[str] = []
                for eid in claim.supporting_evidence_ids:
                    ev = store.get_evidence(eid)
                    if ev is not None:
                        support_source_ids.append(ev.source_id)
                indep = independent_support_count(support_source_ids, clusters)
                ratios.append(min(1.0, indep / 2.0) if indep else 0.0)
            independent_support_ratio = sum(ratios) / float(len(ratios)) if ratios else None
            if independent_support_ratio is not None:
                notes.append(f"independent_support_ratio={independent_support_ratio:.2f}")
        notes.append(f"primary_source_count={primary_source_count}")
    except Exception as exc:  # pragma: no cover - defensive enrichment
        notes.append(f"coverage enrichment skipped: {exc}")

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
        critical_gaps_count=critical_gaps_count,
        independent_support_ratio=independent_support_ratio,
        primary_source_count=primary_source_count,
    )
