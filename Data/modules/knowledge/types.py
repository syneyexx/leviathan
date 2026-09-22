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


class RelationClass(str, Enum):
    LIKE = "like"
    UNLIKE = "unlike"
    UNKNOWN = "unknown"
    CONTRADICTION = "contradiction"


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
    start_offset: int = 0
    end_offset: int = 0
    confidence: float = 1.0
    uncertainty_notes: str = ""
    source_type: str = "document"
    provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "content": self.content,
            "content_hash": self.content_hash,
            "token_estimate": self.token_estimate,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "confidence": self.confidence,
            "uncertainty_notes": self.uncertainty_notes,
            "source_type": self.source_type,
            "provenance": self.provenance,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class DirectionalRelationAtom:
    atom_id: str
    subject_ref: str
    object_ref: str
    relation_class: RelationClass
    comparison_vector: list[float] = field(default_factory=list)
    supporting_evidence_refs: tuple[str, ...] = ()
    document_id: str | None = None
    chunk_id: str | None = None
    confidence: float = 0.5
    notes: str = ""
    created_at: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "atom_id": self.atom_id,
            "subject_ref": self.subject_ref,
            "object_ref": self.object_ref,
            "relation_class": self.relation_class.value,
            "comparison_vector": list(self.comparison_vector),
            "supporting_evidence_refs": list(self.supporting_evidence_refs),
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "confidence": self.confidence,
            "notes": self.notes,
            "created_at": self.created_at,
            "truth": {
                "relation_atom_is_not_authority": True,
                "model_output_is_not_evidence": True,
            },
        }


@dataclass(frozen=True)
class TextSpan:
    text: str
    start: int
    end: int
