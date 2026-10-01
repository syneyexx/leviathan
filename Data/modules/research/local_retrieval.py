"""Local research retrieval via shared KnowledgeStore / HybridRetriever."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from Data.modules.knowledge import HybridRetriever, RetrievalHit, RetrievalQuery, reciprocal_rank_fusion
from Data.modules.knowledge.retrieval import RRF_K


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class KnowledgeSearcher(Protocol):
    def search(self, query: RetrievalQuery) -> list[RetrievalHit]: ...


@dataclass(frozen=True)
class LocalHit:
    document_id: str
    chunk_id: str
    chunk_index: int
    title: str
    source: str
    content: str
    score: float
    modality: str
    original_path: str | None
    document_hash: str | None
    chunk_hash: str
    query: str
    retrieved_at: str
    retrieval_mode: str = "lexical"
    embedding_is_semantic: bool | None = None
    scope: str | None = None

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
            "query": self.query,
            "retrieved_at": self.retrieved_at,
            "retrieval_mode": self.retrieval_mode,
            "embedding_is_semantic": self.embedding_is_semantic,
            "scope": self.scope,
            "location": {
                "document_id": self.document_id,
                "chunk_id": self.chunk_id,
                "chunk_index": self.chunk_index,
            },
        }


@dataclass
class LocalRetrievalTelemetry:
    """Honest retrieval mode / fusion telemetry for Research callers."""

    mode: str
    embedding_is_semantic: bool | None
    use_embeddings: bool
    scopes_searched: int
    per_scope_candidate_limit: int
    fusion: str
    candidate_count: int
    selected_count: int
    truth: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "embedding_is_semantic": self.embedding_is_semantic,
            "use_embeddings": self.use_embeddings,
            "scopes_searched": self.scopes_searched,
            "per_scope_candidate_limit": self.per_scope_candidate_limit,
            "fusion": self.fusion,
            "candidate_count": self.candidate_count,
            "selected_count": self.selected_count,
            "truth": dict(self.truth),
        }


class LocalResearchRetriever:
    """Offline research path — works without web providers.

    P1-013: use hybrid/embeddings when the Knowledge embedding provider is
    semantic; otherwise fall back to lexical and say so in telemetry.

    P1-014: fair multi-scope merge — bounded per-scope candidates, then
    RRF/dedupe into the global limit so the first scope cannot starve later
    datasets.
    """

    def __init__(self, retriever: KnowledgeSearcher | None) -> None:
        self.retriever = retriever
        self.last_telemetry: LocalRetrievalTelemetry | None = None

    @property
    def available(self) -> bool:
        return self.retriever is not None

    def _resolve_mode(self) -> tuple[bool, str, bool | None]:
        """Return ``(use_embeddings, mode_label, embedding_is_semantic)``."""
        if self.retriever is None:
            return False, "unavailable", None
        embedding_is_semantic: bool | None = None
        available = False
        embeddings = getattr(self.retriever, "embeddings", None)
        # HybridRetriever may be constructed without wiring the store provider —
        # fall back to KnowledgeStore.embedding_provider when present.
        if embeddings is None or (
            getattr(embeddings, "provider_id", "") in {"null", ""}
            and not (hasattr(embeddings, "available") and embeddings.available())
        ):
            store = getattr(self.retriever, "store", None)
            store_provider = getattr(store, "embedding_provider", None)
            if store_provider is not None:
                embeddings = store_provider
        if embeddings is not None:
            try:
                available = bool(embeddings.available()) if hasattr(embeddings, "available") else False
            except Exception:  # noqa: BLE001
                available = False
            try:
                if hasattr(embeddings, "is_semantic"):
                    embedding_is_semantic = bool(getattr(embeddings, "is_semantic"))
                elif hasattr(self.retriever, "_embedding_is_semantic") and embeddings is getattr(
                    self.retriever, "embeddings", None
                ):
                    embedding_is_semantic = bool(self.retriever._embedding_is_semantic())  # noqa: SLF001
                else:
                    status = embeddings.status() if hasattr(embeddings, "status") else {}
                    embedding_is_semantic = bool((status or {}).get("is_semantic"))
            except Exception:  # noqa: BLE001
                embedding_is_semantic = False
        if available and embedding_is_semantic:
            return True, "hybrid", True
        if available and embedding_is_semantic is False:
            # Hash / non-semantic vectors must not be labeled as semantic hybrid.
            return False, "lexical_fallback", False
        return False, "lexical", embedding_is_semantic

    def search(
        self,
        query: str,
        *,
        limit: int = 8,
        source: str | None = None,
        local_scopes: list[str] | None = None,
        per_scope_candidate_limit: int | None = None,
        rrf_k: int = RRF_K,
    ) -> list[LocalHit]:
        if self.retriever is None:
            self.last_telemetry = LocalRetrievalTelemetry(
                mode="unavailable",
                embedding_is_semantic=None,
                use_embeddings=False,
                scopes_searched=0,
                per_scope_candidate_limit=0,
                fusion="none",
                candidate_count=0,
                selected_count=0,
                truth={"local_retriever_unavailable": True},
            )
            return []
        text = (query or "").strip()
        if not text:
            self.last_telemetry = LocalRetrievalTelemetry(
                mode="empty_query",
                embedding_is_semantic=None,
                use_embeddings=False,
                scopes_searched=0,
                per_scope_candidate_limit=0,
                fusion="none",
                candidate_count=0,
                selected_count=0,
                truth={"empty_query": True},
            )
            return []
        now = utc_now()
        use_embeddings, mode_label, embedding_is_semantic = self._resolve_mode()
        # Ensure HybridRetriever uses the store provider when semantic hybrid is selected
        # but the retriever was constructed with a null embedding provider.
        if use_embeddings:
            current = getattr(self.retriever, "embeddings", None)
            store = getattr(self.retriever, "store", None)
            store_provider = getattr(store, "embedding_provider", None)
            if (
                store_provider is not None
                and current is not None
                and not (hasattr(current, "available") and current.available())
            ):
                try:
                    self.retriever.embeddings = store_provider
                except Exception:  # noqa: BLE001
                    pass

        # Scopes map to KnowledgeStore `source` filter when provided.
        scopes: list[str | None]
        if source:
            scopes = [source]
        else:
            scopes = [s for s in (local_scopes or []) if s]
        if not scopes:
            scopes = [None]

        global_limit = max(1, int(limit))
        # Bound per-scope candidates so later scopes always get a fair slot.
        if per_scope_candidate_limit is not None:
            per_scope = max(1, int(per_scope_candidate_limit))
        else:
            per_scope = max(global_limit, max(1, (global_limit + len(scopes) - 1) // len(scopes)) * 2)
            per_scope = min(max(per_scope, global_limit), max(global_limit * 4, 16))

        ranked_lists: list[list[str]] = []
        by_chunk: dict[str, LocalHit] = {}
        scope_of_chunk: dict[str, str | None] = {}

        for scope in scopes:
            raw = self.retriever.search(
                RetrievalQuery(
                    text=text,
                    limit=per_scope,
                    source=scope,
                    use_embeddings=use_embeddings,
                )
            )
            order: list[str] = []
            for hit in raw:
                if hit.chunk_id in order:
                    continue
                order.append(hit.chunk_id)
                if hit.chunk_id not in by_chunk:
                    by_chunk[hit.chunk_id] = LocalHit(
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
                        query=text,
                        retrieved_at=now,
                        retrieval_mode=mode_label,
                        embedding_is_semantic=embedding_is_semantic,
                        scope=scope,
                    )
                    scope_of_chunk[hit.chunk_id] = scope
            if order:
                ranked_lists.append(order)

        fusion = "none"
        if not ranked_lists:
            selected_ids: list[str] = []
        elif len(ranked_lists) == 1:
            selected_ids = ranked_lists[0][:global_limit]
            fusion = "single_scope"
        else:
            fused = reciprocal_rank_fusion(ranked_lists, k=rrf_k)
            selected_ids = [
                chunk_id
                for chunk_id, _score in sorted(
                    fused.items(), key=lambda item: (-item[1], item[0])
                )
            ][:global_limit]
            fusion = "rrf_multi_scope"
            # Re-score selected hits with fused RRF values for honest ranking.
            for chunk_id in selected_ids:
                base = by_chunk[chunk_id]
                by_chunk[chunk_id] = LocalHit(
                    document_id=base.document_id,
                    chunk_id=base.chunk_id,
                    chunk_index=base.chunk_index,
                    title=base.title,
                    source=base.source,
                    content=base.content,
                    score=round(float(fused[chunk_id]), 6),
                    modality=base.modality,
                    original_path=base.original_path,
                    document_hash=base.document_hash,
                    chunk_hash=base.chunk_hash,
                    query=base.query,
                    retrieved_at=base.retrieved_at,
                    retrieval_mode=mode_label,
                    embedding_is_semantic=embedding_is_semantic,
                    scope=scope_of_chunk.get(chunk_id, base.scope),
                )

        hits = [by_chunk[cid] for cid in selected_ids if cid in by_chunk]
        self.last_telemetry = LocalRetrievalTelemetry(
            mode=mode_label,
            embedding_is_semantic=embedding_is_semantic,
            use_embeddings=use_embeddings,
            scopes_searched=len(scopes),
            per_scope_candidate_limit=per_scope,
            fusion=fusion,
            candidate_count=len(by_chunk),
            selected_count=len(hits),
            truth={
                "hybrid_requires_semantic_embeddings": True,
                "hash_embeddings_are_lexical_fallback": embedding_is_semantic is False,
                "multi_scope_uses_bounded_rrf": len(scopes) > 1,
                "first_scope_cannot_starve_later_scopes": True,
            },
        )
        return hits


def build_default_local_retriever(knowledge_store) -> LocalResearchRetriever:
    if knowledge_store is None:
        return LocalResearchRetriever(None)
    provider = getattr(knowledge_store, "embedding_provider", None)
    return LocalResearchRetriever(HybridRetriever(knowledge_store, embeddings=provider))
