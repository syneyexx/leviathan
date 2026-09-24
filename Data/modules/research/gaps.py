"""Research gap analysis — what is still missing and whether to stop."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from .store import ResearchStore
from .types import (
    ClaimStatus,
    CoverageSummary,
    ResearchClaim,
    ResearchPlan,
    ResearchProject,
)


_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


@dataclass
class ResearchGap:
    gap_id: str
    gap_type: str
    severity: str
    target_question: str | None
    target_claim_id: str | None
    expected_information_gain: float
    suggested_queries: list[str]
    suggested_source_types: list[str]
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "gap_type": self.gap_type,
            "severity": self.severity,
            "target_question": self.target_question,
            "target_claim_id": self.target_claim_id,
            "expected_information_gain": self.expected_information_gain,
            "suggested_queries": list(self.suggested_queries),
            "suggested_source_types": list(self.suggested_source_types),
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


def _gap_id(*parts: str) -> str:
    raw = "|".join(p or "" for p in parts)
    return "gap_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _query_variants(base: str, *, focus: str | None = None) -> list[str]:
    text = (base or "").strip().rstrip("?")
    if not text:
        return []
    out = [text]
    if focus:
        out.append(f"{text} {focus}")
    out.append(f"{text} primary source")
    out.append(f"{text} evidence")
    # Deduplicate preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for q in out:
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(q)
    return deduped


def _primary_types_present(sources: list[Any], preferred: list[str]) -> set[str]:
    present: set[str] = set()
    for src in sources:
        st = getattr(src, "source_type", None)
        value = st.value if hasattr(st, "value") else str(st or "")
        if value:
            present.add(value)
        meta = getattr(src, "metadata", None) or {}
        if isinstance(meta, dict):
            cls = meta.get("source_class") or meta.get("source_type_hint")
            if cls:
                present.add(str(cls))
        uri = (getattr(src, "canonical_uri", None) or getattr(src, "original_uri", None) or "").lower()
        if any(tok in uri for tok in (".gov", ".edu", "arxiv.org", "doi.org", "pubmed")):
            present.add("official_primary")
            present.add("peer_reviewed")
    preferred_set = {p.lower() for p in preferred}
    return preferred_set & {p.lower() for p in present}


class GapAnalyzer:
    """Build ResearchGap objects from store state (claims, evidence, conflicts, coverage, sources, plan)."""

    def analyze(self, store: ResearchStore, project: ResearchProject) -> list[ResearchGap]:
        project_id = project.project_id
        plan = project.plan
        claims = store.list_claims(project_id)
        conflicts = store.list_conflicts(project_id)
        sources = store.list_sources(project_id)
        evidence = store.list_evidence(project_id)
        coverage = project.coverage

        gaps: list[ResearchGap] = []

        planned = list(plan.subquestions) if plan else [project.topic]
        unresolved = list(coverage.unresolved_questions) if coverage else []
        if not unresolved and coverage is None:
            # Derive unanswered subquestions via keyword overlap when coverage not yet built.
            for q in planned:
                tokens = {t.lower() for t in q.split() if len(t) > 3}
                hit = False
                for ev in evidence:
                    span_tokens = {t.lower() for t in ev.span_text.split() if len(t) > 3}
                    if tokens & span_tokens:
                        hit = True
                        break
                if not hit:
                    unresolved.append(q)

        for q in unresolved:
            gaps.append(
                ResearchGap(
                    gap_id=_gap_id("no_evidence", q),
                    gap_type="NO_EVIDENCE",
                    severity="high",
                    target_question=q,
                    target_claim_id=None,
                    expected_information_gain=0.85,
                    suggested_queries=_query_variants(q),
                    suggested_source_types=["web_page", "knowledge", "official_primary"],
                    reason=f"Subquestion unanswered: {q}",
                    metadata={"kind": "unanswered_subquestion"},
                )
            )

        for claim in claims:
            gaps.extend(self._gaps_for_claim(claim, plan))

        conflict_claim_ids = {c.claim_id for c in conflicts if c.claim_id}
        for conflict in conflicts:
            if conflict.claim_id and any(
                g.target_claim_id == conflict.claim_id and g.gap_type == "CONTRADICTION" for g in gaps
            ):
                continue
            claim_prop = conflict.summary
            gaps.append(
                ResearchGap(
                    gap_id=_gap_id("conflict", conflict.conflict_id),
                    gap_type="CONTRADICTION",
                    severity="high",
                    target_question=conflict.unresolved_questions[0] if conflict.unresolved_questions else None,
                    target_claim_id=conflict.claim_id,
                    expected_information_gain=0.9,
                    suggested_queries=_query_variants(
                        claim_prop,
                        focus="reconciliation primary source",
                    ),
                    suggested_source_types=["official_primary", "peer_reviewed", "technical_docs"],
                    reason=f"Unresolved conflict: {conflict.summary}",
                    metadata={
                        "conflict_id": conflict.conflict_id,
                        "analysis": dict(conflict.analysis),
                    },
                )
            )

        # Missing preferred primary types when plan asks for them.
        targets = (plan.evidence_coverage_targets if plan else {}) or {}
        if targets.get("prefer_primary_sources"):
            preferred_primary = [
                "official_primary",
                "peer_reviewed",
                "technical_docs",
                "primary",
            ]
            present = _primary_types_present(sources, preferred_primary)
            if not present and sources:
                topic = (plan.interpreted_question if plan else None) or project.topic
                gaps.append(
                    ResearchGap(
                        gap_id=_gap_id("missing_primary", project_id, topic),
                        gap_type="MISSING_PRIMARY_SOURCE",
                        severity="medium",
                        target_question=topic,
                        target_claim_id=None,
                        expected_information_gain=0.7,
                        suggested_queries=_query_variants(topic, focus="official documentation site:gov OR site:edu"),
                        suggested_source_types=preferred_primary,
                        reason="Plan prefers primary sources but none detected among ingested sources",
                        metadata={"prefer_primary_sources": True},
                    )
                )
            elif not sources:
                topic = (plan.interpreted_question if plan else None) or project.topic
                gaps.append(
                    ResearchGap(
                        gap_id=_gap_id("missing_primary_empty", project_id),
                        gap_type="MISSING_PRIMARY_SOURCE",
                        severity="high",
                        target_question=topic,
                        target_claim_id=None,
                        expected_information_gain=0.95,
                        suggested_queries=_query_variants(topic, focus="primary source"),
                        suggested_source_types=preferred_primary,
                        reason="No sources ingested; primary sources still required by plan targets",
                        metadata={"prefer_primary_sources": True, "source_count": 0},
                    )
                )

        # Ambiguous / weakly specified claims.
        for claim in claims:
            if claim.claim_id in conflict_claim_ids:
                continue
            prop = claim.proposition or ""
            if re.search(r"\b(maybe|possibly|unclear|ambiguous|various|some say)\b", prop, re.I):
                gaps.append(
                    ResearchGap(
                        gap_id=_gap_id("ambiguous", claim.claim_id),
                        gap_type="AMBIGUOUS_CLAIM",
                        severity="low",
                        target_question=None,
                        target_claim_id=claim.claim_id,
                        expected_information_gain=0.4,
                        suggested_queries=_query_variants(prop, focus="definition clarification"),
                        suggested_source_types=["technical_docs", "peer_reviewed"],
                        reason="Claim wording appears ambiguous",
                        metadata={},
                    )
                )

        return self._prioritize(gaps)

    def _gaps_for_claim(self, claim: ResearchClaim, plan: ResearchPlan | None) -> list[ResearchGap]:
        gaps: list[ResearchGap] = []
        support = list(claim.supporting_evidence_ids or [])
        contradict = list(claim.contradicting_evidence_ids or [])
        diversity = int(claim.source_diversity or 0)
        prop = claim.proposition

        if claim.status in {ClaimStatus.UNSUPPORTED, ClaimStatus.UNRESOLVED} or (
            not support and claim.status != ClaimStatus.DISPUTED
        ):
            gaps.append(
                ResearchGap(
                    gap_id=_gap_id("no_ev_claim", claim.claim_id),
                    gap_type="NO_EVIDENCE",
                    severity="high",
                    target_question=None,
                    target_claim_id=claim.claim_id,
                    expected_information_gain=0.88,
                    suggested_queries=_query_variants(prop),
                    suggested_source_types=["web_page", "knowledge", "official_primary"],
                    reason=f"Claim has no supporting evidence: {prop[:160]}",
                    metadata={"status": claim.status.value},
                )
            )
        elif len(support) == 1 or diversity <= 1 or claim.status == ClaimStatus.WEAKLY_SUPPORTED:
            gaps.append(
                ResearchGap(
                    gap_id=_gap_id("single", claim.claim_id),
                    gap_type="SINGLE_SOURCE",
                    severity="medium",
                    target_question=None,
                    target_claim_id=claim.claim_id,
                    expected_information_gain=0.65,
                    suggested_queries=_query_variants(prop, focus="independent confirmation"),
                    suggested_source_types=["web_page", "peer_reviewed", "official_primary"],
                    reason=f"Claim relies on a single source or weak support (diversity={diversity})",
                    metadata={
                        "status": claim.status.value,
                        "support_count": len(support),
                        "source_diversity": diversity,
                    },
                )
            )
        elif len(support) < 2 and claim.status == ClaimStatus.SUPPORTED:
            gaps.append(
                ResearchGap(
                    gap_id=_gap_id("insufficient", claim.claim_id),
                    gap_type="INSUFFICIENT_EVIDENCE",
                    severity="medium",
                    target_question=None,
                    target_claim_id=claim.claim_id,
                    expected_information_gain=0.55,
                    suggested_queries=_query_variants(prop, focus="additional evidence"),
                    suggested_source_types=["web_page", "knowledge"],
                    reason="Claim marked supported but corroboration is thin",
                    metadata={"support_count": len(support)},
                )
            )

        if claim.status == ClaimStatus.DISPUTED or contradict:
            gaps.append(
                ResearchGap(
                    gap_id=_gap_id("contradiction", claim.claim_id),
                    gap_type="CONTRADICTION",
                    severity="high",
                    target_question=None,
                    target_claim_id=claim.claim_id,
                    expected_information_gain=0.92,
                    suggested_queries=_query_variants(prop, focus="counterevidence reconciliation"),
                    suggested_source_types=["official_primary", "peer_reviewed"],
                    reason=f"Disputed claim needs reconciliation: {prop[:160]}",
                    metadata={
                        "status": claim.status.value,
                        "contradicting_count": len(contradict),
                    },
                )
            )

        # Counterevidence gap when only one side exists for a contested topic.
        if support and not contradict and plan and "contradict" in " ".join(plan.subquestions).lower():
            gaps.append(
                ResearchGap(
                    gap_id=_gap_id("counter", claim.claim_id),
                    gap_type="MISSING_COUNTEREVIDENCE",
                    severity="low",
                    target_question=None,
                    target_claim_id=claim.claim_id,
                    expected_information_gain=0.45,
                    suggested_queries=_query_variants(prop, focus="criticism limitations"),
                    suggested_source_types=["journalism", "peer_reviewed", "blog"],
                    reason="Plan seeks alternative accounts; no contradicting evidence found yet",
                    metadata={},
                )
            )

        return gaps

    @staticmethod
    def _prioritize(gaps: list[ResearchGap]) -> list[ResearchGap]:
        # Deduplicate by gap_id keeping highest priority.
        by_id: dict[str, ResearchGap] = {}
        for gap in gaps:
            prev = by_id.get(gap.gap_id)
            if prev is None:
                by_id[gap.gap_id] = gap
                continue
            prev_score = _SEVERITY_RANK.get(prev.severity, 0) * prev.expected_information_gain
            new_score = _SEVERITY_RANK.get(gap.severity, 0) * gap.expected_information_gain
            if new_score > prev_score:
                by_id[gap.gap_id] = gap

        ranked = sorted(
            by_id.values(),
            key=lambda g: (
                _SEVERITY_RANK.get(g.severity, 0) * g.expected_information_gain,
                _SEVERITY_RANK.get(g.severity, 0),
                g.expected_information_gain,
            ),
            reverse=True,
        )
        return ranked


def should_stop(
    gaps: list[ResearchGap],
    coverage: CoverageSummary | None,
    plan: ResearchPlan | None,
    *,
    waves_without_gain: int,
    max_waves: int,
    budget_exhausted: bool,
) -> tuple[bool, str]:
    """Decide whether another research wave is warranted.

    Hard budget is a ceiling — do not stop only because rounds finished if
    critical high-gain gaps remain AND budget still allows another wave.
    """
    if budget_exhausted:
        return True, "budget_exhausted"

    if waves_without_gain >= 2:
        return True, "waves_without_gain>=2"

    critical_high = [
        g
        for g in gaps
        if g.severity in {"critical", "high"} and g.expected_information_gain >= 0.5
    ]
    high_gain = [g for g in gaps if g.expected_information_gain >= 0.55]
    max_eig = max((g.expected_information_gain for g in gaps), default=0.0)

    rounds_done = coverage.rounds_completed if coverage else 0
    # Plan rounds inform the ceiling but do not alone force a stop when critical
    # high-gain gaps remain and the caller still has budget for another wave.
    plan_ceiling = max(max_waves, int(plan.rounds) if plan else max_waves)

    if not critical_high and max_eig < 0.35:
        return True, "low_expected_information_gain"

    if not critical_high and not high_gain:
        return True, "no_critical_or_high_gaps"

    if rounds_done >= plan_ceiling and critical_high:
        return False, "critical_high_gain_gaps_remain_under_budget"

    if rounds_done >= plan_ceiling and not critical_high:
        return True, "max_waves_reached"

    return False, "continue"


def select_next_queries(
    gaps: list[ResearchGap],
    existing_queries: list[str],
    *,
    limit: int,
) -> list[str]:
    """Complementary queries drawn from top gaps, skipping near-duplicates."""
    existing_norm = {q.strip().lower() for q in existing_queries if q and q.strip()}
    selected: list[str] = []
    selected_norm: set[str] = set()

    ranked = sorted(
        gaps,
        key=lambda g: _SEVERITY_RANK.get(g.severity, 0) * g.expected_information_gain,
        reverse=True,
    )
    for gap in ranked:
        for query in gap.suggested_queries:
            q = query.strip()
            if not q:
                continue
            key = q.lower()
            if key in existing_norm or key in selected_norm:
                continue
            # Skip near-duplicates (shared prefix / containment).
            if any(key in e or e in key for e in selected_norm if len(e) > 12):
                continue
            selected.append(q)
            selected_norm.add(key)
            if len(selected) >= max(0, limit):
                return selected
    return selected
