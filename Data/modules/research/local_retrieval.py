"""Local research retrieval via shared KnowledgeStore / HybridRetriever."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from Data.modules.knowledge import HybridRetriever, RetrievalHit, RetrievalQuery


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
            "location": {
                "document_id": self.document_id,
                "chunk_id": self.chunk_id,
                "chunk_index": self.chunk_index,
            },
        }


class LocalResearchRetriever:
    """Offline research path — works without web providers."""

    def __init__(self, retriever: KnowledgeSearcher | None) -> None:
        self.retriever = retriever

    @property
    def available(self) -> bool:
        return self.retriever is not None

    def search(
        self,
        query: str,
        *,
        limit: int = 8,
        source: str | None = None,
        local_scopes: list[str] | None = None,
    ) -> list[LocalHit]:
        if self.retriever is None:
            return []
        text = (query or "").strip()
        if not text:
            return []
        now = utc_now()
        # Scopes map to KnowledgeStore `source` filter when provided.
        scopes = [s for s in (local_scopes or []) if s]
        if source:
            scopes = [source]
        if not scopes:
            scopes = [None]  # type: ignore[list-item]

        seen: set[str] = set()
        hits: list[LocalHit] = []
        per_scope = max(1, limit)
        for scope in scopes:
            raw = self.retriever.search(
                RetrievalQuery(text=text, limit=per_scope, source=scope, use_embeddings=False)
            )
            for hit in raw:
                if hit.chunk_id in seen:
                    continue
                seen.add(hit.chunk_id)
                hits.append(
                    LocalHit(
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
                    )
                )
                if len(hits) >= limit:
                    return hits
        return hits


def build_default_local_retriever(knowledge_store) -> LocalResearchRetriever:
    if knowledge_store is None:
        return LocalResearchRetriever(None)
    return LocalResearchRetriever(HybridRetriever(knowledge_store))
