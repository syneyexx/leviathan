from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .types import EvidenceKind, EvidenceRecord, EvidenceStatus


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class EvidenceStore:
    """Durable evidence records separate from observations and model output."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
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
            self._ensure_schema(conn)

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS evidence (
                evidence_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                claim TEXT NOT NULL,
                created_at TEXT NOT NULL,
                verified_at TEXT,
                observation_id TEXT,
                artifact_id TEXT,
                run_id TEXT,
                job_id TEXT,
                content_hash TEXT,
                path TEXT,
                error TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_evidence_status ON evidence(status, created_at)"
        )

    def create(
        self,
        *,
        kind: EvidenceKind,
        claim: str,
        status: EvidenceStatus = EvidenceStatus.UNVERIFIED,
        observation_id: str | None = None,
        artifact_id: str | None = None,
        run_id: str | None = None,
        job_id: str | None = None,
        content_hash: str | None = None,
        path: str | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
        evidence_id: str | None = None,
    ) -> EvidenceRecord:
        now = utc_now()
        record = EvidenceRecord(
            evidence_id=evidence_id or str(uuid.uuid4()),
            kind=kind,
            status=status,
            claim=claim,
            created_at=now,
            verified_at=now if status == EvidenceStatus.VERIFIED else None,
            observation_id=observation_id,
            artifact_id=artifact_id,
            run_id=run_id,
            job_id=job_id,
            content_hash=content_hash,
            path=path,
            error=error,
            metadata=metadata or {},
        )
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO evidence(
                    evidence_id, kind, status, claim, created_at, verified_at,
                    observation_id, artifact_id, run_id, job_id, content_hash, path,
                    error, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.evidence_id,
                    record.kind.value,
                    record.status.value,
                    record.claim,
                    record.created_at,
                    record.verified_at,
                    record.observation_id,
                    record.artifact_id,
                    record.run_id,
                    record.job_id,
                    record.content_hash,
                    record.path,
                    record.error,
                    json.dumps(record.metadata),
                ),
            )
        return record

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM evidence WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def list(
        self,
        *,
        status: EvidenceStatus | None = None,
        run_id: str | None = None,
        limit: int = 100,
    ) -> list[EvidenceRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 500)))
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                f"SELECT * FROM evidence {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def set_status(
        self,
        evidence_id: str,
        status: EvidenceStatus,
        *,
        error: str | None = None,
        content_hash: str | None = None,
    ) -> EvidenceRecord | None:
        now = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM evidence WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone()
            if row is None:
                return None
            verified_at = now if status == EvidenceStatus.VERIFIED else row["verified_at"]
            conn.execute(
                """
                UPDATE evidence
                SET status = ?, verified_at = ?, error = COALESCE(?, error),
                    content_hash = COALESCE(?, content_hash)
                WHERE evidence_id = ?
                """,
                (status.value, verified_at, error, content_hash, evidence_id),
            )
            row = conn.execute(
                "SELECT * FROM evidence WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    @staticmethod
    def _from_row(row: sqlite3.Row) -> EvidenceRecord:
        return EvidenceRecord(
            evidence_id=row["evidence_id"],
            kind=EvidenceKind(row["kind"]),
            status=EvidenceStatus(row["status"]),
            claim=row["claim"],
            created_at=row["created_at"],
            verified_at=row["verified_at"],
            observation_id=row["observation_id"],
            artifact_id=row["artifact_id"],
            run_id=row["run_id"],
            job_id=row["job_id"],
            content_hash=row["content_hash"],
            path=row["path"],
            error=row["error"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )
