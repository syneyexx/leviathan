"""Claim–evidence graph + reproducibility bundles (U227–U230)."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from Data.modules.common.atomic import atomic_write_text, ensure_dir

from .store import ResearchStore
from .types import ClaimStatus, ResearchClaim, ResearchEvidence, ResearchProject, ResearchSource


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class ClaimEvidenceEdge:
    edge_id: str
    claim_id: str
    evidence_id: str
    relation: str  # supports | contradicts | related
    uncertainty: str  # low | medium | high
    entailment_score: float | None = None
    entailment_passed: bool | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "claim_id": self.claim_id,
            "evidence_id": self.evidence_id,
            "relation": self.relation,
            "uncertainty": self.uncertainty,
            "entailment_score": self.entailment_score,
            "entailment_passed": self.entailment_passed,
        }


@dataclass
class ClaimEvidenceGraph:
    project_id: str
    nodes_claims: list[dict[str, Any]] = field(default_factory=list)
    nodes_evidence: list[dict[str, Any]] = field(default_factory=list)
    edges: list[ClaimEvidenceEdge] = field(default_factory=list)
    generated_at: str = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "claims": list(self.nodes_claims),
            "evidence": list(self.nodes_evidence),
            "edges": [e.public_dict() for e in self.edges],
            "generated_at": self.generated_at,
            "metadata": dict(self.metadata),
            "truth": {
                "graph_links_claims_to_evidence": True,
                "llm_judge_is_not_sole_proof": True,
            },
        }


def _token_overlap(a: str, b: str) -> float:
    ta = {t for t in a.lower().split() if len(t) > 2}
    tb = {t for t in b.lower().split() if len(t) > 2}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / float(len(ta | tb))


def _negation_contradiction(claim: str, evidence: str) -> str | None:
    """Return detail when evidence negates the claim; lexical overlap must not override."""
    import re

    claim_n = " ".join((claim or "").lower().split())
    evidence_n = " ".join((evidence or "").lower().split())

    def _negated(text: str) -> bool:
        return bool(
            re.search(
                r"\b(does not|do not|don't|doesn't|did not|didn't|never|no longer|"
                r"cannot|can't|is not|are not|isn't|aren't|was not|weren't|not)\b",
                text,
            )
        )

    def _core(text: str) -> set[str]:
        cleaned = re.sub(
            r"\b(does not|do not|don't|doesn't|did not|didn't|never|no longer|"
            r"cannot|can't|is not|are not|isn't|aren't|was not|weren't|not)\b",
            " ",
            text,
        )
        return {t for t in cleaned.split() if len(t) > 2}

    shared = _core(claim_n) & _core(evidence_n)
    if len(shared) >= 2 and _negated(claim_n) != _negated(evidence_n):
        return "negation polarity conflict with shared content"
    claim_nums = re.findall(r"\b\d+(?:\.\d+)?\b", claim_n)
    evidence_nums = re.findall(r"\b\d+(?:\.\d+)?\b", evidence_n)
    if claim_nums and evidence_nums and set(claim_nums).isdisjoint(set(evidence_nums)) and len(shared) >= 2:
        return "numeric mismatch with overlapping entities"
    return None


def citation_entailment_check(claim: str, span: str, *, min_overlap: float = 0.15) -> dict[str, Any]:
    """Heuristic entailment before finalizing high-confidence claims (U228).

    Status vocabulary: SUPPORTED | CONTRADICTED | INSUFFICIENT_EVIDENCE.
    Lexical overlap alone never overrides a detected contradiction.
    """
    score = _token_overlap(claim, span)
    contradiction = _negation_contradiction(claim, span)
    if contradiction:
        return {
            "overlap_ratio": score,
            "passed": False,
            "status": "CONTRADICTED",
            "min_overlap": min_overlap,
            "detail": contradiction,
            "truth": {
                "heuristic_entailment_is_not_proof": True,
                "lexical_overlap_does_not_override_contradiction": True,
            },
        }
    if score >= min_overlap:
        return {
            "overlap_ratio": score,
            "passed": True,
            "status": "SUPPORTED",
            "min_overlap": min_overlap,
            "detail": "lexical support (heuristic)",
            "truth": {
                "heuristic_entailment_is_not_proof": True,
                "lexical_overlap_does_not_override_contradiction": True,
            },
        }
    return {
        "overlap_ratio": score,
        "passed": False,
        "status": "INSUFFICIENT_EVIDENCE",
        "min_overlap": min_overlap,
        "detail": "insufficient lexical overlap",
        "truth": {
            "heuristic_entailment_is_not_proof": True,
            "lexical_overlap_does_not_override_contradiction": True,
        },
    }


class ClaimEvidenceGraphBuilder:
    def __init__(self, store: ResearchStore) -> None:
        self.store = store

    def build(self, project_id: str, *, gate_high_confidence: bool = True) -> ClaimEvidenceGraph:
        claims = self.store.list_claims(project_id)
        evidence = {e.evidence_id: e for e in self.store.list_evidence(project_id)}
        edges: list[ClaimEvidenceEdge] = []
        claim_nodes: list[dict[str, Any]] = []

        for claim in claims:
            status = claim.status
            support_ok = 0
            for eid in claim.supporting_evidence_ids:
                ev = evidence.get(eid)
                if ev is None:
                    continue
                check = citation_entailment_check(claim.proposition, ev.span_text)
                if check.get("status") == "CONTRADICTED":
                    edges.append(
                        ClaimEvidenceEdge(
                            edge_id=f"edge_{uuid.uuid4().hex[:10]}",
                            claim_id=claim.claim_id,
                            evidence_id=eid,
                            relation="contradicts",
                            uncertainty="high",
                            entailment_score=float(check["overlap_ratio"]),
                            entailment_passed=False,
                        )
                    )
                    if gate_high_confidence and status in {
                        ClaimStatus.SUPPORTED,
                        ClaimStatus.WEAKLY_SUPPORTED,
                    }:
                        status = ClaimStatus.DISPUTED
                        claim = ResearchClaim(
                            claim_id=claim.claim_id,
                            project_id=claim.project_id,
                            proposition=claim.proposition,
                            status=status,
                            created_at=claim.created_at,
                            updated_at=_utc_now(),
                            raw_wording=claim.raw_wording,
                            supporting_evidence_ids=list(claim.supporting_evidence_ids),
                            contradicting_evidence_ids=list(
                                dict.fromkeys([*claim.contradicting_evidence_ids, eid])
                            ),
                            source_diversity=claim.source_diversity,
                            metadata={
                                **dict(claim.metadata or {}),
                                "entailment_contradicted": True,
                                "entailment": check,
                            },
                        )
                        self.store.upsert_claim(claim)
                    continue
                if gate_high_confidence and status == ClaimStatus.SUPPORTED and not check["passed"]:
                    # Downgrade high-confidence claim when entailment fails (U228).
                    status = ClaimStatus.WEAKLY_SUPPORTED
                    claim = ResearchClaim(
                        claim_id=claim.claim_id,
                        project_id=claim.project_id,
                        proposition=claim.proposition,
                        status=status,
                        created_at=claim.created_at,
                        updated_at=_utc_now(),
                        raw_wording=claim.raw_wording,
                        supporting_evidence_ids=list(claim.supporting_evidence_ids),
                        contradicting_evidence_ids=list(claim.contradicting_evidence_ids),
                        source_diversity=claim.source_diversity,
                        metadata={
                            **dict(claim.metadata or {}),
                            "entailment_downgraded": True,
                            "entailment": check,
                        },
                    )
                    self.store.upsert_claim(claim)
                else:
                    support_ok += 1
                uncertainty = "low" if check["passed"] and status == ClaimStatus.SUPPORTED else (
                    "high" if not check["passed"] else "medium"
                )
                edges.append(
                    ClaimEvidenceEdge(
                        edge_id=f"edge_{uuid.uuid4().hex[:10]}",
                        claim_id=claim.claim_id,
                        evidence_id=eid,
                        relation="supports",
                        uncertainty=uncertainty,
                        entailment_score=float(check["overlap_ratio"]),
                        entailment_passed=bool(check["passed"]),
                    )
                )
            for eid in claim.contradicting_evidence_ids:
                edges.append(
                    ClaimEvidenceEdge(
                        edge_id=f"edge_{uuid.uuid4().hex[:10]}",
                        claim_id=claim.claim_id,
                        evidence_id=eid,
                        relation="contradicts",
                        uncertainty="medium",
                    )
                )
            claim_nodes.append(claim.public_dict())

        return ClaimEvidenceGraph(
            project_id=project_id,
            nodes_claims=claim_nodes,
            nodes_evidence=[e.public_dict() for e in evidence.values()],
            edges=edges,
            metadata={
                "claim_count": len(claim_nodes),
                "edge_count": len(edges),
                "gated_high_confidence": gate_high_confidence,
            },
        )


@dataclass
class ReproducibilityBundle:
    bundle_id: str
    project_id: str
    path: str
    content_hash: str
    created_at: str
    manifest: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "project_id": self.project_id,
            "path": self.path,
            "content_hash": self.content_hash,
            "created_at": self.created_at,
            "manifest": dict(self.manifest),
            "truth": {
                "bundle_is_reproducibility_aid": True,
                "not_implicit_knowledge_ingest": True,
            },
        }


class ReproducibilityBundleExporter:
    def __init__(self, store: ResearchStore, exports_root: Path) -> None:
        self.store = store
        self.exports_root = Path(exports_root)
        self.graph_builder = ClaimEvidenceGraphBuilder(store)

    def export(
        self,
        project: ResearchProject,
        *,
        model_revision: str | None = None,
    ) -> ReproducibilityBundle:
        ensure_dir(self.exports_root)
        graph = self.graph_builder.build(project.project_id)
        sources = [s.public_dict() for s in self.store.list_sources(project.project_id)]
        evidence = [e.public_dict() for e in self.store.list_evidence(project.project_id)]
        events = [e.public_dict() for e in self.store.list_events(project.project_id, limit=500)]
        plan = project.plan.public_dict() if project.plan else {}
        queries = list(plan.get("retrieval_queries") or [])
        # Freshness axes (U226): publication / retrieval dates tracked separately on sources.
        freshness = [
            {
                "source_id": s.get("source_id"),
                "published_at": s.get("published_at"),
                "fetched_at": s.get("fetched_at"),
                "created_at": s.get("created_at"),
                "event_date": (s.get("metadata") or {}).get("event_date"),
                "update_date": (s.get("metadata") or {}).get("update_date"),
            }
            for s in sources
        ]
        payload = {
            "bundle_schema_version": 1,
            "project": project.public_dict(),
            "plan": plan,
            "queries": queries,
            "sources": sources,
            "evidence": evidence,
            "claim_graph": graph.public_dict(),
            "events": events,
            "freshness": freshness,
            "model_revision": model_revision,
            "exported_at": _utc_now(),
        }
        raw = json.dumps(payload, indent=2, sort_keys=True, default=str)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        bundle_id = f"rb_{uuid.uuid4().hex[:12]}"
        path = self.exports_root / f"{project.project_id}_{bundle_id}.json"
        atomic_write_text(path, raw)
        return ReproducibilityBundle(
            bundle_id=bundle_id,
            project_id=project.project_id,
            path=str(path),
            content_hash=digest[:24],
            created_at=_utc_now(),
            manifest={
                "source_count": len(sources),
                "evidence_count": len(evidence),
                "claim_count": len(graph.nodes_claims),
                "query_count": len(queries),
                "model_revision": model_revision,
            },
        )
