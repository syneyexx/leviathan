from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class IngestStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    PARSING = "PARSING"
    INDEXING = "INDEXING"
    READY = "READY"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"
    DELETED = "DELETED"


@dataclass(frozen=True)
class DocumentRecord:
    document_id: str
    title: str
    content: str
    source: str
    status: IngestStatus
    content_hash: str
    original_path: str | None
    source_mtime: str | None
    size_bytes: int | None
    parser: str
    parser_version: str
    ingest_version: int
    trust_metadata: dict[str, Any]
    created_at: str
    updated_at: str
    error: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.document_id,
            "title": self.title,
            "content": self.content,
            "source": self.source,
            "status": self.status.value,
            "content_hash": self.content_hash,
            "original_path": self.original_path,
            "source_mtime": self.source_mtime,
            "size_bytes": self.size_bytes,
            "parser": self.parser,
            "parser_version": self.parser_version,
            "ingest_version": self.ingest_version,
            "trust_metadata": self.trust_metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
        }

    def legacy_dict(self) -> dict[str, Any]:
        """Step-1 compatible shape used by chat/context."""
        return {
            "id": self.document_id,
            "title": self.title,
            "content": self.content,
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    document_id: str
    chunk_index: int
    content: str
    content_hash: str
    token_estimate: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "content": self.content,
            "content_hash": self.content_hash,
            "token_estimate": self.token_estimate,
            "metadata": self.metadata,
        }
