"""Deterministic research quality scorecard — not a truth probability."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from .citation_audit import CitationAuditReport, CitationAuditStatus, audit_report
from .gaps import GapAnalyzer, ResearchGap
from .source_quality import (
    SourceAssessment,
    assess_source,
    cluster_dependent_sources,
    independent_support_count,
)
from .store import ResearchStore
from .types import ClaimStatus, ResearchProject


@dataclass
class DimensionScore:
    name: str
    score: float
    numerator: float
    denominator: float
    notes: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": self.score,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "notes": self.notes,
        }


@dataclass
class ResearchQualityScorecard:
    project_id: str
    dimensions: dict[str, DimensionScore] = field(default_factory=dict)
    overall: float = 0.0
    gaps_summary: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "dimensions": {k: v.public_dict() for k, v in self.dimensions.items()},
            "overall": self.overall,
            "gaps_summary": dict(self.gaps_summary),
            "metadata": dict(self.metadata),
            "truth": {
                "scorecard_is_not_probability_answer_is_true": True,
                "dimensions_measure_process_quality_not_ontological_truth": True,
                "high_score_does_not_mean_correct": True,
            },
        }


def _ratio(num: float, den: float) -> float:
    if den <= 0:
        return 0.0
    return max(0.0, min(1.0, float(num) / float(den)))


def _unique_domains(sources: list[Any]) -> list[str]:
    domains: list[str] = []
    for src in sources:
        uri = getattr(src, "canonical_uri", None) or getattr(src, "original_uri", None) or ""
        host = urlparse(uri).hostname
        if host:
            domains.append(host.lower().removeprefix("www."))
        elif uri.startswith("knowledge://"):
            domains.append("local.knowledge")
        elif uri.startswith("seed://"):
            domains.append("local.seed")
    return sorted(set(domains))


def build_quality_scorecard(
    store: ResearchStore,
    project: ResearchProject,
    *,
    report_markdown: str | None = None,
    gaps: list[ResearchGap] | None = None,
    citation_report: CitationAuditReport | None = None,
) -> ResearchQualityScorecard:
    """Compute deterministic process-quality dimensions (0–1) with denominators."""
    project_id = project.project_id
    plan = project.plan
    coverage = project.coverage
    claims = store.list_claims(project_id)
    conflicts = store.list_conflicts(project_id)
    sources = store.list_sources(project_id)
    evidence = store.list_evidence(project_id)

    if gaps is None:
        gaps = GapAnalyzer().analyze(store, project)

    topic_tokens = []
    if plan and plan.interpreted_question:
        topic_tokens = [t for t in plan.interpreted_question.lower().split() if len(t) > 2]
    elif project.topic:
        topic_tokens = [t for t in project.topic.lower().split() if len(t) > 2]

    assessments: list[SourceAssessment] = [
        assess_source(src, topic_tokens=topic_tokens) for src in sources
    ]
    clusters = cluster_dependent_sources(sources)

    # --- coverage ---
    planned = list(coverage.planned_questions) if coverage else (list(plan.subquestions) if plan else [project.topic])
    answered = list(coverage.answered_questions) if coverage else []
    coverage_num = float(len(answered))
    coverage_den = float(max(1, len(planned)))
    coverage_score = _ratio(coverage_num, coverage_den)
    coverage_dim = DimensionScore(
        name="coverage",
        score=coverage_score,
        numerator=coverage_num,
        denominator=coverage_den,
        notes=(
            "answered_questions / planned_questions. "
            "claim_coverage = claims with ≥1 supporting evidence / total claims "
            f"({sum(1 for c in claims if c.supporting_evidence_ids)}/{len(claims)})."
        ),
    )

    # --- citation_validity ---
    if citation_report is None and report_markdown:
        citation_report = audit_report(store, project, report_markdown)
    if citation_report and citation_report.items:
        ok = sum(
            1
            for i in citation_report.items
            if i.status
            in {
                CitationAuditStatus.SUPPORTED,
                CitationAuditStatus.PARTIALLY_SUPPORTED,
                CitationAuditStatus.INTERPRETATION,
            }
        )
        cit_num = float(ok)
        cit_den = float(len(citation_report.items))
        cit_notes = (
            "supported+partial+interpretation items / audited sentences; "
            f"critical_unsupported={len(citation_report.critical_unsupported)}"
        )
    else:
        # Fall back to evidence that can resolve at all.
        cit_num = float(len(evidence))
        cit_den = float(max(1, len(evidence)))
        cit_notes = "no report markdown audited; fallback uses evidence presence only"
        if not evidence:
            cit_num = 0.0
    citation_dim = DimensionScore(
        name="citation_validity",
        score=_ratio(cit_num, cit_den),
        numerator=cit_num,
        denominator=cit_den,
        notes=cit_notes,
    )

    # --- source_diversity ---
    domains = _unique_domains(sources)
    diversity_num = float(len(domains))
    diversity_den = 3.0  # target: at least 3 distinct domains
    diversity_dim = DimensionScore(
        name="source_diversity",
        score=_ratio(diversity_num, diversity_den),
        numerator=diversity_num,
        denominator=diversity_den,
        notes=f"unique_domains={len(domains)} among source_count={len(sources)} (target≥3)",
    )

    # --- primary_source_presence ---
    primary = [a for a in assessments if a.primary_or_secondary == "primary" or a.source_class in {
        "official_primary",
        "peer_reviewed",
        "technical_docs",
    }]
    primary_num = float(len(primary))
    primary_den = float(max(1, min(3, len(sources) or 1)))
    primary_dim = DimensionScore(
        name="primary_source_presence",
        score=_ratio(primary_num, primary_den),
        numerator=primary_num,
        denominator=primary_den,
        notes="primary-class assessments / min(3, sources); contextual class not TLD alone",
    )

    # --- freshness ---
    if assessments:
        freshness_num = sum(a.freshness for a in assessments)
        freshness_den = float(len(assessments))
        freshness_notes = "mean SourceAssessment.freshness across sources"
    else:
        freshness_num = 0.0
        freshness_den = 1.0
        freshness_notes = "no sources to score freshness"
    freshness_dim = DimensionScore(
        name="freshness",
        score=_ratio(freshness_num, freshness_den),
        numerator=freshness_num,
        denominator=freshness_den,
        notes=freshness_notes,
    )

    # --- independent_corroboration ---
    if claims:
        ratios: list[float] = []
        for claim in claims:
            support_source_ids: list[str] = []
            for eid in claim.supporting_evidence_ids:
                ev = store.get_evidence(eid)
                if ev is not None:
                    support_source_ids.append(ev.source_id)
            indep = independent_support_count(support_source_ids, clusters)
            # Target: at least 2 independent clusters for strong corroboration.
            ratios.append(_ratio(float(indep), 2.0))
        indep_num = sum(ratios)
        indep_den = float(len(ratios))
        indep_notes = "mean(min(independent_clusters/2, 1)) across claims"
    else:
        indep_num = 0.0
        indep_den = 1.0
        indep_notes = "no claims; independent corroboration undefined"
    indep_dim = DimensionScore(
        name="independent_corroboration",
        score=_ratio(indep_num, indep_den),
        numerator=indep_num,
        denominator=indep_den,
        notes=indep_notes,
    )

    # --- conflict_handling ---
    disputed = [c for c in claims if c.status == ClaimStatus.DISPUTED]
    if disputed:
        with_record = 0
        conflict_claim_ids = {c.claim_id for c in conflicts if c.claim_id}
        for claim in disputed:
            if claim.claim_id in conflict_claim_ids and claim.contradicting_evidence_ids:
                with_record += 1
        conflict_num = float(with_record)
        conflict_den = float(len(disputed))
        conflict_notes = "disputed claims with preserved conflict records / disputed claims"
    elif conflicts:
        conflict_num = float(len(conflicts))
        conflict_den = float(len(conflicts))
        conflict_notes = "conflicts present and retained (preserve_both)"
    else:
        conflict_num = 1.0
        conflict_den = 1.0
        conflict_notes = "no disputes detected; vacuously handled"
    conflict_dim = DimensionScore(
        name="conflict_handling",
        score=_ratio(conflict_num, conflict_den),
        numerator=conflict_num,
        denominator=conflict_den,
        notes=conflict_notes,
    )

    # --- unresolved_critical_gaps ---
    # Score = resolved_share among critical/high: 1 - (open / max(open, 1)) when any remain.
    critical_high = [g for g in gaps if g.severity in {"critical", "high"}]
    if not critical_high:
        gap_num, gap_den, gap_score = 1.0, 1.0, 1.0
        gap_notes = "no critical/high gaps remaining"
    else:
        gap_den = float(len(critical_high))
        gap_num = 0.0  # all listed gaps are still unresolved
        gap_score = _ratio(gap_num, gap_den)
        gap_notes = (
            f"{len(critical_high)} unresolved critical/high gaps; "
            "numerator is resolved count (0 until gaps close)"
        )
    gaps_dim = DimensionScore(
        name="unresolved_critical_gaps",
        score=gap_score,
        numerator=gap_num,
        denominator=gap_den,
        notes=gap_notes,
    )

    dimensions = {
        "coverage": coverage_dim,
        "citation_validity": citation_dim,
        "source_diversity": diversity_dim,
        "primary_source_presence": primary_dim,
        "freshness": freshness_dim,
        "independent_corroboration": indep_dim,
        "conflict_handling": conflict_dim,
        "unresolved_critical_gaps": gaps_dim,
    }

    weights = {
        "coverage": 0.15,
        "citation_validity": 0.18,
        "source_diversity": 0.12,
        "primary_source_presence": 0.12,
        "freshness": 0.08,
        "independent_corroboration": 0.15,
        "conflict_handling": 0.10,
        "unresolved_critical_gaps": 0.10,
    }
    overall = sum(dimensions[k].score * weights[k] for k in weights)

    return ResearchQualityScorecard(
        project_id=project_id,
        dimensions=dimensions,
        overall=round(overall, 4),
        gaps_summary={
            "total_gaps": len(gaps),
            "critical_high": len(critical_high),
            "by_type": _count_by(gaps, "gap_type"),
            "by_severity": _count_by(gaps, "severity"),
        },
        metadata={
            "source_count": len(sources),
            "claim_count": len(claims),
            "evidence_count": len(evidence),
            "conflict_count": len(conflicts),
            "unique_domains": domains,
            "primary_source_count": len(primary),
        },
    )


def _count_by(gaps: list[ResearchGap], attr: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for gap in gaps:
        key = str(getattr(gap, attr))
        out[key] = out.get(key, 0) + 1
    return out
