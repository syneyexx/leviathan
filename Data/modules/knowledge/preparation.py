"""Pure Knowledge preparation — normalize, chunk, embedding plan (no DB mutation).

Owned by ``knowledge_prepare``. Canonical SQLite COMMIT_WRITE stays in db_commit.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any

from .chunking import chunk_text_spans
from .hashing import content_sha256, estimate_tokens

# Material changes to this constant invalidate chunk hashes / rebuild scope.
NORMALIZATION_VERSION = "1"


def normalize_document_text(text: str) -> str:
    """Deterministic document normalization (provenance-preserving).

    Matches chunking CRLF policy. Does not strip meaningful interior whitespace.
    """
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def stable_chunk_id(document_id: str, chunk_index: int, content_hash: str) -> str:
    """Deterministic chunk identity for the same document version + chunk config."""
    seed = f"knowledge-chunk:{document_id}:{chunk_index}:{content_hash}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


@dataclass(frozen=True)
class PreparedChunk:
    chunk_id: str
    chunk_index: int
    content: str
    content_hash: str
    token_estimate: int
    start_offset: int
    end_offset: int
    confidence: float = 1.0
    uncertainty_notes: str = ""
    source_type: str = "document"
    provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "chunk_index": self.chunk_index,
            "content": self.content,
            "content_hash": self.content_hash,
            "token_estimate": self.token_estimate,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "confidence": self.confidence,
            "uncertainty_notes": self.uncertainty_notes,
            "source_type": self.source_type,
            "provenance": dict(self.provenance),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PreparedDocumentIndex:
    document_id: str
    title: str
    source: str
    expected_content_hash: str
    normalization_version: str
    chunk_max_chars: int
    chunk_overlap: int
    chunks: tuple[PreparedChunk, ...]
    needs_embeddings: bool = False
    embedding_provider_id: str = ""
    embedding_unavailable_reason: str = ""

    def public_dict(self, *, include_content: bool = True) -> dict[str, Any]:
        chunks = [
            c.public_dict() if include_content else {**c.public_dict(), "content": ""}
            for c in self.chunks
        ]
        return {
            "document_id": self.document_id,
            "title": self.title,
            "source": self.source,
            "expected_content_hash": self.expected_content_hash,
            "normalization_version": self.normalization_version,
            "chunk_max_chars": self.chunk_max_chars,
            "chunk_overlap": self.chunk_overlap,
            "chunk_count": len(self.chunks),
            "chunks": chunks,
            "needs_embeddings": self.needs_embeddings,
            "embedding_provider_id": self.embedding_provider_id,
            "embedding_unavailable_reason": self.embedding_unavailable_reason,
        }


def build_chunk_plan(
    *,
    document_id: str,
    title: str,
    content: str,
    source: str = "manual",
    content_hash: str | None = None,
    original_path: str | None = None,
    source_mtime: str | None = None,
    chunk_max_chars: int = 1200,
    chunk_overlap: int = 120,
    source_type: str = "document",
    confidence: float = 1.0,
    uncertainty_notes: str = "",
    needs_embeddings: bool = False,
    embedding_provider_id: str = "",
    embedding_unavailable_reason: str = "",
) -> PreparedDocumentIndex:
    """Compute chunks + hashes without writing SQLite."""
    normalized = normalize_document_text(content)
    digest = content_hash or content_sha256(normalized)
    spans = chunk_text_spans(
        normalized, max_chars=chunk_max_chars, overlap=chunk_overlap
    )
    chunks: list[PreparedChunk] = []
    for index, part in enumerate(spans):
        chash = content_sha256(part.text)
        provenance = {
            "path": original_path,
            "mtime": source_mtime,
            "document_hash": digest,
            "source": source,
            "title": title,
            "normalization_version": NORMALIZATION_VERSION,
        }
        chunks.append(
            PreparedChunk(
                chunk_id=stable_chunk_id(document_id, index, chash),
                chunk_index=index,
                content=part.text,
                content_hash=chash,
                token_estimate=estimate_tokens(part.text),
                start_offset=part.start,
                end_offset=part.end,
                confidence=confidence,
                uncertainty_notes=uncertainty_notes,
                source_type=source_type,
                provenance=provenance,
                metadata={"title": title},
            )
        )
    return PreparedDocumentIndex(
        document_id=document_id,
        title=title,
        source=source,
        expected_content_hash=digest,
        normalization_version=NORMALIZATION_VERSION,
        chunk_max_chars=chunk_max_chars,
        chunk_overlap=chunk_overlap,
        chunks=tuple(chunks),
        needs_embeddings=needs_embeddings,
        embedding_provider_id=embedding_provider_id,
        embedding_unavailable_reason=embedding_unavailable_reason,
    )


def partition_embedding_batches(
    chunks: list[PreparedChunk] | tuple[PreparedChunk, ...],
    *,
    batch_size: int = 64,
) -> list[list[PreparedChunk]]:
    """Fan-out into bounded embedding batches (never one job per chunk)."""
    size = max(1, min(int(batch_size), 500))
    items = list(chunks)
    return [items[i : i + size] for i in range(0, len(items), size)]


def embedding_batch_idempotency_key(
    *,
    document_id: str,
    content_hash: str,
    provider_id: str,
    batch_index: int,
) -> str:
    raw = f"{document_id}:{content_hash}:{provider_id}:{batch_index}"
    return "emb:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
