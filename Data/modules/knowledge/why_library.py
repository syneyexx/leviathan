from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class WhyBucket(str, Enum):
    WHY_BELONGS_TO_PARENT = "why_belongs_to_parent"
    WHY_NOT_CHILD = "why_not_child"
    SUPERFICIAL_RESEMBLANCE = "superficial_resemblance"
    RESIDUE = "residue"


@dataclass(frozen=True)
class WhyRecord:
    why_id: str
    observation: str
    bucket: WhyBucket
    parent_ref: str | None
    child_ref: str | None
    comparison: str
    evidence_refs: tuple[str, ...] = ()
    residue: str = ""
    confidence: float = 0.5
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "why_id": self.why_id,
            "observation": self.observation,
            "bucket": self.bucket.value,
            "parent_ref": self.parent_ref,
            "child_ref": self.child_ref,
            "comparison": self.comparison,
            "evidence_refs": list(self.evidence_refs),
            "residue": self.residue,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "truth": {
                "why_is_advisory": True,
                "parent_inheritance_requires_evidence": True,
                "model_output_is_not_evidence": True,
            },
        }

    def as_context_item(self) -> dict[str, Any]:
        return {
            "id": self.why_id,
            "content": (
                f"[why/{self.bucket.value}] {self.observation} — {self.comparison}"
                + (f" residue={self.residue}" if self.residue else "")
            ),
            "kind": "why",
            "status": "advisory",
        }


class WhyLibrary:
    """Lightweight semantic assimilation: observation → comparison → why buckets."""

    def __init__(self, db_path: Path, *, enabled: bool = False) -> None:
        self.db_path = db_path
        self.enabled = enabled
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS why_records (
                    why_id TEXT PRIMARY KEY,
                    observation TEXT NOT NULL,
                    bucket TEXT NOT NULL,
                    parent_ref TEXT,
                    child_ref TEXT,
                    comparison TEXT NOT NULL,
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    residue TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_why_bucket ON why_records(bucket, created_at)"
            )

    def assimilate(
        self,
        *,
        observation: str,
        parent_ref: str | None = None,
        child_ref: str | None = None,
        evidence_refs: list[str] | tuple[str, ...] | None = None,
        resemblance_notes: str = "",
        residue: str = "",
        exclude_child: bool = False,
        confidence: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> WhyRecord | None:
        if not self.enabled:
            return None
        text = observation.strip()
        if not text:
            raise ValueError("Why observation cannot be empty")
        refs = tuple(evidence_refs or ())
        # Parent inheritance only when evidence-supported.
        if parent_ref and not refs:
            bucket = WhyBucket.SUPERFICIAL_RESEMBLANCE
            comparison = resemblance_notes or (
                f"Parent {parent_ref} resemblance noted without supporting evidence — not inherited"
            )
        elif exclude_child and child_ref:
            bucket = WhyBucket.WHY_NOT_CHILD
            comparison = resemblance_notes or f"Explicitly excluded from child {child_ref}"
        elif parent_ref and refs:
            bucket = WhyBucket.WHY_BELONGS_TO_PARENT
            comparison = resemblance_notes or (
                f"Belongs under parent {parent_ref} with evidence {', '.join(refs)}"
            )
        elif residue or resemblance_notes:
            bucket = WhyBucket.RESIDUE if residue else WhyBucket.SUPERFICIAL_RESEMBLANCE
            comparison = resemblance_notes or "Residue preserved without forced taxonomy"
        else:
            bucket = WhyBucket.RESIDUE
            comparison = "Unclassified observation retained as residue"

        record = WhyRecord(
            why_id=str(uuid.uuid4()),
            observation=text,
            bucket=bucket,
            parent_ref=parent_ref,
            child_ref=child_ref,
            comparison=comparison,
            evidence_refs=refs,
            residue=residue,
            confidence=max(0.0, min(1.0, float(confidence))),
            created_at=utc_now(),
            metadata=metadata or {},
        )
        self.initialize()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO why_records(
                    why_id, observation, bucket, parent_ref, child_ref, comparison,
                    evidence_refs_json, residue, confidence, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.why_id,
                    record.observation,
                    record.bucket.value,
                    record.parent_ref,
                    record.child_ref,
                    record.comparison,
                    json.dumps(list(record.evidence_refs)),
                    record.residue,
                    record.confidence,
                    record.created_at,
                    json.dumps(record.metadata),
                ),
            )
        return record

    def search(self, query: str, *, limit: int = 10) -> list[WhyRecord]:
        if not self.enabled:
            return []
        self.initialize()
        like = f"%{query.strip()}%"
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM why_records
                WHERE observation LIKE ? OR comparison LIKE ? OR residue LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (like, like, like, max(1, min(limit, 100))),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_recent(self, *, limit: int = 20) -> list[WhyRecord]:
        if not self.enabled:
            return []
        self.initialize()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM why_records ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> WhyRecord:
        return WhyRecord(
            why_id=row["why_id"],
            observation=row["observation"],
            bucket=WhyBucket(row["bucket"]),
            parent_ref=row["parent_ref"],
            child_ref=row["child_ref"],
            comparison=row["comparison"],
            evidence_refs=tuple(json.loads(row["evidence_refs_json"] or "[]")),
            residue=row["residue"] or "",
            confidence=float(row["confidence"]),
            created_at=row["created_at"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )
