from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .embeddings import (
    EmbeddingProvider,
    NullEmbeddingProvider,
    RerankerProvider,
    cosine_similarity,
)
from .store import KnowledgeStore
from .types import IngestStatus


@dataclass(frozen=True)
class RetrievalQuery:
    text: str
    limit: int = 5
    source: str | None = None
    status: IngestStatus = IngestStatus.READY
    use_embeddings: bool = True
    use_reranker: bool = False
    min_confidence: float | None = None
    min_score: float | None = None  # Wave 4: drop hits below threshold (exit gate)
    time_after: str | None = None
    time_before: str | None = None
    relation_class: str | None = None
    layer: str | None = None  # evidence | atlas | any
    record_trace: bool = True
    detect_contradictions: bool = True


@dataclass(frozen=True)
class RetrievalTrace:
    """Reproducible retrieval audit (U117)."""

    query: str
    candidate_count: int
    selected_count: int
    min_score: float | None
    modalities: tuple[str, ...]
    selected_chunk_ids: tuple[str, ...]
    contradictions: tuple[dict[str, Any], ...] = ()
    dropped_below_threshold: int = 0

    def public_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "candidate_count": self.candidate_count,
            "selected_count": self.selected_count,
            "min_score": self.min_score,
            "modalities": list(self.modalities),
            "selected_chunk_ids": list(self.selected_chunk_ids),
            "contradictions": list(self.contradictions),
            "dropped_below_threshold": self.dropped_below_threshold,
            "truth": {
                "vector_index_is_not_canonical_fact_store": True,
                "model_output_is_not_evidence": True,
            },
        }


@dataclass(frozen=True)
class CitationCheck:
    """Citation entailment gate — contradiction-aware (U109).

    Status vocabulary:
      SUPPORTED | CONTRADICTED | INSUFFICIENT_EVIDENCE
    Lexical overlap alone never overrides a detected contradiction.
    """

    claim: str
    chunk_id: str
    entailed: bool
    overlap_ratio: float
    detail: str
    status: str = "INSUFFICIENT_EVIDENCE"  # SUPPORTED | CONTRADICTED | INSUFFICIENT_EVIDENCE

    def public_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "chunk_id": self.chunk_id,
            "entailed": self.entailed,
            "status": self.status,
            "overlap_ratio": self.overlap_ratio,
            "detail": self.detail,
            "truth": {
                "heuristic_entailment_is_not_proof": True,
                "lexical_overlap_does_not_override_contradiction": True,
            },
        }


@dataclass(frozen=True)
class RetrievalHit:
    document_id: str
    chunk_id: str
    chunk_index: int
    title: str
    source: str
    content: str
    score: float
    modality: str  # lexical | vector | hybrid | reranked
    original_path: str | None
    document_hash: str | None
    chunk_hash: str
    confidence: float = 1.0
    start_offset: int = 0
    end_offset: int = 0
    source_type: str = "document"
    layer: str = "evidence"
    provenance: dict[str, Any] = field(default_factory=dict)

    def as_context_document(self) -> dict[str, Any]:
        """Shape expected by ContextBuilder / chat orchestration."""
        return {
            "id": self.document_id,
            "title": self.title,
            "content": self.content,
            "source": self.source,
            "chunk_id": self.chunk_id,
            "chunk_index": self.chunk_index,
            "original_path": self.original_path,
            "content_hash": self.document_hash,
            "chunk_hash": self.chunk_hash,
            "confidence": self.confidence,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "source_type": self.source_type,
            "layer": self.layer,
        }

    def public_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "chunk_index": self.chunk_index,
            "title": self.title,
            "source": self.source,
            "content": self.content,
            "score": self.score,
            "modality": self.modality,
            "original_path": self.original_path,
            "document_hash": self.document_hash,
            "chunk_hash": self.chunk_hash,
            "confidence": self.confidence,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "source_type": self.source_type,
            "layer": self.layer,
            "provenance": self.provenance,
        }


