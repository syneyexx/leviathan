from __future__ import annotations

from typing import Protocol


class EmbeddingProvider(Protocol):
    """Interface for vector embeddings.

    Implementations may be added later. Knowledge V2 must not fabricate vectors.
    """

    provider_id: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...

    def available(self) -> bool:
        ...


class NullEmbeddingProvider:
    """Explicit no-embedding provider — hybrid retrieval falls back to lexical only."""

    provider_id = "null"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("NullEmbeddingProvider cannot embed documents")

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("NullEmbeddingProvider cannot embed queries")

    def available(self) -> bool:
        return False
