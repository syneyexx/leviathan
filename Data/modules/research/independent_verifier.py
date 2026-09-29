"""Independent claim verifier — separate from the claim authoring path (Wave 10–11).

Does not reuse authoring model judgments as proof. Deterministic entailment +
source-independence checks only. Cross-model verification remains OPTIONAL and
must be labelled honestly when unavailable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .claim_relations import ClaimRelation, normalize_claim_relation, relation_from_entailment_status
from .graph import citation_entailment_check
from .source_quality import cluster_dependent_sources, independent_support_count
from .store import ResearchStore


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class IndependentEdgeVerdict:
    claim_id: str
    evidence_id: str
    relation: str
    entailment_status: str
    overlap_ratio: float
    independent_cluster: bool
    detail: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "evidence_id": self.evidence_id,
            "relation": normalize_claim_relation(self.relation).value,
            "entailment_status": self.entailment_status,
            "overlap_ratio": self.overlap_ratio,
            "independent_cluster": self.independent_cluster,
            "detail": self.detail,
        }


@dataclass
class IndependentVerificationReport:
    report_id: str
    project_id: str
    created_at: str
    verdicts: list[IndependentEdgeVerdict] = field(default_factory=list)
    supports: int = 0
    contradicts: int = 0
    qualifies: int = 0
    background: int = 0
    insufficient: int = 0
    independent_support_clusters: int = 0
    cross_model_status: str = "UNAVAILABLE"
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "project_id": self.project_id,
            "created_at": self.created_at,
            "verdicts": [v.public_dict() for v in self.verdicts],
            "counts": {
                ClaimRelation.SUPPORTS.value: self.supports,
                ClaimRelation.CONTRADICTS.value: self.contradicts,
                ClaimRelation.QUALIFIES.value: self.qualifies,
                ClaimRelation.BACKGROUND.value: self.background,
                ClaimRelation.INSUFFICIENT.value: self.insufficient,
            },
            "independent_support_clusters": self.independent_support_clusters,
            "cross_model_status": self.cross_model_status,
            "metadata": dict(self.metadata),
            "truth": {
                "independent_of_authoring_path": True,
                "deterministic_entailment_is_not_proof": True,
                "cross_model_unavailable_is_not_pass": True,
                "self_critique_is_not_independent": True,
            },
        }


class IndependentClaimVerifier:
    """Verifier access path used by ResearchService.verify_claims_independently."""

    def __init__(self, store: ResearchStore) -> None:
        self.store = store

    def verify_project(self, project_id: str) -> IndependentVerificationReport:
        claims = self.store.list_claims(project_id)
        evidence = {e.evidence_id: e for e in self.store.list_evidence(project_id)}
        sources = self.store.list_sources(project_id)
        clusters = cluster_dependent_sources(sources)
        verdicts: list[IndependentEdgeVerdict] = []
        counts = {r: 0 for r in ClaimRelation}
        max_indep = 0

        for claim in claims:
            support_ids = list(claim.supporting_evidence_ids or [])
            contradict_ids = list(claim.contradicting_evidence_ids or [])
            support_source_ids = []
            for eid in support_ids + contradict_ids:
                ev = evidence.get(eid)
                if ev is None:
                    verdicts.append(
                        IndependentEdgeVerdict(
                            claim_id=claim.claim_id,
                            evidence_id=eid,
                            relation=ClaimRelation.INSUFFICIENT.value,
                            entailment_status="INSUFFICIENT_EVIDENCE",
                            overlap_ratio=0.0,
                            independent_cluster=False,
                            detail="evidence_missing",
                        )
                    )
                    counts[ClaimRelation.INSUFFICIENT] += 1
                    continue
                check = citation_entailment_check(claim.proposition, ev.span_text)
                rel = relation_from_entailment_status(str(check.get("status") or ""))
                if eid in contradict_ids and rel != ClaimRelation.CONTRADICTS:
                    # Author-tagged contradiction preserved when lexical check is weak.
                    if rel == ClaimRelation.INSUFFICIENT:
                        rel = ClaimRelation.CONTRADICTS
                overlap = float(check.get("overlap_ratio") or 0.0)
                if rel == ClaimRelation.INSUFFICIENT and overlap > 0.05:
                    rel = ClaimRelation.QUALIFIES
                elif rel == ClaimRelation.INSUFFICIENT:
                    rel = ClaimRelation.BACKGROUND
                if eid in support_ids:
                    support_source_ids.append(ev.source_id)
                indep = False
                if eid in support_ids:
                    # Single-source support is never "independent cluster" alone.
                    indep = independent_support_count([ev.source_id], clusters) >= 1
                verdicts.append(
                    IndependentEdgeVerdict(
                        claim_id=claim.claim_id,
                        evidence_id=eid,
                        relation=rel.value,
                        entailment_status=str(check.get("status") or "INSUFFICIENT_EVIDENCE"),
                        overlap_ratio=overlap,
                        independent_cluster=bool(indep),
                        detail=str(check.get("detail") or ""),
                    )
                )
                counts[rel] += 1
            if support_source_ids:
                max_indep = max(
                    max_indep,
                    int(independent_support_count(support_source_ids, clusters)),
                )

        return IndependentVerificationReport(
            report_id=f"iv_{uuid.uuid4().hex[:12]}",
            project_id=project_id,
            created_at=_utc_now(),
            verdicts=verdicts,
            supports=counts[ClaimRelation.SUPPORTS],
            contradicts=counts[ClaimRelation.CONTRADICTS],
            qualifies=counts[ClaimRelation.QUALIFIES],
            background=counts[ClaimRelation.BACKGROUND],
            insufficient=counts[ClaimRelation.INSUFFICIENT],
            independent_support_clusters=max_indep,
            cross_model_status="UNAVAILABLE",
            metadata={
                "claim_count": len(claims),
                "evidence_count": len(evidence),
                "verifier": "deterministic_independent_claim_verifier",
            },
        )
