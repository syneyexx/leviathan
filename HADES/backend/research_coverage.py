"""Honest research coverage summary from persisted project metrics."""

from __future__ import annotations

from typing import Any

from claim_register import honest_research_metric_kind

DEPTH_SOURCE_TARGETS = {"quick": 4, "standard": 8, "deep": 14, "expert": 24}


def summarize_research_coverage(project: dict[str, Any]) -> dict[str, Any]:
    """Derive coverage gaps from stored metrics — never claim expert completeness."""
    metrics = project.get("metrics") or {}
    if not isinstance(metrics, dict):
        metrics = {}

    depth = str(project.get("depth") or "standard")
    source_target = DEPTH_SOURCE_TARGETS.get(depth, 14)
    project_status = str(project.get("status") or "")
    metric_status = str(metrics.get("status") or "")
    metric_kind = honest_research_metric_kind(metrics.get("metric_kind"))

    coverage_score = int(metrics.get("coverage_score") or metrics.get("mastery") or 0)
    mastery_target = int(metrics.get("mastery_target") or 90)
    source_count = int(metrics.get("source_count") or 0)
    evidence_chunks = int(metrics.get("evidence_chunks") or 0)
    domain_diversity = int(metrics.get("domain_diversity") or 0)
    contradictions = [str(item) for item in (metrics.get("contradictions") or []) if str(item).strip()]

    gaps: list[str] = []
    if source_count < source_target:
        gaps.append(f"Brondekking: {source_count}/{source_target} unieke bronnen voor {depth}-onderzoek.")
    if coverage_score < mastery_target:
        gaps.append(
            f"Dekkingsscore {coverage_score}% onder drempel {mastery_target}% "
            f"({metric_kind})."
        )
    if evidence_chunks < max(3, source_target // 2):
        gaps.append(f"Weinig evidence-chunks ({evidence_chunks}); synthese kan dun zijn.")
    if depth in {"deep", "expert"} and domain_diversity < 2 and project.get("allow_web"):
        gaps.append(f"Lage webdomein-diversiteit ({domain_diversity}); meer onafhankelijke bronnen nodig.")
    if contradictions:
        gaps.append(f"{len(contradictions)} zichtbare tegenstrijdigheid(en) in evidence — niet expert-compleet.")
    if project_status == "needs_more_evidence":
        gaps.append("Projectstatus: needs_more_evidence — expert-drempel niet bereikt.")
    elif metric_status == "needs-more-evidence":
        gaps.append("Metriekstatus: needs-more-evidence — meer bewijs vereist.")
    elif depth == "expert" and project_status == "completed" and coverage_score < mastery_target:
        gaps.append("Expert-diepte maar dekkingsmetriek onder drempel — geen bewezen mastery.")

    complete = not gaps and project_status == "completed" and coverage_score >= mastery_target
    incomplete = bool(gaps) or project_status in {"needs_more_evidence", "failed", "cancelled", "running", "queued"}

    return {
        "ok": True,
        "project_id": project.get("id"),
        "depth": depth,
        "complete": complete,
        "incomplete": incomplete,
        "needs_more_evidence": project_status == "needs_more_evidence" or metric_status == "needs-more-evidence",
        "coverage_score": coverage_score,
        "mastery_target": mastery_target,
        "source_count": source_count,
        "source_target": source_target,
        "evidence_chunks": evidence_chunks,
        "domain_diversity": domain_diversity,
        "metric_kind": metric_kind,
        "metric_note": metrics.get("metric_note")
        or "Geen aangetoonde expertise; alleen brondekking/diversiteit.",
        "gaps": gaps,
        "contradictions": contradictions,
        "status": project_status,
        "metric_status": metric_status or None,
        "label": "expert-threshold" if complete and depth == "expert" else "incomplete" if gaps else "advanced",
    }
