from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .types import ArtifactRecord


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ArtifactStore:
    """Metadata in SQLite; content on disk under a configured artifacts root."""

    def __init__(self, db_path: Path, artifacts_root: Path) -> None:
        self.db_path = db_path
        self.artifacts_root = artifacts_root
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
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
        if not filename or "/" in filename or "\\" in filename or filename in {".", ".."}:
            raise ValueError("filename must be a plain basename")
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

    def verify_hash(self, artifact_id: str) -> bool:
        record = self.get(artifact_id)
        if not record:
            raise KeyError(artifact_id)
        data = Path(record.path).read_bytes()
        ok = sha256_bytes(data) == record.content_hash
        status = "verified" if ok else "hash_mismatch"
        with self.connect() as conn:
            conn.execute(
                "UPDATE artifacts SET verification_status = ? WHERE artifact_id = ?",
                (status, artifact_id),
            )
        return ok
