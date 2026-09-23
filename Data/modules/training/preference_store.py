"""Durable preference record store (Wave 9)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .preference_schema import (
    PreferenceCandidate,
    PreferenceRanking,
    PreferenceRecord,
    _utc_now,
)


class PreferenceStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        # Tables created by migration v32; ensure local test DBs still work.
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS preference_records (
                    preference_id TEXT PRIMARY KEY,
                    prompt TEXT NOT NULL,
                    preferred_id TEXT,
                    rejected_id TEXT,
                    ranking TEXT NOT NULL,
                    rubric TEXT,
                    profile TEXT,
                    annotator TEXT,
                    source TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    candidates_json TEXT NOT NULL,
                    context_json TEXT NOT NULL DEFAULT '{}',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )

    def save(self, record: PreferenceRecord) -> PreferenceRecord:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO preference_records(
                    preference_id, prompt, preferred_id, rejected_id, ranking,
                    rubric, profile, annotator, source, content_hash,
                    candidates_json, context_json, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(preference_id) DO UPDATE SET
                    prompt=excluded.prompt,
                    preferred_id=excluded.preferred_id,
                    rejected_id=excluded.rejected_id,
                    ranking=excluded.ranking,
                    rubric=excluded.rubric,
                    profile=excluded.profile,
                    annotator=excluded.annotator,
                    source=excluded.source,
                    content_hash=excluded.content_hash,
                    candidates_json=excluded.candidates_json,
                    context_json=excluded.context_json,
                    metadata_json=excluded.metadata_json
                """,
                (
                    record.preference_id,
                    record.prompt,
                    record.preferred_id,
                    record.rejected_id,
                    record.ranking.value,
                    record.rubric,
                    record.profile,
                    record.annotator,
                    record.source,
                    record.content_hash,
                    json.dumps([c.public_dict() for c in record.candidates]),
                    json.dumps(record.context),
                    json.dumps(record.metadata),
                    record.created_at or _utc_now(),
                ),
            )
        return record

    def get(self, preference_id: str) -> PreferenceRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM preference_records WHERE preference_id = ?",
                (preference_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def list(self, *, limit: int = 100, source: str | None = None) -> list[PreferenceRecord]:
        with self.connect() as conn:
            if source:
                rows = conn.execute(
                    """
                    SELECT * FROM preference_records
                    WHERE source = ?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (source, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM preference_records
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [self._from_row(r) for r in rows]

    def _from_row(self, row: sqlite3.Row) -> PreferenceRecord:
        candidates_raw = json.loads(row["candidates_json"] or "[]")
        candidates = [
            PreferenceCandidate(
                candidate_id=str(c.get("candidate_id") or ""),
                text=str(c.get("text") or ""),
                rank=c.get("rank"),
                score=c.get("score"),
                metadata=dict(c.get("metadata") or {}),
            )
            for c in candidates_raw
            if isinstance(c, dict)
        ]
        return PreferenceRecord(
            preference_id=row["preference_id"],
            prompt=row["prompt"],
            candidates=candidates,
            preferred_id=row["preferred_id"],
            rejected_id=row["rejected_id"],
            ranking=PreferenceRanking(row["ranking"]),
            rubric=row["rubric"],
            profile=row["profile"],
            annotator=row["annotator"],
            source=row["source"],
            context=json.loads(row["context_json"] or "{}"),
            content_hash=row["content_hash"],
            created_at=row["created_at"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )
