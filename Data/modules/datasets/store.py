"""SQLite persistence for datasets / versions / files / jobs / indexes."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .types import (
    DatasetFile,
    DatasetIndex,
    DatasetJob,
    DatasetJobStatus,
    DatasetJobType,
    DatasetRecord,
    DatasetStatus,
    DatasetVersion,
    DetectedFormat,
    IndexStatus,
    SourceType,
    VersionKind,
    VersionStatus,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


class DatasetStore:
    """Owns dataset tables in the central LEVIATHAN database — no parallel DB."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        """Ensure migration v14 tables exist (idempotent CREATE IF NOT EXISTS)."""
        from Data.backend.migrations import MigrationRunner

        MigrationRunner(self.db_path).apply_all()

    # --- Datasets ---

    def create_dataset(
        self,
        *,
        name: str,
        source_type: SourceType,
        description: str = "",
        original_filename: str | None = None,
        original_uri: str | None = None,
        license: str | None = None,
        provenance: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        dataset_id: str | None = None,
        status: DatasetStatus = DatasetStatus.CREATED,
    ) -> DatasetRecord:
        now = utc_now()
        record = DatasetRecord(
            dataset_id=dataset_id or str(uuid.uuid4()),
            name=name.strip() or "untitled",
            source_type=source_type,
            status=status,
            description=description or "",
            original_filename=original_filename,
            original_uri=original_uri,
            license=license,
            provenance=dict(provenance or {}),
            metadata=dict(metadata or {}),
            created_at=now,
            updated_at=now,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO datasets(
                    dataset_id, name, source_type, status, description,
                    original_filename, original_uri, license, schema_version,
                    content_hash, byte_size, row_count, detected_format,
                    format_confidence, provenance_json, metadata_json, raw_path,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.dataset_id,
                    record.name,
                    record.source_type.value,
                    record.status.value,
                    record.description,
                    record.original_filename,
                    record.original_uri,
                    record.license,
                    record.schema_version,
                    record.content_hash,
                    record.byte_size,
                    record.row_count,
                    None,
                    None,
                    json.dumps(record.provenance),
                    json.dumps(record.metadata),
                    record.raw_path,
                    record.created_at,
                    record.updated_at,
                ),
            )
        return record

    def get_dataset(self, dataset_id: str) -> DatasetRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM datasets WHERE dataset_id = ?", (dataset_id,)
            ).fetchone()
        return self._dataset_from_row(row) if row else None

    def list_datasets(self, *, limit: int = 100) -> list[DatasetRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM datasets ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [self._dataset_from_row(r) for r in rows]

    def update_dataset(self, dataset_id: str, **fields: Any) -> DatasetRecord:
        allowed = {
            "name",
            "status",
            "description",
            "original_filename",
            "original_uri",
            "license",
            "content_hash",
            "byte_size",
            "row_count",
            "detected_format",
            "format_confidence",
            "provenance",
            "metadata",
            "raw_path",
            "schema_version",
        }
        updates: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            col = {
                "provenance": "provenance_json",
                "metadata": "metadata_json",
                "detected_format": "detected_format",
            }.get(key, key)
            if key in {"provenance", "metadata"}:
                values.append(json.dumps(value or {}))
            elif key == "status" and isinstance(value, DatasetStatus):
                values.append(value.value)
            elif key == "detected_format" and isinstance(value, DetectedFormat):
                values.append(value.value)
            elif key == "detected_format" and value is None:
                values.append(None)
            else:
                values.append(value)
            updates.append(f"{col} = ?")
        if not updates:
            existing = self.get_dataset(dataset_id)
            if existing is None:
                raise KeyError(dataset_id)
            return existing
        now = utc_now()
        updates.append("updated_at = ?")
        values.append(now)
        values.append(dataset_id)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE datasets SET {', '.join(updates)} WHERE dataset_id = ?",
                values,
            )
            row = conn.execute(
                "SELECT * FROM datasets WHERE dataset_id = ?", (dataset_id,)
            ).fetchone()
        if row is None:
            raise KeyError(dataset_id)
        return self._dataset_from_row(row)

    def delete_dataset(self, dataset_id: str) -> bool:
        with self.connect() as conn:
            conn.execute("DELETE FROM dataset_indexes WHERE dataset_id = ?", (dataset_id,))
            conn.execute("DELETE FROM dataset_files WHERE dataset_id = ?", (dataset_id,))
            conn.execute("DELETE FROM dataset_versions WHERE dataset_id = ?", (dataset_id,))
            conn.execute(
                "UPDATE dataset_jobs SET dataset_id = NULL WHERE dataset_id = ?",
                (dataset_id,),
            )
            cur = conn.execute("DELETE FROM datasets WHERE dataset_id = ?", (dataset_id,))
            return cur.rowcount > 0

    # --- Versions ---

    def create_version(
        self,
        *,
        dataset_id: str,
        version_label: str,
        kind: VersionKind,
        parent_version_id: str | None = None,
        status: VersionStatus = VersionStatus.PENDING,
        schema: dict[str, Any] | None = None,
        storage_path: str | None = None,
        metadata: dict[str, Any] | None = None,
        transform_lineage: list[dict[str, Any]] | None = None,
        version_id: str | None = None,
    ) -> DatasetVersion:
        now = utc_now()
        record = DatasetVersion(
            version_id=version_id or str(uuid.uuid4()),
            dataset_id=dataset_id,
            version_label=version_label,
            parent_version_id=parent_version_id,
            status=status,
            kind=kind,
            schema=dict(schema or {"version": 1, "type": "canonical"}),
            storage_path=storage_path,
            metadata=dict(metadata or {}),
            transform_lineage=list(transform_lineage or []),
            created_at=now,
            updated_at=now,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO dataset_versions(
                    version_id, dataset_id, version_label, parent_version_id,
                    status, kind, schema_json, row_count, byte_size, content_hash,
                    storage_path, split_json, transform_lineage_json,
                    token_stats_json, validation_json, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.version_id,
                    record.dataset_id,
                    record.version_label,
                    record.parent_version_id,
                    record.status.value,
                    record.kind.value,
                    json.dumps(record.schema),
                    record.row_count,
                    record.byte_size,
                    record.content_hash,
                    record.storage_path,
                    json.dumps(record.split),
                    json.dumps(record.transform_lineage),
                    json.dumps(record.token_stats),
                    json.dumps(record.validation),
                    json.dumps(record.metadata),
                    record.created_at,
                    record.updated_at,
                ),
            )
        return record

    def get_version(self, version_id: str) -> DatasetVersion | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM dataset_versions WHERE version_id = ?", (version_id,)
            ).fetchone()
        return self._version_from_row(row) if row else None

    def list_versions(self, dataset_id: str) -> list[DatasetVersion]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM dataset_versions
                WHERE dataset_id = ?
                ORDER BY created_at DESC
                """,
                (dataset_id,),
            ).fetchall()
        return [self._version_from_row(r) for r in rows]

    def update_version(self, version_id: str, **fields: Any) -> DatasetVersion:
        colmap = {
            "status": "status",
            "kind": "kind",
            "schema": "schema_json",
            "row_count": "row_count",
            "byte_size": "byte_size",
            "content_hash": "content_hash",
            "storage_path": "storage_path",
            "split": "split_json",
            "transform_lineage": "transform_lineage_json",
            "token_stats": "token_stats_json",
            "validation": "validation_json",
            "metadata": "metadata_json",
            "version_label": "version_label",
            "parent_version_id": "parent_version_id",
        }
        updates: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            if key not in colmap:
                continue
            col = colmap[key]
            if key in {"schema", "split", "transform_lineage", "token_stats", "validation", "metadata"}:
                values.append(json.dumps(value if value is not None else ({} if key != "transform_lineage" else [])))
            elif key == "status" and isinstance(value, VersionStatus):
                values.append(value.value)
            elif key == "kind" and isinstance(value, VersionKind):
                values.append(value.value)
            else:
                values.append(value)
            updates.append(f"{col} = ?")
        if not updates:
            existing = self.get_version(version_id)
            if existing is None:
                raise KeyError(version_id)
            return existing
        now = utc_now()
        updates.append("updated_at = ?")
        values.append(now)
        values.append(version_id)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE dataset_versions SET {', '.join(updates)} WHERE version_id = ?",
                values,
            )
            row = conn.execute(
                "SELECT * FROM dataset_versions WHERE version_id = ?", (version_id,)
            ).fetchone()
        if row is None:
            raise KeyError(version_id)
        return self._version_from_row(row)

    # --- Files ---

    def add_file(
        self,
        *,
        dataset_id: str,
        role: str,
        path: str,
        content_hash: str,
        byte_size: int,
        version_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        file_id: str | None = None,
    ) -> DatasetFile:
        now = utc_now()
        record = DatasetFile(
            file_id=file_id or str(uuid.uuid4()),
            dataset_id=dataset_id,
            version_id=version_id,
            role=role,
            path=path,
            content_hash=content_hash,
            byte_size=byte_size,
            metadata=dict(metadata or {}),
            created_at=now,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO dataset_files(
                    file_id, dataset_id, version_id, role, path,
                    content_hash, byte_size, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.file_id,
                    record.dataset_id,
                    record.version_id,
                    record.role,
                    record.path,
                    record.content_hash,
                    record.byte_size,
                    record.created_at,
                    json.dumps(record.metadata),
                ),
            )
        return record

    def list_files(self, dataset_id: str, *, version_id: str | None = None) -> list[DatasetFile]:
        with self.connect() as conn:
            if version_id:
                rows = conn.execute(
                    """
                    SELECT * FROM dataset_files
                    WHERE dataset_id = ? AND version_id = ?
                    ORDER BY created_at ASC
                    """,
                    (dataset_id, version_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM dataset_files
                    WHERE dataset_id = ?
                    ORDER BY created_at ASC
                    """,
                    (dataset_id,),
                ).fetchall()
        return [self._file_from_row(r) for r in rows]

    # --- Jobs ---

    def create_job(
        self,
        *,
        job_type: DatasetJobType,
        dataset_id: str | None = None,
        version_id: str | None = None,
        config: dict[str, Any] | None = None,
        trace_id: str | None = None,
        log_path: str | None = None,
        job_id: str | None = None,
        status: DatasetJobStatus = DatasetJobStatus.QUEUED,
    ) -> DatasetJob:
        now = utc_now()
        record = DatasetJob(
            job_id=job_id or str(uuid.uuid4()),
            dataset_id=dataset_id,
            version_id=version_id,
            job_type=job_type,
            status=status,
            config=dict(config or {}),
            trace_id=trace_id,
            log_path=log_path,
            created_at=now,
            updated_at=now,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO dataset_jobs(
                    job_id, dataset_id, version_id, job_type, status, phase,
                    progress, cancel_requested, worker_pid, checkpoint_json,
                    config_json, result_json, error, log_path, trace_id,
                    created_at, started_at, updated_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.job_id,
                    record.dataset_id,
                    record.version_id,
                    record.job_type.value,
                    record.status.value,
                    record.phase,
                    record.progress,
                    1 if record.cancel_requested else 0,
                    record.worker_pid,
                    json.dumps(record.checkpoint),
                    json.dumps(record.config),
                    json.dumps(record.result),
                    record.error,
                    record.log_path,
                    record.trace_id,
                    record.created_at,
                    record.started_at,
                    record.updated_at,
                    record.finished_at,
                ),
            )
        return record

    def get_job(self, job_id: str) -> DatasetJob | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM dataset_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._job_from_row(row) if row else None

    def list_jobs(
        self,
        *,
        dataset_id: str | None = None,
        status: DatasetJobStatus | None = None,
        limit: int = 100,
    ) -> list[DatasetJob]:
        clauses: list[str] = []
        params: list[Any] = []
        if dataset_id:
            clauses.append("dataset_id = ?")
            params.append(dataset_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 500)))
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM dataset_jobs {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._job_from_row(r) for r in rows]

    def update_job(self, job_id: str, **fields: Any) -> DatasetJob:
        colmap = {
            "status": "status",
            "phase": "phase",
            "progress": "progress",
            "cancel_requested": "cancel_requested",
            "worker_pid": "worker_pid",
            "checkpoint": "checkpoint_json",
            "config": "config_json",
            "result": "result_json",
            "error": "error",
            "log_path": "log_path",
            "trace_id": "trace_id",
            "started_at": "started_at",
            "finished_at": "finished_at",
            "dataset_id": "dataset_id",
            "version_id": "version_id",
        }
        updates: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            if key not in colmap:
                continue
            col = colmap[key]
            if key in {"checkpoint", "config", "result"}:
                values.append(json.dumps(value or {}))
            elif key == "status" and isinstance(value, DatasetJobStatus):
                values.append(value.value)
            elif key == "cancel_requested":
                values.append(1 if value else 0)
            else:
                values.append(value)
            updates.append(f"{col} = ?")
        now = utc_now()
        updates.append("updated_at = ?")
        values.append(now)
        values.append(job_id)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE dataset_jobs SET {', '.join(updates)} WHERE job_id = ?",
                values,
            )
            row = conn.execute(
                "SELECT * FROM dataset_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return self._job_from_row(row)

    def request_cancel(self, job_id: str) -> DatasetJob:
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.status in {
            DatasetJobStatus.COMPLETED,
            DatasetJobStatus.FAILED,
            DatasetJobStatus.CANCELLED,
        }:
            return job
        if job.status == DatasetJobStatus.QUEUED:
            return self.update_job(
                job_id,
                status=DatasetJobStatus.CANCELLED,
                cancel_requested=True,
                finished_at=utc_now(),
                error="cancelled before start",
            )
        return self.update_job(job_id, cancel_requested=True)

    def claim_next_queued(self) -> DatasetJob | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM dataset_jobs
                WHERE status = ? AND cancel_requested = 0
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (DatasetJobStatus.QUEUED.value,),
            ).fetchone()
            if row is None:
                return None
            now = utc_now()
            conn.execute(
                """
                UPDATE dataset_jobs
                SET status = ?, started_at = ?, updated_at = ?, worker_pid = ?
                WHERE job_id = ? AND status = ?
                """,
                (
                    DatasetJobStatus.RUNNING.value,
                    now,
                    now,
                    None,
                    row["job_id"],
                    DatasetJobStatus.QUEUED.value,
                ),
            )
            if conn.execute("SELECT changes()").fetchone()[0] == 0:
                return None
            row = conn.execute(
                "SELECT * FROM dataset_jobs WHERE job_id = ?", (row["job_id"],)
            ).fetchone()
        return self._job_from_row(row) if row else None

    def list_running_jobs(self) -> list[DatasetJob]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM dataset_jobs WHERE status = ?",
                (DatasetJobStatus.RUNNING.value,),
            ).fetchall()
        return [self._job_from_row(r) for r in rows]

    # --- Indexes ---

    def create_index(
        self,
        *,
        dataset_id: str,
        version_id: str,
        knowledge_scope: str | None = None,
        embedding_model: str | None = None,
        storage_path: str | None = None,
        provenance: dict[str, Any] | None = None,
        status: IndexStatus = IndexStatus.PENDING,
        index_id: str | None = None,
    ) -> DatasetIndex:
        now = utc_now()
        record = DatasetIndex(
            index_id=index_id or str(uuid.uuid4()),
            dataset_id=dataset_id,
            version_id=version_id,
            status=status,
            knowledge_scope=knowledge_scope,
            embedding_model=embedding_model,
            storage_path=storage_path,
            provenance=dict(provenance or {}),
            created_at=now,
            updated_at=now,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO dataset_indexes(
                    index_id, dataset_id, version_id, status, chunk_count,
                    embedding_model, index_version, knowledge_scope, storage_path,
                    provenance_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.index_id,
                    record.dataset_id,
                    record.version_id,
                    record.status.value,
                    record.chunk_count,
                    record.embedding_model,
                    record.index_version,
                    record.knowledge_scope,
                    record.storage_path,
                    json.dumps(record.provenance),
                    record.created_at,
                    record.updated_at,
                ),
            )
        return record

    def get_index(self, index_id: str) -> DatasetIndex | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM dataset_indexes WHERE index_id = ?", (index_id,)
            ).fetchone()
        return self._index_from_row(row) if row else None

    def list_indexes(self, dataset_id: str) -> list[DatasetIndex]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM dataset_indexes
                WHERE dataset_id = ?
                ORDER BY created_at DESC
                """,
                (dataset_id,),
            ).fetchall()
        return [self._index_from_row(r) for r in rows]

    def update_index(self, index_id: str, **fields: Any) -> DatasetIndex:
        colmap = {
            "status": "status",
            "chunk_count": "chunk_count",
            "embedding_model": "embedding_model",
            "index_version": "index_version",
            "knowledge_scope": "knowledge_scope",
            "storage_path": "storage_path",
            "provenance": "provenance_json",
        }
        updates: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            if key not in colmap:
                continue
            col = colmap[key]
            if key == "provenance":
                values.append(json.dumps(value or {}))
            elif key == "status" and isinstance(value, IndexStatus):
                values.append(value.value)
            else:
                values.append(value)
            updates.append(f"{col} = ?")
        now = utc_now()
        updates.append("updated_at = ?")
        values.append(now)
        values.append(index_id)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE dataset_indexes SET {', '.join(updates)} WHERE index_id = ?",
                values,
            )
            row = conn.execute(
                "SELECT * FROM dataset_indexes WHERE index_id = ?", (index_id,)
            ).fetchone()
        if row is None:
            raise KeyError(index_id)
        return self._index_from_row(row)

    # --- Row mappers ---

    def _dataset_from_row(self, row: sqlite3.Row) -> DatasetRecord:
        fmt = row["detected_format"]
        return DatasetRecord(
            dataset_id=row["dataset_id"],
            name=row["name"],
            source_type=SourceType(row["source_type"]),
            status=DatasetStatus(row["status"]),
            description=row["description"] or "",
            original_filename=row["original_filename"],
            original_uri=row["original_uri"],
            license=row["license"],
            schema_version=int(row["schema_version"] or 1),
            content_hash=row["content_hash"],
            byte_size=row["byte_size"],
            row_count=row["row_count"],
            detected_format=DetectedFormat(fmt) if fmt else None,
            format_confidence=row["format_confidence"],
            provenance=_loads(row["provenance_json"], {}),
            metadata=_loads(row["metadata_json"], {}),
            raw_path=row["raw_path"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _version_from_row(self, row: sqlite3.Row) -> DatasetVersion:
        return DatasetVersion(
            version_id=row["version_id"],
            dataset_id=row["dataset_id"],
            version_label=row["version_label"],
            parent_version_id=row["parent_version_id"],
            status=VersionStatus(row["status"]),
            kind=VersionKind(row["kind"]),
            schema=_loads(row["schema_json"], {}),
            row_count=row["row_count"],
            byte_size=row["byte_size"],
            content_hash=row["content_hash"],
            storage_path=row["storage_path"],
            split=_loads(row["split_json"], {}),
            transform_lineage=_loads(row["transform_lineage_json"], []),
            token_stats=_loads(row["token_stats_json"], {}),
            validation=_loads(row["validation_json"], {}),
            metadata=_loads(row["metadata_json"], {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _file_from_row(self, row: sqlite3.Row) -> DatasetFile:
        return DatasetFile(
            file_id=row["file_id"],
            dataset_id=row["dataset_id"],
            version_id=row["version_id"],
            role=row["role"],
            path=row["path"],
            content_hash=row["content_hash"],
            byte_size=int(row["byte_size"]),
            metadata=_loads(row["metadata_json"], {}),
            created_at=row["created_at"],
        )

    def _job_from_row(self, row: sqlite3.Row) -> DatasetJob:
        return DatasetJob(
            job_id=row["job_id"],
            dataset_id=row["dataset_id"],
            version_id=row["version_id"],
            job_type=DatasetJobType(row["job_type"]),
            status=DatasetJobStatus(row["status"]),
            phase=row["phase"],
            progress=row["progress"],
            cancel_requested=bool(row["cancel_requested"]),
            worker_pid=row["worker_pid"],
            checkpoint=_loads(row["checkpoint_json"], {}),
            config=_loads(row["config_json"], {}),
            result=_loads(row["result_json"], {}),
            error=row["error"],
            log_path=row["log_path"],
            trace_id=row["trace_id"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            updated_at=row["updated_at"],
            finished_at=row["finished_at"],
        )

    def _index_from_row(self, row: sqlite3.Row) -> DatasetIndex:
        return DatasetIndex(
            index_id=row["index_id"],
            dataset_id=row["dataset_id"],
            version_id=row["version_id"],
            status=IndexStatus(row["status"]),
            chunk_count=row["chunk_count"],
            embedding_model=row["embedding_model"],
            index_version=int(row["index_version"] or 1),
            knowledge_scope=row["knowledge_scope"],
            storage_path=row["storage_path"],
            provenance=_loads(row["provenance_json"], {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
