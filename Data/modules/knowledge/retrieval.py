from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .embeddings import (
    EmbeddingProvider,
    NullEmbeddingProvider,
    RerankerProvider,
    cosine_similarity,
)
from .store import KnowledgeStore
from .types import IngestStatus

# Reciprocal Rank Fusion constant (Cormack et al.). Rank-based: does not assume
# positive BM25 magnitudes. SQLite FTS5 bm25() returns lower (more negative) = better.
RRF_K = 60


class RetrievalMode(str, Enum):
    """Explicit retrieval modality for evaluation and callers."""

    LEXICAL = "lexical"
    DENSE = "dense"
    HYBRID = "hybrid"
    HYBRID_RERANK = "hybrid_rerank"


@dataclass(frozen=True)
class RetrievalQuery:
    text: str
    limit: int = 5
    source: str | None = None
    status: IngestStatus = IngestStatus.READY
    use_embeddings: bool = True
    use_reranker: bool = False
    mode: RetrievalMode | str | None = None
    min_confidence: float | None = None
    min_score: float | None = None  # Wave 4: drop hits below threshold (exit gate)
    time_after: str | None = None
    time_before: str | None = None
    relation_class: str | None = None
    layer: str | None = None  # evidence | atlas | any
    record_trace: bool = True
    detect_contradictions: bool = True
    require_source_valid: bool = True
    rrf_k: int = RRF_K

    def resolved_mode(self) -> RetrievalMode:
        if self.mode is not None:
            if isinstance(self.mode, RetrievalMode):
                return self.mode
            return RetrievalMode(str(self.mode).strip().lower())
        if self.use_reranker:
            return RetrievalMode.HYBRID_RERANK
        if self.use_embeddings:
            return RetrievalMode.HYBRID
        return RetrievalMode.LEXICAL


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
    mode: str = "hybrid"
    fusion: str = "none"
    embedding_is_semantic: bool | None = None
    bm25_semantics: str = "sqlite_fts5_bm25_lower_is_better"

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
            "mode": self.mode,
            "fusion": self.fusion,
            "embedding_is_semantic": self.embedding_is_semantic,
            "bm25_semantics": self.bm25_semantics,
            "truth": {
                "vector_index_is_not_canonical_fact_store": True,
                "model_output_is_not_evidence": True,
                "hash_vectors_are_not_semantic_embeddings": self.embedding_is_semantic is False,
                "sqlite_bm25_is_not_assumed_positive": True,
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


def bm25_relevance(bm25_raw: float) -> float:
    """Convert SQLite FTS5 bm25 (lower/more-negative = better) to higher-is-better.

    Does not assume conventional positive Okapi BM25 scores.
    """
    return float(-bm25_raw)


def reciprocal_rank_fusion(
    ranked_lists: list[list[str]],
    *,
    k: int = RRF_K,
) -> dict[str, float]:
    """RRF over 1-based ranks. Mathematically appropriate across incomparable score spaces."""
    fused: dict[str, float] = {}
    kk = max(1, int(k))
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked, start=1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (kk + rank)
    return fused


class HybridRetriever:
    """Lexical + optional dense retrieval with rank fusion (HybridRetriever V3).

    Vector path is only used when EmbeddingProvider.available() is true.
    Null/unavailable providers produce lexical-only results — never fabricated vectors.
    Hash embedding providers may participate in dense fusion but are never labeled semantic.
    Final selection may apply MMR-style diversity when ``diversity_enabled`` is set.
    Exact / high lexical overlap hits keep preference over pure diversity.
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
        rrf_k: int = RRF_K,
        diversity_enabled: bool = False,
        diversity_strength: float = 0.3,
        observability_emit: Any | None = None,
    ) -> None:
        self.store = store
        self.embeddings = embeddings or NullEmbeddingProvider()
        self.reranker = reranker
        self.lexical_weight = lexical_weight
        self.dense_weight = dense_weight
        self.candidate_multiplier = max(1, candidate_multiplier)
        self.rrf_k = max(1, int(rrf_k))
        self.diversity_enabled = bool(diversity_enabled)
        self.diversity_strength = float(diversity_strength)
        self._emit = observability_emit

    def search(self, query: RetrievalQuery) -> list[RetrievalHit]:
        mode = query.resolved_mode()
        fetch_limit = max(query.limit * self.candidate_multiplier, query.limit)
        embedding_is_semantic = self._embedding_is_semantic()
        fusion_used = "none"

        lexical_hits: list[RetrievalHit] = []
        dense_hits: list[RetrievalHit] = []
        by_chunk: dict[str, RetrievalHit] = {}

        if mode in {RetrievalMode.LEXICAL, RetrievalMode.HYBRID, RetrievalMode.HYBRID_RERANK}:
            lexical_rows = self.store.search_lexical(
                query.text,
                limit=fetch_limit,
                source=query.source,
                status=query.status,
            )
            for position, row in enumerate(lexical_rows, start=1):
                bm25_raw = float(row.get("rank") if row.get("rank") is not None else 0.0)
                relevance = bm25_relevance(bm25_raw)
                hit = self._row_to_hit(
                    row,
                    score=relevance,
                    modality="lexical",
                    extra_provenance={
                        "bm25_raw": bm25_raw,
                        "bm25_relevance": relevance,
                        "lexical_rank": position,
                        "bm25_semantics": "sqlite_fts5_bm25_lower_is_better",
                    },
                )
                if not self._passes_filters(hit, query):
                    continue
                lexical_hits.append(hit)
                by_chunk[hit.chunk_id] = hit

        dense_eligible = (
            mode in {RetrievalMode.DENSE, RetrievalMode.HYBRID, RetrievalMode.HYBRID_RERANK}
            and self.embeddings.available()
        )
        query_vec: list[float] | None = None
        if dense_eligible:
            query_vec = self.embeddings.embed_query(query.text)
            dense_rows = self.store.search_dense(
                query_vec,
                limit=fetch_limit,
                source=query.source,
                status=query.status,
            )
            for position, row in enumerate(dense_rows, start=1):
                dense_score = float(row.get("dense_score") or 0.0)
                existing = by_chunk.get(row["chunk_id"])
                if existing is None:
                    hit = self._row_to_hit(
                        row,
                        score=dense_score,
                        modality="vector",
                        extra_provenance={
                            "dense_score": dense_score,
                            "dense_rank": position,
                            "embedding_provider": getattr(self.embeddings, "provider_id", "unknown"),
                            "embedding_is_semantic": embedding_is_semantic,
                        },
                    )
                    if not self._passes_filters(hit, query):
                        continue
                    dense_hits.append(hit)
                    by_chunk[hit.chunk_id] = hit
                else:
                    dense_hits.append(
                        RetrievalHit(
                            document_id=existing.document_id,
                            chunk_id=existing.chunk_id,
                            chunk_index=existing.chunk_index,
                            title=existing.title,
                            source=existing.source,
                            content=existing.content,
                            score=dense_score,
                            modality="vector",
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
                                "dense_score": dense_score,
                                "dense_rank": position,
                                "embedding_provider": getattr(
                                    self.embeddings, "provider_id", "unknown"
                                ),
                                "embedding_is_semantic": embedding_is_semantic,
                            },
                        )
                    )

            # Fill dense list for lexical-only chunks that have stored embeddings
            # (dense search may already include them; avoid duplicate ranks).
            seen_dense = {h.chunk_id for h in dense_hits}
            for chunk_id, hit in list(by_chunk.items()):
                if chunk_id in seen_dense or query_vec is None:
                    continue
                stored = self.store.get_chunk_embedding(chunk_id)
                if stored is None:
                    continue
                dense_score = cosine_similarity(query_vec, stored)
                dense_hits.append(
                    RetrievalHit(
                        document_id=hit.document_id,
                        chunk_id=hit.chunk_id,
                        chunk_index=hit.chunk_index,
                        title=hit.title,
                        source=hit.source,
                        content=hit.content,
                        score=dense_score,
                        modality="vector",
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
                            "dense_score": dense_score,
                            "embedding_provider": getattr(self.embeddings, "provider_id", "unknown"),
                            "embedding_is_semantic": embedding_is_semantic,
                        },
                    )
                )
            dense_hits.sort(key=lambda h: h.score, reverse=True)
            # Re-assign dense ranks after sort
            dense_hits = [
                RetrievalHit(
                    document_id=h.document_id,
                    chunk_id=h.chunk_id,
                    chunk_index=h.chunk_index,
                    title=h.title,
                    source=h.source,
                    content=h.content,
                    score=h.score,
                    modality=h.modality,
                    original_path=h.original_path,
                    document_hash=h.document_hash,
                    chunk_hash=h.chunk_hash,
                    confidence=h.confidence,
                    start_offset=h.start_offset,
                    end_offset=h.end_offset,
                    source_type=h.source_type,
                    layer=h.layer,
                    provenance={**h.provenance, "dense_rank": i},
                )
                for i, h in enumerate(dense_hits, start=1)
            ]

        # Mode-specific assembly
        if mode == RetrievalMode.LEXICAL:
            hits = sorted(lexical_hits, key=lambda h: h.score, reverse=True)
            fusion_used = "bm25_relevance"
        elif mode == RetrievalMode.DENSE:
            if not dense_eligible:
                hits = []
            else:
                hits = list(dense_hits)
            fusion_used = "cosine"
        else:
            # HYBRID / HYBRID_RERANK — RRF across available ranked lists
            lists: list[list[str]] = []
            if lexical_hits:
                lists.append([h.chunk_id for h in lexical_hits])
            if dense_hits:
                lists.append([h.chunk_id for h in dense_hits])
            if not lists:
                hits = []
            elif len(lists) == 1:
                # Single modality present — keep that modality's scores
                if lexical_hits and not dense_hits:
                    hits = sorted(lexical_hits, key=lambda h: h.score, reverse=True)
                    fusion_used = "bm25_relevance"
                else:
                    hits = list(dense_hits)
                    fusion_used = "cosine"
            else:
                k = query.rrf_k if query.rrf_k else self.rrf_k
                fused_scores = reciprocal_rank_fusion(lists, k=k)
                fusion_used = "rrf"
                # Merge hit metadata preferring lexical base then dense-only
                merged: dict[str, RetrievalHit] = {h.chunk_id: h for h in lexical_hits}
                for h in dense_hits:
                    if h.chunk_id not in merged:
                        merged[h.chunk_id] = h
                hits = []
                for chunk_id, rrf_score in fused_scores.items():
                    base = merged[chunk_id]
                    lex = next((x for x in lexical_hits if x.chunk_id == chunk_id), None)
                    den = next((x for x in dense_hits if x.chunk_id == chunk_id), None)
                    modality = "hybrid" if lex and den else (lex.modality if lex else "vector")
                    hits.append(
                        RetrievalHit(
                            document_id=base.document_id,
                            chunk_id=base.chunk_id,
                            chunk_index=base.chunk_index,
                            title=base.title,
                            source=base.source,
                            content=base.content,
                            score=round(rrf_score, 6),
                            modality=modality,
                            original_path=base.original_path,
                            document_hash=base.document_hash,
                            chunk_hash=base.chunk_hash,
                            confidence=base.confidence,
                            start_offset=base.start_offset,
                            end_offset=base.end_offset,
                            source_type=base.source_type,
                            layer=base.layer,
                            provenance={
                                **base.provenance,
                                **(den.provenance if den else {}),
                                "lexical_rank": (lex.provenance.get("lexical_rank") if lex else None),
                                "dense_rank": (den.provenance.get("dense_rank") if den else None),
                                "bm25_raw": (lex.provenance.get("bm25_raw") if lex else None),
                                "dense_score": (den.provenance.get("dense_score") if den else None),
                                "fusion": "rrf",
                                "rrf_k": k,
                                "rrf_score": round(rrf_score, 6),
                                "embedding_is_semantic": embedding_is_semantic,
                            },
                        )
                    )
                hits.sort(key=lambda h: h.score, reverse=True)

        if (
            mode == RetrievalMode.HYBRID_RERANK
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
                        provenance={
                            **hit.provenance,
                            "pre_rerank_score": hit.score,
                            "fusion": hit.provenance.get("fusion", fusion_used),
                        },
                    )
                )
            hits = sorted(reranked, key=lambda item: item.score, reverse=True)
            fusion_used = f"{fusion_used}+rerank"

        if query.relation_class:
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

        diversity_applied = False
        if self.diversity_enabled and hits and query.limit > 1:
            selected = self._mmr_select(
                hits,
                query_text=query.text,
                limit=query.limit,
                strength=self.diversity_strength,
            )
            if selected:
                hits = selected
                diversity_applied = True
                fusion_used = f"{fusion_used}+mmr" if fusion_used else "mmr"

        result = hits[: query.limit]
        for idx, hit in enumerate(result):
            prov = {
                **hit.provenance,
                "dense_eligible": dense_eligible,
                "embedding_is_semantic": embedding_is_semantic,
                "retrieval_mode": mode.value,
            }
            if "fusion" not in prov:
                prov["fusion"] = fusion_used
            if diversity_applied:
                prov["diversity"] = {
                    "enabled": True,
                    "strength": self.diversity_strength,
                    "method": "mmr",
                }
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
                provenance=prov,
            )

        if query.record_trace:
            contradictions = (
                self._detect_contradictions(result) if query.detect_contradictions else []
            )
            self.last_trace = RetrievalTrace(
                query=query.text,
                candidate_count=len(before_threshold),
                selected_count=len(result),
                min_score=query.min_score,
                modalities=tuple(sorted({h.modality for h in result})),
                selected_chunk_ids=tuple(h.chunk_id for h in result),
                contradictions=tuple(contradictions),
                dropped_below_threshold=dropped_below,
                mode=mode.value,
                fusion=fusion_used,
                embedding_is_semantic=embedding_is_semantic if dense_eligible else None,
            )

        if self._emit is not None:
            try:
                self._emit(
                    "knowledge",
                    "hybrid_retrieval",
                    payload={
                        "query_preview": (query.text or "")[:120],
                        "mode": mode.value,
                        "fusion": fusion_used,
                        "candidate_count": len(before_threshold),
                        "selected_count": len(result),
                        "diversity_applied": diversity_applied,
                        "embedding_is_semantic": embedding_is_semantic if dense_eligible else None,
                    },
                )
            except Exception:  # noqa: BLE001
                pass
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
                mode=query.resolved_mode().value,
            )
        return hits, trace

    @staticmethod
    def _token_set(text: str) -> set[str]:
        import re

        return {t for t in re.findall(r"[^\W_]{2,}", (text or "").lower(), flags=re.UNICODE)}

    @classmethod
    def _jaccard(cls, a: set[str], b: set[str]) -> float:
        if not a or not b:
            return 0.0
        inter = len(a & b)
        union = len(a | b)
        return inter / union if union else 0.0

    @classmethod
    def _exact_match_boost(cls, query_text: str, content: str) -> float:
        """Prefer precision: high query-token coverage in content is exact-ish."""
        q = cls._token_set(query_text)
        if not q:
            return 0.0
        c = cls._token_set(content)
        coverage = len(q & c) / len(q)
        # Phrase containment is a strong exact signal.
        q_norm = " ".join((query_text or "").lower().split())
        c_norm = " ".join((content or "").lower().split())
        if q_norm and q_norm in c_norm:
            return 1.0
        return coverage

    def _mmr_select(
        self,
        hits: list[RetrievalHit],
        *,
        query_text: str,
        limit: int,
        strength: float,
    ) -> list[RetrievalHit]:
        """Simple MMR-style selection with exact-match preference.

        ``strength`` in [0,1] controls novelty weight (1 = max diversity).
        Hits with high exact overlap are always preferred early.
        """
        if not hits or limit <= 0:
            return []
        strength = min(1.0, max(0.0, float(strength)))
        # lambda_rel: relevance weight; higher strength → lower lambda_rel
        lambda_rel = 1.0 - strength

        # Pin exact / near-exact matches first (precision preference).
        scored = []
        for hit in hits:
            exact = self._exact_match_boost(query_text, hit.content)
            scored.append((exact, hit))
        scored.sort(key=lambda item: (item[0], item[1].score), reverse=True)

        selected: list[RetrievalHit] = []
        remaining: list[RetrievalHit] = []
        for exact, hit in scored:
            if exact >= 0.85 and len(selected) < limit:
                selected.append(hit)
            else:
                remaining.append(hit)

        token_cache: dict[str, set[str]] = {
            h.chunk_id: self._token_set(h.content) for h in hits
        }
        # Normalize relevance scores to [0,1] for MMR mix.
        max_score = max((h.score for h in hits), default=1.0) or 1.0

        while remaining and len(selected) < limit:
            best_idx = 0
            best_val = float("-inf")
            selected_tokens = [token_cache.get(h.chunk_id, set()) for h in selected]
            for idx, hit in enumerate(remaining):
                relevance = float(hit.score) / max_score if max_score else 0.0
                novelty_pen = 0.0
                if selected_tokens:
                    ht = token_cache.get(hit.chunk_id, set())
                    novelty_pen = max(
                        (self._jaccard(ht, st) for st in selected_tokens),
                        default=0.0,
                    )
                # Also diversify by document_id when content is near-duplicate.
                same_doc = any(hit.document_id == s.document_id for s in selected)
                if same_doc:
                    novelty_pen = max(novelty_pen, 0.55)
                mmr = lambda_rel * relevance - (1.0 - lambda_rel) * novelty_pen
                if mmr > best_val:
                    best_val = mmr
                    best_idx = idx
            selected.append(remaining.pop(best_idx))

        return selected

    def _embedding_is_semantic(self) -> bool:
        status = {}
        try:
            status = self.embeddings.status() if hasattr(self.embeddings, "status") else {}
        except Exception:  # noqa: BLE001
            status = {}
        if "is_semantic" in status:
            return bool(status["is_semantic"])
        if hasattr(self.embeddings, "is_semantic"):
            return bool(getattr(self.embeddings, "is_semantic"))
        provider_id = str(getattr(self.embeddings, "provider_id", "") or "").lower()
        if provider_id in {"local_hash", "hash", "null"}:
            return False
        truth = status.get("truth") or {}
        if truth.get("hash_embedding_is_not_neural_model"):
            return False
        return bool(status.get("production_grade")) and provider_id not in {"", "null"}

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
                    r"cannot|can't|is not|are not|isn't|aren't|was not|weren't|not|"
                    r"niet|nooit|geen)\b",
                    text,
                )
            )

        claim_neg = _negated(claim)
        evidence_neg = _negated(evidence)

        def _core(text: str) -> set[str]:
            cleaned = re.sub(
                r"\b(does not|do not|don't|doesn't|did not|didn't|never|no longer|"
                r"cannot|can't|is not|are not|isn't|aren't|was not|weren't|not|"
                r"niet|nooit|geen)\b",
                " ",
                text,
            )
            return {t for t in cleaned.split() if len(t) > 2}

        claim_core = _core(claim)
        evidence_core = _core(evidence)
        shared = claim_core & evidence_core
        if len(shared) >= 2 and claim_neg != evidence_neg:
            return "negation polarity conflict with shared content"

        claim_nums = re.findall(r"\b\d+(?:\.\d+)?\b", claim)
        evidence_nums = re.findall(r"\b\d+(?:\.\d+)?\b", evidence)
        if claim_nums and evidence_nums and set(claim_nums).isdisjoint(set(evidence_nums)):
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
        if query.layer and query.layer != "any" and hit.layer != query.layer:
            return False
        if query.require_source_valid and not HybridRetriever._source_is_valid(hit):
            return False
        updated = str(
            hit.provenance.get("updated_at")
            or hit.provenance.get("source_mtime")
            or ""
        )
        if query.time_after and updated and updated < query.time_after:
            return False
        if query.time_before and updated and updated > query.time_before:
            return False
        # Temporal validity from trust_metadata.valid_until / valid_from
        trust = hit.provenance.get("trust_metadata") or {}
        valid_until = str(trust.get("valid_until") or "")
        valid_from = str(trust.get("valid_from") or "")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if valid_until and valid_until < now:
            return False
        if valid_from and valid_from > now:
            return False
        return True

    @staticmethod
    def _source_is_valid(hit: RetrievalHit) -> bool:
        trust = hit.provenance.get("trust_metadata") or {}
        if trust.get("valid") is False:
            return False
        if trust.get("revoked") or trust.get("invalid") or trust.get("expired"):
            return False
        if str(trust.get("source_validity") or "").lower() in {"invalid", "revoked", "expired"}:
            return False
        return True

    @staticmethod
    def _row_to_hit(
        row: dict[str, Any],
        *,
        score: float,
        modality: str,
        extra_provenance: dict[str, Any] | None = None,
    ) -> RetrievalHit:
        trust_meta = row.get("trust_metadata")
        if trust_meta is None and row.get("trust_metadata_json"):
            import json

            try:
                trust_meta = json.loads(row["trust_metadata_json"] or "{}")
            except Exception:  # noqa: BLE001
                trust_meta = {}
        provenance = {
            "updated_at": row.get("updated_at"),
            "source_mtime": row.get("source_mtime"),
            "uncertainty_notes": row.get("uncertainty_notes") or "",
            "trust_metadata": trust_meta or {},
        }
        if extra_provenance:
            provenance.update(extra_provenance)
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
            provenance=provenance,
        )
