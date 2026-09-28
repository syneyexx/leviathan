from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from Data.modules.common.hashing import sha256_file as sha256_file

from .types import ArtifactRecord

# Small control-plane payloads only. Larger artifacts must be file-backed.
MAX_INLINE_ARTIFACT_BYTES = 8 * 1024 * 1024
# Hash verification above this stays off the API process unless a worker calls it.
LARGE_VERIFY_INLINE_BYTES = 64 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _copy_stream(source: Path, dest: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as src, dest.open("wb") as out:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            out.write(chunk)
            size += len(chunk)
        out.flush()
        os.fsync(out.fileno())
    return digest.hexdigest(), size


def _safe_basename(filename: str) -> str:
    if not filename or "/" in filename or "\\" in filename or filename in {".", ".."}:
        raise ValueError("filename must be a plain basename")
    name = Path(filename).name
    if name != filename:
        raise ValueError("filename must be a plain basename")
    return name


class ArtifactStore:
    """Metadata in SQLite; content on disk under a configured artifacts root."""

    def __init__(self, db_path: Path, artifacts_root: Path) -> None:
        self.db_path = db_path
        self.artifacts_root = artifacts_root
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        from Data.modules.common.sqlite_policy import open_sqlite_connection

        conn = open_sqlite_connection(self.db_path, set_wal=False)
        try:
            yield conn
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            conn.close()


    def initialize(self) -> None:
        from Data.modules.common.sqlite_policy import ensure_wal

        with self.connect() as conn:
            ensure_wal(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    run_id TEXT,
                    job_id TEXT,
                    artifact_type TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE,
                    content_hash TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    producer TEXT NOT NULL,
                    verification_status TEXT NOT NULL DEFAULT 'unverified',
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )

    def create_from_bytes(
        self,
        *,
        data: bytes,
        artifact_type: str,
        producer: str,
        filename: str,
        run_id: str | None = None,
        job_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        overwrite: bool = False,
    ) -> ArtifactRecord:
        _safe_basename(filename)
        if len(data) > MAX_INLINE_ARTIFACT_BYTES:
            raise ValueError(
                f"create_from_bytes refuses {len(data)} bytes "
                f"(limit {MAX_INLINE_ARTIFACT_BYTES}); use create_from_file or adopt_staged_file"
            )
        artifact_id = str(uuid.uuid4())
        rel_dir = artifact_id[:2]
        dest_dir = self.artifacts_root / rel_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{artifact_id}_{filename}"
        if dest.exists() and not overwrite:
            raise FileExistsError(f"Artifact path already exists: {dest}")
        digest = sha256_bytes(data)
        dest.write_bytes(data)
        from Data.modules.observability.redaction import redact_payload

        safe_meta = redact_payload(dict(metadata or {}))
        record = ArtifactRecord(
            artifact_id=artifact_id,
            run_id=run_id,
            job_id=job_id,
            artifact_type=artifact_type,
            path=str(dest),
            content_hash=digest,
            size_bytes=len(data),
            created_at=utc_now(),
            producer=producer,
            verification_status="unverified",
            metadata=safe_meta,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO artifacts(
                    artifact_id, run_id, job_id, artifact_type, path, content_hash,
                    size_bytes, created_at, producer, verification_status, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.artifact_id,
                    record.run_id,
                    record.job_id,
                    record.artifact_type,
                    record.path,
                    record.content_hash,
                    record.size_bytes,
                    record.created_at,
                    record.producer,
                    record.verification_status,
                    json.dumps(record.metadata),
                ),
            )
        return record

    def create_from_file(
        self,
        *,
        source: Path | str,
        artifact_type: str,
        producer: str,
        filename: str | None = None,
        run_id: str | None = None,
        job_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        overwrite: bool = False,
    ) -> ArtifactRecord:
        """Copy ``source`` into immutable artifact storage. Source is left in place.

        Bytes are streamed. The caller does not pass the artifact body.
        """
        return self._ingest_file(
            source=Path(source),
            artifact_type=artifact_type,
            producer=producer,
            filename=filename,
            run_id=run_id,
            job_id=job_id,
            metadata=metadata,
            overwrite=overwrite,
            adopt=False,
        )

    def adopt_staged_file(
        self,
        *,
        source: Path | str,
        artifact_type: str,
        producer: str,
        filename: str | None = None,
        run_id: str | None = None,
        job_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        overwrite: bool = False,
    ) -> ArtifactRecord:
        """Take ownership of a staged file (rename into artifact storage).

        The staged path is consumed. This is not an external reference.
        """
        return self._ingest_file(
            source=Path(source),
            artifact_type=artifact_type,
            producer=producer,
            filename=filename,
            run_id=run_id,
            job_id=job_id,
            metadata=metadata,
            overwrite=overwrite,
            adopt=True,
        )

    def _ingest_file(
        self,
        *,
        source: Path,
        artifact_type: str,
        producer: str,
        filename: str | None,
        run_id: str | None,
        job_id: str | None,
        metadata: dict[str, Any] | None,
        overwrite: bool,
        adopt: bool,
    ) -> ArtifactRecord:
        if not source.is_file():
            raise FileNotFoundError(str(source))
        if source.is_symlink():
            raise ValueError("artifact source must not be a symlink")
        plain = _safe_basename(filename or source.name)
        artifact_id = str(uuid.uuid4())
        dest_dir = self.artifacts_root / artifact_id[:2]
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{artifact_id}_{plain}"
        if dest.exists() and not overwrite:
            raise FileExistsError(f"Artifact path already exists: {dest}")
        staging = dest.with_name(dest.name + ".partial")
        try:
            if adopt:
                digest = sha256_file(source)
                size = source.stat().st_size
                os.replace(source, dest)
            else:
                digest, size = _copy_stream(source, staging)
                os.replace(staging, dest)
        except Exception:
            staging.unlink(missing_ok=True)
            if dest.exists() and not overwrite:
                dest.unlink(missing_ok=True)
            raise
        from Data.modules.observability.redaction import redact_payload

        safe_meta = redact_payload(dict(metadata or {}))
        safe_meta["ingest"] = "adopt" if adopt else "copy"
        record = ArtifactRecord(
            artifact_id=artifact_id,
            run_id=run_id,
            job_id=job_id,
            artifact_type=artifact_type,
            path=str(dest),
            content_hash=digest,
            size_bytes=size,
            created_at=utc_now(),
            producer=producer,
            verification_status="unverified",
            metadata=safe_meta,
        )
        self._insert(record)
        return record

    def _insert(self, record: ArtifactRecord) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO artifacts(
                    artifact_id, run_id, job_id, artifact_type, path, content_hash,
                    size_bytes, created_at, producer, verification_status, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.artifact_id,
                    record.run_id,
                    record.job_id,
                    record.artifact_type,
                    record.path,
                    record.content_hash,
                    record.size_bytes,
                    record.created_at,
                    record.producer,
                    record.verification_status,
                    json.dumps(record.metadata),
                ),
            )

    def get(self, artifact_id: str) -> ArtifactRecord | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
        if not row:
            return None
        return ArtifactRecord(
            artifact_id=row["artifact_id"],
            run_id=row["run_id"],
            job_id=row["job_id"],
            artifact_type=row["artifact_type"],
            path=row["path"],
            content_hash=row["content_hash"],
            size_bytes=row["size_bytes"],
            created_at=row["created_at"],
            producer=row["producer"],
            verification_status=row["verification_status"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    def verify_hash(self, artifact_id: str, *, allow_large: bool = False) -> bool:
        record = self.get(artifact_id)
        if not record:
            raise KeyError(artifact_id)
        path = Path(record.path)
        size = path.stat().st_size if path.is_file() else int(record.size_bytes or 0)
        if size > LARGE_VERIFY_INLINE_BYTES and not allow_large:
            from Data.modules.execution.workload import running_in_worker_process

            if not running_in_worker_process():
                raise ValueError(
                    "large artifact hash verification is EXTERNAL_REQUIRED "
                    "(generic file_io owner is not available on this build)"
                )
        ok = sha256_file(path) == record.content_hash
        status = "verified" if ok else "hash_mismatch"
        with self.connect() as conn:
            conn.execute(
                "UPDATE artifacts SET verification_status = ? WHERE artifact_id = ?",
                (status, artifact_id),
            )
        return ok
