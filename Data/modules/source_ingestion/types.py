"""Source Ingestion domain types — phases, artifacts, manifests, outcomes."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class IngestionPhase(str, Enum):
    UPLOADING = "uploading"
    STORED = "stored"
    QUEUED = "queued"
    INSPECTING = "inspecting"
    EXPANDING = "expanding"
    CLASSIFYING = "classifying"
    PARSING = "parsing"
    NORMALIZING = "normalizing"
    BRAIN_PENDING = "brain_pending"
    BRAIN_SYNCING = "brain_syncing"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    QUARANTINED = "quarantined"
    SKIPPED = "skipped"


class MemberOutcome(str, Enum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    QUARANTINED = "quarantined"
    FAILED = "failed"
    DUPLICATE = "duplicate"
    ROUTED = "routed"
    PENDING = "pending"
    CANCELLED = "cancelled"


class SourceKind(str, Enum):
    DOCUMENT = "document"
    STRUCTURED = "structured"
    SOURCE_CODE = "source_code"
    PLAIN_TEXT = "plain_text"
    OFFICE = "office"
    DATASET = "dataset"
    IMAGE = "image"
    ARCHIVE = "archive"
    BINARY = "binary"
    UNKNOWN = "unknown"
    SECRET = "secret"


class DetectionConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


PARSER_VERSION = "1.0.0"
CAPABILITY_PROCESS = "source_ingestion.process"
CAPABILITY_BRAIN_RETRY = "source_ingestion.brain_retry"


@dataclass(frozen=True)
class DetectionResult:
    kind: SourceKind
    mime_type: str | None
    extension: str
    confidence: DetectionConfidence
    signals: dict[str, Any] = field(default_factory=dict)
    handler_hint: str | None = None
    is_archive: bool = False
    is_text: bool = False
    is_binary: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "mime_type": self.mime_type,
            "extension": self.extension,
            "confidence": self.confidence.value,
            "signals": dict(self.signals),
            "handler_hint": self.handler_hint,
            "is_archive": self.is_archive,
            "is_text": self.is_text,
            "is_binary": self.is_binary,
        }


@dataclass
class ContentRef:
    """File-backed or in-memory content reference (prefer file-backed for large text)."""

    text: str | None = None
    path: str | None = None
    encoding: str = "utf-8"
    byte_start: int | None = None
    byte_end: int | None = None
    truncated: bool = False

    def read_text(self, *, max_chars: int | None = None) -> str:
        if self.text is not None:
            if max_chars is not None and len(self.text) > max_chars:
                return self.text[:max_chars]
            return self.text
        if not self.path:
            return ""
        from pathlib import Path

        data = Path(self.path).read_text(encoding=self.encoding, errors="replace")
        if max_chars is not None and len(data) > max_chars:
            return data[:max_chars]
        return data

    def public_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "encoding": self.encoding,
            "byte_start": self.byte_start,
            "byte_end": self.byte_end,
            "truncated": self.truncated,
            "has_inline_text": self.text is not None,
            "inline_chars": len(self.text) if self.text is not None else None,
        }


@dataclass
class NormalizedArtifact:
    source_kind: SourceKind
    title: str
    relative_path: str
    mime_type: str | None
    parser: str
    parser_version: str
    content_hash: str
    content: ContentRef
    structured_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    unsupported_features: list[str] = field(default_factory=list)
    outcome: MemberOutcome = MemberOutcome.SUCCESS
    skip_reason: str | None = None
    error_code: str | None = None
    retryable: bool = False
    route_target: str | None = None  # e.g. "dataset"

    def public_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind.value,
            "title": self.title,
            "relative_path": self.relative_path,
            "mime_type": self.mime_type,
            "parser": self.parser,
            "parser_version": self.parser_version,
            "content_hash": self.content_hash,
            "content": self.content.public_dict(),
            "structured_metadata": dict(self.structured_metadata),
            "provenance": dict(self.provenance),
            "warnings": list(self.warnings),
            "unsupported_features": list(self.unsupported_features),
            "outcome": self.outcome.value,
            "skip_reason": self.skip_reason,
            "error_code": self.error_code,
            "retryable": self.retryable,
            "route_target": self.route_target,
        }


@dataclass
class ManifestMember:
    member_id: str
    container_source_id: str
    relative_path: str
    original_filename: str
    size_bytes: int
    compressed_size_bytes: int | None = None
    content_hash: str | None = None
    mime_type: str | None = None
    detected_kind: str | None = None
    detection: dict[str, Any] = field(default_factory=dict)
    outcome: MemberOutcome = MemberOutcome.PENDING
    skip_reason: str | None = None
    error_code: str | None = None
    parse_status: str = "pending"
    brain_status: str = "not_applicable"
    child_source_id: str | None = None
    brain_document_id: str | None = None
    parser: str | None = None
    is_encrypted: bool = False
    is_symlink: bool = False
    is_directory: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "member_id": self.member_id,
            "container_source_id": self.container_source_id,
            "relative_path": self.relative_path,
            "original_filename": self.original_filename,
            "size_bytes": self.size_bytes,
            "compressed_size_bytes": self.compressed_size_bytes,
            "content_hash": self.content_hash,
            "mime_type": self.mime_type,
            "detected_kind": self.detected_kind,
            "detection": dict(self.detection),
            "outcome": self.outcome.value,
            "skip_reason": self.skip_reason,
            "error_code": self.error_code,
            "parse_status": self.parse_status,
            "brain_status": self.brain_status,
            "child_source_id": self.child_source_id,
            "brain_document_id": self.brain_document_id,
            "parser": self.parser,
            "is_encrypted": self.is_encrypted,
            "is_symlink": self.is_symlink,
            "is_directory": self.is_directory,
            "metadata": dict(self.metadata),
        }


@dataclass
class ArchiveManifest:
    container_source_id: str
    archive_type: str
    member_count: int = 0
    directory_count: int = 0
    total_uncompressed_bytes: int = 0
    compressed_bytes: int = 0
    files_ingested: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    files_quarantined: int = 0
    files_duplicate: int = 0
    files_routed: int = 0
    files_pending: int = 0
    brain_synced: int = 0
    brain_failed: int = 0
    project_kind: str | None = None
    languages_detected: list[str] = field(default_factory=list)
    root_files: list[str] = field(default_factory=list)
    manifest_files: list[str] = field(default_factory=list)
    members: list[ManifestMember] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def recompute_aggregates(self) -> None:
        self.member_count = len([m for m in self.members if not m.is_directory])
        self.directory_count = len([m for m in self.members if m.is_directory])
        self.files_ingested = 0
        self.files_skipped = 0
        self.files_failed = 0
        self.files_quarantined = 0
        self.files_duplicate = 0
        self.files_routed = 0
        self.files_pending = 0
        self.brain_synced = 0
        self.brain_failed = 0
        for m in self.members:
            if m.is_directory:
                continue
            if m.outcome == MemberOutcome.SUCCESS:
                self.files_ingested += 1
            elif m.outcome == MemberOutcome.SKIPPED:
                self.files_skipped += 1
            elif m.outcome == MemberOutcome.FAILED:
                self.files_failed += 1
            elif m.outcome == MemberOutcome.QUARANTINED:
                self.files_quarantined += 1
            elif m.outcome == MemberOutcome.DUPLICATE:
                self.files_duplicate += 1
            elif m.outcome == MemberOutcome.ROUTED:
                self.files_routed += 1
            elif m.outcome in {MemberOutcome.PENDING, MemberOutcome.CANCELLED}:
                self.files_pending += 1
            if m.brain_status == "synced":
                self.brain_synced += 1
            elif m.brain_status == "failed":
                self.brain_failed += 1

    def aggregate_phase(self) -> IngestionPhase:
        self.recompute_aggregates()
        if self.files_pending > 0:
            return IngestionPhase.PARSING
        if self.files_failed > 0 or self.files_quarantined > 0:
            if self.files_ingested > 0 or self.files_routed > 0:
                return IngestionPhase.PARTIAL
            return IngestionPhase.FAILED
        if self.files_ingested == 0 and self.files_routed == 0 and self.files_duplicate == 0:
            if self.files_skipped > 0:
                return IngestionPhase.COMPLETED
            return IngestionPhase.FAILED
        return IngestionPhase.COMPLETED

    def public_dict(self, *, include_members: bool = False) -> dict[str, Any]:
        self.recompute_aggregates()
        payload: dict[str, Any] = {
            "container_source_id": self.container_source_id,
            "archive_type": self.archive_type,
            "member_count": self.member_count,
            "directory_count": self.directory_count,
            "total_uncompressed_bytes": self.total_uncompressed_bytes,
            "compressed_bytes": self.compressed_bytes,
            "files_ingested": self.files_ingested,
            "files_skipped": self.files_skipped,
            "files_failed": self.files_failed,
            "files_quarantined": self.files_quarantined,
            "files_duplicate": self.files_duplicate,
            "files_routed": self.files_routed,
            "files_pending": self.files_pending,
            "brain_synced": self.brain_synced,
            "brain_failed": self.brain_failed,
            "project_kind": self.project_kind,
            "languages_detected": list(self.languages_detected),
            "root_files": list(self.root_files),
            "manifest_files": list(self.manifest_files),
            "metadata": dict(self.metadata),
        }
        if include_members:
            payload["members"] = [m.public_dict() for m in self.members]
        return payload


@dataclass
class IngestionProgress:
    source_id: str
    job_id: str | None
    status: IngestionPhase
    phase: IngestionPhase
    progress_pct: float | None
    files_discovered: int
    files_ingested: int
    files_skipped: int
    files_failed: int
    files_pending: int
    files_quarantined: int
    files_duplicate: int
    files_routed: int
    brain_synced: int
    brain_failed: int
    bytes_processed: int
    compressed_bytes: int | None = None
    uncompressed_bytes: int | None = None
    archive_type: str | None = None
    filename: str | None = None
    error: str | None = None
    cancel_requested: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "job_id": self.job_id,
            "status": self.status.value,
            "phase": self.phase.value,
            "progress_pct": self.progress_pct,
            "files_discovered": self.files_discovered,
            "files_ingested": self.files_ingested,
            "files_skipped": self.files_skipped,
            "files_failed": self.files_failed,
            "files_pending": self.files_pending,
            "files_quarantined": self.files_quarantined,
            "files_duplicate": self.files_duplicate,
            "files_routed": self.files_routed,
            "brain_synced": self.brain_synced,
            "brain_failed": self.brain_failed,
            "bytes_processed": self.bytes_processed,
            "compressed_bytes": self.compressed_bytes,
            "uncompressed_bytes": self.uncompressed_bytes,
            "archive_type": self.archive_type,
            "filename": self.filename,
            "error": self.error,
            "cancel_requested": self.cancel_requested,
        }


@dataclass
class IngestionError(Exception):
    code: str
    message: str
    http_status: int = 400
    details: dict[str, Any] = field(default_factory=dict)
    retryable: bool = False

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def public_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
            "retryable": self.retryable,
        }