class HybridRetriever:
    """Lexical + optional dense retrieval with score fusion (HybridRetriever V3).

    Vector path is only used when EmbeddingProvider.available() is true.
    Null/unavailable providers produce lexical-only results — never fabricated vectors.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        embeddings: EmbeddingProvider | None = None,
        *,
        reranker: RerankerProvider | None = None,
        lexical_weight: float = 0.55,
        dense_weight: float = 0.45,
        candidate_multiplier: int = 3,
    ) -> None:
        self.store = store
        self.embeddings = embeddings or NullEmbeddingProvider()
        self.reranker = reranker
        self.lexical_weight = lexical_weight
        self.dense_weight = dense_weight
        self.candidate_multiplier = max(1, candidate_multiplier)

    def search(self, query: RetrievalQuery) -> list[RetrievalHit]:
        fetch_limit = max(query.limit * self.candidate_multiplier, query.limit)
        lexical_rows = self.store.search_lexical(
            query.text,
            limit=fetch_limit,
            source=query.source,
            status=query.status,
        )
        by_chunk: dict[str, RetrievalHit] = {}
        for row in lexical_rows:
            rank = float(row.get("rank") or 0.0)
            score = 1.0 / (1.0 + max(rank, 0.0))
            hit = self._row_to_hit(row, score=score, modality="lexical")
            if not self._passes_filters(hit, query):
                continue
            by_chunk[hit.chunk_id] = hit

        dense_used = False
        if query.use_embeddings and self.embeddings.available():
            dense_used = True
            query_vec = self.embeddings.embed_query(query.text)
            dense_rows = self.store.search_dense(
                query_vec,
                limit=fetch_limit,
                source=query.source,
                status=query.status,
            )
            for row in dense_rows:
                dense_score = float(row.get("dense_score") or 0.0)
                existing = by_chunk.get(row["chunk_id"])
                if existing is None:
                    hit = self._row_to_hit(row, score=dense_score, modality="vector")
                    if not self._passes_filters(hit, query):
                        continue
                    by_chunk[hit.chunk_id] = hit
                else:
                    fused = (
                        self.lexical_weight * existing.score + self.dense_weight * dense_score
                    )
                    by_chunk[existing.chunk_id] = RetrievalHit(
                        document_id=existing.document_id,
                        chunk_id=existing.chunk_id,
                        chunk_index=existing.chunk_index,
                        title=existing.title,
                        source=existing.source,
                        content=existing.content,
                        score=round(fused, 6),
                        modality="hybrid",
                        original_path=existing.original_path,
                        document_hash=existing.document_hash,
                        chunk_hash=existing.chunk_hash,
                        confidence=existing.confidence,
                        start_offset=existing.start_offset,
                        end_offset=existing.end_offset,
                        source_type=existing.source_type,
                        layer=existing.layer,
                        provenance={
                            **existing.provenance,
                            "lexical_score": existing.score,
                            "dense_score": dense_score,
                            "fusion": "weighted_sum",
                        },
                    )

            # Also upgrade pure lexical hits that have stored embeddings.
            for chunk_id, hit in list(by_chunk.items()):
                if hit.modality != "lexical":
                    continue
                stored = self.store.get_chunk_embedding(chunk_id)
                if stored is None:
                    continue
                dense_score = cosine_similarity(query_vec, stored)
                fused = self.lexical_weight * hit.score + self.dense_weight * dense_score
                by_chunk[chunk_id] = RetrievalHit(
                    document_id=hit.document_id,
                    chunk_id=hit.chunk_id,
                    chunk_index=hit.chunk_index,
                    title=hit.title,
                    source=hit.source,
                    content=hit.content,
                    score=round(fused, 6),
                    modality="hybrid",
                    original_path=hit.original_path,
                    document_hash=hit.document_hash,
                    chunk_hash=hit.chunk_hash,
                    confidence=hit.confidence,
                    start_offset=hit.start_offset,
                    end_offset=hit.end_offset,
                    source_type=hit.source_type,
                    layer=hit.layer,
                    provenance={
                        **hit.provenance,
                        "lexical_score": hit.score,
                        "dense_score": dense_score,
                        "fusion": "weighted_sum",
                    },
                )

        hits = sorted(by_chunk.values(), key=lambda item: item.score, reverse=True)

        if (
            query.use_reranker
            and self.reranker is not None
            and self.reranker.available()
            and hits
        ):
            top = hits[: max(query.limit * 2, query.limit)]
            scores = self.reranker.score(query.text, [h.content for h in top])
            reranked: list[RetrievalHit] = []
            for hit, score in zip(top, scores):
                reranked.append(
                    RetrievalHit(
                        document_id=hit.document_id,
                        chunk_id=hit.chunk_id,
                        chunk_index=hit.chunk_index,
                        title=hit.title,
                        source=hit.source,
                        content=hit.content,
                        score=round(float(score), 6),
                        modality="reranked",
                        original_path=hit.original_path,
                        document_hash=hit.document_hash,
                        chunk_hash=hit.chunk_hash,
                        confidence=hit.confidence,
                        start_offset=hit.start_offset,
                        end_offset=hit.end_offset,
                        source_type=hit.source_type,
                        layer=hit.layer,
                        provenance={**hit.provenance, "pre_rerank_score": hit.score},
                    )
                )
            hits = sorted(reranked, key=lambda item: item.score, reverse=True)

        if query.relation_class:
            # Soft filter via store relation atoms attached to chunks.
            allowed = {
                atom.chunk_id
                for atom in self.store.list_relation_atoms(limit=500)
                if atom.relation_class.value == query.relation_class and atom.chunk_id
            }
            if allowed:
                hits = [h for h in hits if h.chunk_id in allowed]

        before_threshold = list(hits)
        dropped_below = 0
        if query.min_score is not None:
            hits = [h for h in hits if h.score >= query.min_score]
            dropped_below = len(before_threshold) - len(hits)

        result = hits[: query.limit]
        # Annotate whether dense path was eligible (for observability).
        for idx, hit in enumerate(result):
            if dense_used and "dense_eligible" not in hit.provenance:
                result[idx] = RetrievalHit(
                    document_id=hit.document_id,
                    chunk_id=hit.chunk_id,
                    chunk_index=hit.chunk_index,
                    title=hit.title,
                    source=hit.source,
                    content=hit.content,
                    score=hit.score,
                    modality=hit.modality,
                    original_path=hit.original_path,
                    document_hash=hit.document_hash,
                    chunk_hash=hit.chunk_hash,
                    confidence=hit.confidence,
                    start_offset=hit.start_offset,
                    end_offset=hit.end_offset,
                    source_type=hit.source_type,
                    layer=hit.layer,
                    provenance={**hit.provenance, "dense_eligible": True},
                )

        if query.record_trace:
            contradictions = (
                self._detect_contradictions(result) if query.detect_contradictions else []
            )
            # Stash last trace on instance for callers that want it without API change.
            self.last_trace = RetrievalTrace(
                query=query.text,
                candidate_count=len(before_threshold),
                selected_count=len(result),
                min_score=query.min_score,
                modalities=tuple(sorted({h.modality for h in result})),
                selected_chunk_ids=tuple(h.chunk_id for h in result),
                contradictions=tuple(contradictions),
                dropped_below_threshold=dropped_below,
            )
        return result

    def search_with_trace(
        self, query: RetrievalQuery
    ) -> tuple[list[RetrievalHit], RetrievalTrace]:
        hits = self.search(query)
        trace = getattr(self, "last_trace", None)
        if trace is None:
            trace = RetrievalTrace(
                query=query.text,
                candidate_count=len(hits),
                selected_count=len(hits),
                min_score=query.min_score,
                modalities=tuple(sorted({h.modality for h in hits})),
                selected_chunk_ids=tuple(h.chunk_id for h in hits),
            )
        return hits, trace

    @staticmethod
    def verify_citation(claim: str, hit: RetrievalHit, *, min_overlap: float = 0.2) -> CitationCheck:
        """Citation entailment with negation/contradiction detection.

        Lexical overlap alone is never sufficient when evidence contradicts the claim.
        """
        claim_norm = " ".join((claim or "").lower().split())
        content_norm = " ".join((hit.content or "").lower().split())
        claim_tokens = {t for t in claim_norm.split() if len(t) > 2}
        content_tokens = {t for t in content_norm.split() if len(t) > 2}
        if not claim_tokens:
            return CitationCheck(
                claim=claim,
                chunk_id=hit.chunk_id,
                entailed=False,
                overlap_ratio=0.0,
                detail="empty claim",
                status="INSUFFICIENT_EVIDENCE",
            )
        overlap = len(claim_tokens & content_tokens) / len(claim_tokens)

        # Negation / contradiction heuristics (must beat pure overlap).
        contradiction = HybridRetriever._claim_contradicted_by_evidence(claim_norm, content_norm)
        if contradiction:
            return CitationCheck(
                claim=claim,
                chunk_id=hit.chunk_id,
                entailed=False,
                overlap_ratio=round(overlap, 4),
                detail=contradiction,
                status="CONTRADICTED",
            )

        if overlap >= min_overlap:
            return CitationCheck(
                claim=claim,
                chunk_id=hit.chunk_id,
                entailed=True,
                overlap_ratio=round(overlap, 4),
                detail="lexical support (heuristic — not proof)",
                status="SUPPORTED",
            )
        return CitationCheck(
            claim=claim,
            chunk_id=hit.chunk_id,
            entailed=False,
            overlap_ratio=round(overlap, 4),
            detail="insufficient lexical overlap",
            status="INSUFFICIENT_EVIDENCE",
        )

    @staticmethod
    def _claim_contradicted_by_evidence(claim: str, evidence: str) -> str | None:
        """Return contradiction detail when evidence negates the claim; else None."""
        import re

        def _negated(text: str) -> bool:
            return bool(
                re.search(
                    r"\b(does not|do not|don't|doesn't|did not|didn't|never|no longer|"
                    r"cannot|can't|is not|are not|isn't|aren't|was not|weren't|not)\b",
                    text,
                )
            )

        claim_neg = _negated(claim)
        evidence_neg = _negated(evidence)

        # Strip negation markers for content comparison.
        def _core(text: str) -> set[str]:
            cleaned = re.sub(
                r"\b(does not|do not|don't|doesn't|did not|didn't|never|no longer|"
                r"cannot|can't|is not|are not|isn't|aren't|was not|weren't|not)\b",
                " ",
                text,
            )
            return {t for t in cleaned.split() if len(t) > 2}

        claim_core = _core(claim)
        evidence_core = _core(evidence)
        shared = claim_core & evidence_core
        # Require meaningful shared content + opposite polarity.
        if len(shared) >= 2 and claim_neg != evidence_neg:
            return "negation polarity conflict with shared content"

        # Numeric / unit mismatch on shared entities.
        claim_nums = re.findall(r"\b\d+(?:\.\d+)?\b", claim)
        evidence_nums = re.findall(r"\b\d+(?:\.\d+)?\b", evidence)
        if claim_nums and evidence_nums and set(claim_nums).isdisjoint(set(evidence_nums)):
            # Only flag when surrounding content overlaps enough.
            if len(shared) >= 2:
                return "numeric mismatch with overlapping entities"

        return None

    @staticmethod
    def _detect_contradictions(hits: list[RetrievalHit]) -> list[dict[str, Any]]:
        """Surface obvious yes/no conflicts across top hits (U111)."""
        contradictions: list[dict[str, Any]] = []
        texts = [(h.chunk_id, h.content.lower()) for h in hits]
        for i, (cid_a, text_a) in enumerate(texts):
            for cid_b, text_b in texts[i + 1 :]:
                a_neg = " not " in f" {text_a} " or text_a.startswith("not ")
                b_neg = " not " in f" {text_b} " or text_b.startswith("not ")
                # Shared content words but opposite negation → visible contradiction.
                shared = set(text_a.split()) & set(text_b.split())
                if len(shared) >= 3 and a_neg != b_neg:
                    contradictions.append(
                        {
                            "chunk_a": cid_a,
                            "chunk_b": cid_b,
                            "detail": "possible negation conflict",
                        }
                    )
        return contradictions

    @staticmethod
    def _passes_filters(hit: RetrievalHit, query: RetrievalQuery) -> bool:
        if query.min_confidence is not None and hit.confidence < query.min_confidence:
            return False
        # min_score applied after fusion so dropped_below_threshold is measurable
        if query.layer and query.layer != "any" and hit.layer != query.layer:
            return False
        updated = str(hit.provenance.get("updated_at") or "")
        if query.time_after and updated and updated < query.time_after:
            return False
        if query.time_before and updated and updated > query.time_before:
            return False
        return True

    @staticmethod
    def _row_to_hit(row: dict[str, Any], *, score: float, modality: str) -> RetrievalHit:
        return RetrievalHit(
            document_id=row["document_id"],
            chunk_id=row["chunk_id"],
            chunk_index=int(row["chunk_index"]),
            title=row["title"],
            source=row["source"],
            content=row.get("chunk_content") or row.get("content") or "",
            score=score,
            modality=modality,
            original_path=row.get("original_path"),
            document_hash=row.get("document_hash"),
            chunk_hash=row.get("chunk_hash") or row.get("content_hash") or "",
            confidence=float(row.get("confidence") if row.get("confidence") is not None else 1.0),
            start_offset=int(row.get("start_offset") or 0),
            end_offset=int(row.get("end_offset") or 0),
            source_type=str(row.get("source_type") or "document"),
            layer="evidence",
            provenance={
                "updated_at": row.get("updated_at"),
                "uncertainty_notes": row.get("uncertainty_notes") or "",
            },
        )
