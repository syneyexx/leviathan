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
    time_after: str | None = None
    time_before: str | None = None
    relation_class: str | None = None
    layer: str | None = None  # evidence | atlas | any


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
        return result

    @staticmethod
    def _passes_filters(hit: RetrievalHit, query: RetrievalQuery) -> bool:
        if query.min_confidence is not None and hit.confidence < query.min_confidence:
            return False
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
