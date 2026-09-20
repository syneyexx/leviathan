from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .embeddings import EmbeddingProvider, NullEmbeddingProvider
from .store import KnowledgeStore
from .types import IngestStatus


@dataclass(frozen=True)
class RetrievalQuery:
    text: str
    limit: int = 5
    source: str | None = None
    status: IngestStatus = IngestStatus.READY
    use_embeddings: bool = True


@dataclass(frozen=True)
class RetrievalHit:
    document_id: str
    chunk_id: str
    chunk_index: int
    title: str
    source: str
    content: str
    score: float
    modality: str  # lexical | vector | hybrid
    original_path: str | None
    document_hash: str | None
    chunk_hash: str

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
        }


class HybridRetriever:
    """Lexical + optional vector retrieval.

    Vector path is only used when EmbeddingProvider.available() is true.
    Null/unavailable providers produce lexical-only results — never fabricated vectors.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        embeddings: EmbeddingProvider | None = None,
    ) -> None:
        self.store = store
        self.embeddings = embeddings or NullEmbeddingProvider()

    def search(self, query: RetrievalQuery) -> list[RetrievalHit]:
        lexical_rows = self.store.search_lexical(
            query.text,
            limit=query.limit,
            source=query.source,
            status=query.status,
        )
        hits: list[RetrievalHit] = []
        for row in lexical_rows:
            # bm25: lower is better in SQLite — invert for a descending score.
            rank = float(row.get("rank") or 0.0)
            score = 1.0 / (1.0 + max(rank, 0.0))
            hits.append(
                RetrievalHit(
                    document_id=row["document_id"],
                    chunk_id=row["chunk_id"],
                    chunk_index=int(row["chunk_index"]),
                    title=row["title"],
                    source=row["source"],
                    content=row["chunk_content"],
                    score=score,
                    modality="lexical",
                    original_path=row.get("original_path"),
                    document_hash=row.get("document_hash"),
                    chunk_hash=row["chunk_hash"],
                )
            )

        if query.use_embeddings and self.embeddings.available():
            # Future: fuse vector scores with lexical hits.
            # Provider must be real; do not invent similarity here.
            _ = self.embeddings.embed_query(query.text)

        return hits
