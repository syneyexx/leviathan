"""Dataset domain types — durable records and status enums."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class DatasetStatus(str, Enum):
    CREATED = "created"
    IMPORTING = "importing"
    RAW = "raw"
    MATERIALIZING = "materializing"
    READY = "ready"
    FAILED = "failed"
    ARCHIVED = "archived"


class VersionStatus(str, Enum):
    PENDING = "pending"
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class VersionKind(str, Enum):
    RAW = "raw"
    MATERIALIZED = "materialized"
    TRANSFORMED = "transformed"
    SPLIT = "split"
    EXPORT = "export"


class SourceType(str, Enum):
    LOCAL = "local"
    HUGGINGFACE = "huggingface"
    UPLOAD = "upload"
    DERIVED = "derived"


class DetectedFormat(str, Enum):
    JSONL = "jsonl"
    JSON = "json"
    CSV = "csv"
    TSV = "tsv"
    TXT = "txt"
    MD = "md"
    PARQUET = "parquet"
    UNKNOWN = "unknown"


class DatasetJobType(str, Enum):
    IMPORT_LOCAL = "import_local"
    IMPORT_HF = "import_hf"
    MATERIALIZE = "materialize"
    VALIDATE = "validate"
    DEDUPE = "dedupe"
    TRANSFORM = "transform"
    SPLIT = "split"
    TOKENIZE_STATS = "tokenize_stats"
    EXPORT = "export"
    INDEX = "index"
    DUPLICATE = "duplicate"
    SHARD_INGEST = "shard_ingest"
    CONTAMINATION_SCAN = "contamination_scan"


class DatasetJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class IndexStatus(str, Enum):
    PENDING = "pending"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


CANONICAL_SCHEMA_VERSION = 1


@dataclass
class CanonicalRecord:
    """Normalized training/knowledge row.

    Required: ``id`` and at least one of ``text`` or ``messages``.
    """

    id: str
    text: str = ""
    messages: list[dict[str, Any]] | None = None
    labels: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    split: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "text": self.text, "metadata": dict(self.metadata)}
        if self.messages is not None:
            out["messages"] = self.messages
        if self.labels is not None:
            out["labels"] = self.labels
        if self.split is not None:
            out["split"] = self.split
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CanonicalRecord":
        return cls(
            id=str(data.get("id") or ""),
            text=str(data.get("text") or ""),
            messages=data.get("messages") if isinstance(data.get("messages"), list) else None,
            labels=data.get("labels") if isinstance(data.get("labels"), dict) else None,
            metadata=dict(data.get("metadata") or {}) if isinstance(data.get("metadata"), dict) else {},
            split=str(data["split"]) if data.get("split") is not None else None,
        )


@dataclass
class FormatDetection:
    format: DetectedFormat
    confidence: float
    details: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "format": self.format.value,
            "confidence": self.confidence,
            "details": self.details,
        }


@dataclass
class DatasetRecord:
    dataset_id: str
    name: str
    source_type: SourceType
    status: DatasetStatus
    created_at: str
    updated_at: str
    description: str = ""
    original_filename: str | None = None
    original_uri: str | None = None
    license: str | None = None
    schema_version: int = CANONICAL_SCHEMA_VERSION
    content_hash: str | None = None
    byte_size: int | None = None
    row_count: int | None = None
    detected_format: DetectedFormat | None = None
    format_confidence: float | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_path: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "datasetId": self.dataset_id,
            "name": self.name,
            "sourceType": self.source_type.value,
            "status": self.status.value,
            "description": self.description,
            "originalFilename": self.original_filename,
            "originalUri": self.original_uri,
            "license": self.license,
            "schemaVersion": self.schema_version,
            "contentHash": self.content_hash,
            "byteSize": self.byte_size,
            "rowCount": self.row_count,
            "detectedFormat": self.detected_format.value if self.detected_format else None,
            "formatConfidence": self.format_confidence,
            "provenance": self.provenance,
            "metadata": self.metadata,
            "rawPath": self.raw_path,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass
class DatasetVersion:
    version_id: str
    dataset_id: str
    version_label: str
    status: VersionStatus
    kind: VersionKind
    created_at: str
    updated_at: str
    parent_version_id: str | None = None
    schema: dict[str, Any] = field(default_factory=dict)
    row_count: int | None = None
    byte_size: int | None = None
    content_hash: str | None = None
    storage_path: str | None = None
    split: dict[str, Any] = field(default_factory=dict)
    transform_lineage: list[dict[str, Any]] = field(default_factory=list)
    token_stats: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "versionId": self.version_id,
            "datasetId": self.dataset_id,
            "versionLabel": self.version_label,
            "parentVersionId": self.parent_version_id,
            "status": self.status.value,
            "kind": self.kind.value,
            "schema": self.schema,
            "rowCount": self.row_count,
            "byteSize": self.byte_size,
            "contentHash": self.content_hash,
            "storagePath": self.storage_path,
            "split": self.split,
            "transformLineage": self.transform_lineage,
            "tokenStats": self.token_stats,
            "validation": self.validation,
            "metadata": self.metadata,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass
class DatasetFile:
    file_id: str
    dataset_id: str
    role: str
    path: str
    content_hash: str
    byte_size: int
    created_at: str
    version_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "fileId": self.file_id,
            "datasetId": self.dataset_id,
            "versionId": self.version_id,
            "role": self.role,
            "path": self.path,
            "contentHash": self.content_hash,
            "byteSize": self.byte_size,
            "metadata": self.metadata,
            "createdAt": self.created_at,
        }


@dataclass
class DatasetJob:
    job_id: str
    job_type: DatasetJobType
    status: DatasetJobStatus
    created_at: str
    updated_at: str
    dataset_id: str | None = None
    version_id: str | None = None
    phase: str | None = None
    progress: float | None = None
    cancel_requested: bool = False
    worker_pid: int | None = None
    checkpoint: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    log_path: str | None = None
    trace_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "jobId": self.job_id,
            "datasetId": self.dataset_id,
            "versionId": self.version_id,
            "jobType": self.job_type.value,
            "status": self.status.value,
            "phase": self.phase,
            "progress": self.progress,
            "cancelRequested": self.cancel_requested,
            "workerPid": self.worker_pid,
            "checkpoint": self.checkpoint,
            "config": self.config,
            "result": self.result,
            "error": self.error,
            "logPath": self.log_path,
            "traceId": self.trace_id,
            "createdAt": self.created_at,
            "startedAt": self.started_at,
            "updatedAt": self.updated_at,
            "finishedAt": self.finished_at,
        }


@dataclass
class DatasetIndex:
    index_id: str
    dataset_id: str
    version_id: str
    status: IndexStatus
    created_at: str
    updated_at: str
    chunk_count: int | None = None
    embedding_model: str | None = None
    index_version: int = 1
    knowledge_scope: str | None = None
    storage_path: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "indexId": self.index_id,
            "datasetId": self.dataset_id,
            "versionId": self.version_id,
            "status": self.status.value,
            "chunkCount": self.chunk_count,
            "embeddingModel": self.embedding_model,
            "indexVersion": self.index_version,
            "knowledgeScope": self.knowledge_scope,
            "storagePath": self.storage_path,
            "provenance": self.provenance,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


class DatasetError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "dataset_error",
        http_status: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status
        self.details = dict(details or {})

    def public_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            out["details"] = self.details
        return out
