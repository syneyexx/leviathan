"""Memory consolidation — episodic → semantic candidates with provenance (W8).

Never: model confidence 0.95 → permanent semantic truth.
Proposed semantic memories remain AGENT_PROPOSED until verification.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from .types import MemoryKind, MemoryTrustState, normalize_trust_state


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class SemanticCandidate:
    candidate_id: str
    content: str
    trust_state: MemoryTrustState
    source_episodic_ids: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    contradictions: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    admitted: bool = False
    admission_reason: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "content": self.content,
            "trust_state": self.trust_state.value,
            "source_episodic_ids": list(self.source_episodic_ids),
            "provenance": dict(self.provenance),
            "contradictions": list(self.contradictions),
            "evidence_refs": list(self.evidence_refs),
            "admitted": self.admitted,
            "admission_reason": self.admission_reason,
            "truth": {
                "model_confidence_is_not_memory_truth": True,
                "agent_proposed_until_verified": self.trust_state
                == MemoryTrustState.AGENT_PROPOSED,
            },
        }


@dataclass
class ConsolidationResult:
    candidates: list[SemanticCandidate] = field(default_factory=list)
    clusters: list[list[str]] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "candidates": [c.public_dict() for c in self.candidates],
            "clusters": [list(c) for c in self.clusters],
        }


class MemoryConsolidator:
    """Cluster episodic records → semantic candidates with trust gates."""

    def consolidate(
        self,
        episodic: Sequence[dict[str, Any]],
        *,
        existing_semantic: Sequence[dict[str, Any]] | None = None,
        min_cluster_size: int = 2,
    ) -> ConsolidationResult:
        clusters = self._cluster(list(episodic))
        candidates: list[SemanticCandidate] = []
        existing = list(existing_semantic or [])
        for cluster in clusters:
            if len(cluster) < min_cluster_size:
                continue
            texts = [str(e.get("content") or "") for e in cluster if e.get("content")]
            if not texts:
                continue
            # Representative = longest episodic span (not model confidence).
            content = max(texts, key=len)[:800]
            ids = tuple(str(e.get("memory_id") or e.get("id") or "") for e in cluster)
            ids = tuple(i for i in ids if i)
            contradictions = self._contradictions(content, existing)
            evidence_refs = []
            for e in cluster:
                for ref in e.get("source_refs") or e.get("evidence_refs") or []:
                    evidence_refs.append(str(ref))
            trust = MemoryTrustState.AGENT_PROPOSED
            # Only elevate when every member already VERIFIED/USER_STATED and no contradictions.
            member_trusts = {
                normalize_trust_state(e.get("trust_state") or e.get("trust"))
                for e in cluster
            }
            if (
                not contradictions
                and member_trusts
                and member_trusts <= {MemoryTrustState.VERIFIED, MemoryTrustState.USER_STATED}
                and evidence_refs
            ):
                trust = MemoryTrustState.SOURCE_DERIVED
            candidate = SemanticCandidate(
                candidate_id=f"sem:{uuid.uuid4().hex[:12]}",
                content=content,
                trust_state=trust,
                source_episodic_ids=ids,
                provenance={
                    "cluster_size": len(cluster),
                    "created_at": utc_now(),
                    "content_hash": hashlib.sha256(content.encode()).hexdigest()[:16],
                },
                contradictions=contradictions,
                evidence_refs=evidence_refs,
            )
            candidate.admitted, candidate.admission_reason = self._admit(candidate)
            candidates.append(candidate)
        return ConsolidationResult(candidates=candidates, clusters=[[str(e.get("memory_id") or "") for e in c] for c in clusters])

    def _cluster(self, items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        """Simple token-overlap clustering — deterministic, no LLM."""
        clusters: list[list[dict[str, Any]]] = []
        for item in items:
            kind = str(item.get("kind") or "").upper()
            if kind and kind not in {"EPISODIC", "NOTE", "SUMMARY", ""}:
                continue
            tokens = set(str(item.get("content") or "").lower().split())
            tokens = {t for t in tokens if len(t) > 3}
            placed = False
            for cluster in clusters:
                rep = set(str(cluster[0].get("content") or "").lower().split())
                rep = {t for t in rep if len(t) > 3}
                if not tokens or not rep:
                    continue
                overlap = len(tokens & rep) / max(1, len(tokens | rep))
                if overlap >= 0.25:
                    cluster.append(item)
                    placed = True
                    break
            if not placed:
                clusters.append([item])
        return clusters

    def _contradictions(self, content: str, existing: list[dict[str, Any]]) -> list[str]:
        out: list[str] = []
        lowered = content.lower()
        for sem in existing:
            other = str(sem.get("content") or "")
            if not other:
                continue
            # Naive negation conflict: "X is Y" vs "X is not Y"
            if " is not " in lowered and " is not " not in other.lower():
                subject = lowered.split(" is not ", 1)[0].strip()[-40:]
                if subject and subject in other.lower() and " is " in other.lower():
                    out.append(str(sem.get("memory_id") or sem.get("id") or other[:40]))
        return out

    def _admit(self, candidate: SemanticCandidate) -> tuple[bool, str]:
        if candidate.trust_state == MemoryTrustState.REVOKED:
            return False, "revoked"
        if candidate.contradictions:
            return False, "contradiction_pending"
        if candidate.trust_state == MemoryTrustState.AGENT_PROPOSED:
            # Admitted as candidate only — not as VERIFIED semantic truth.
            return True, "admitted_as_agent_proposed_candidate"
        if candidate.trust_state in {
            MemoryTrustState.SOURCE_DERIVED,
            MemoryTrustState.USER_STATED,
            MemoryTrustState.VERIFIED,
        }:
            return True, f"admitted_{candidate.trust_state.value.lower()}"
        return False, "trust_insufficient"
