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


class AtlasScale(str, Enum):
    EVENT = "event"
    THREAD = "thread"
    INVESTIGATION = "investigation"
    RECURRING_PATTERN = "recurring-pattern"
    PROJECT = "project"
    DOMAIN = "domain"


@dataclass(frozen=True)
class AtlasRecord:
    """Mutable interpretation layer. Evidence remains immutable."""

    atlas_id: str
    title: str
    summary: str
    scope: str
    scale: AtlasScale
    entities: tuple[str, ...] = ()
    projects: tuple[str, ...] = ()
    relation_types: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    confidence: float = 0.5
    evidence_record_refs: tuple[str, ...] = ()
    parent_atlas_id: str | None = None
    child_atlas_ids: tuple[str, ...] = ()
    last_revised_at: str = ""
    revision_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "atlas_id": self.atlas_id,
            "title": self.title,
            "summary": self.summary,
            "scope": self.scope,
            "scale": self.scale.value,
            "entities": list(self.entities),
            "projects": list(self.projects),
            "relation_types": list(self.relation_types),
            "unresolved_questions": list(self.unresolved_questions),
            "contradictions": list(self.contradictions),
            "confidence": self.confidence,
            "evidence_record_refs": list(self.evidence_record_refs),
            "parent_atlas_id": self.parent_atlas_id,
            "child_atlas_ids": list(self.child_atlas_ids),
            "last_revised_at": self.last_revised_at,
            "revision_reason": self.revision_reason,
            "metadata": self.metadata,
            "layer": "atlas",
            "truth": {
                "atlas_is_mutable_interpretation": True,
                "evidence_is_immutable": True,
                "atlas_is_not_authority": True,
            },
        }


class AtlasStore:
    """Cold Atlas layer over the central LEVIATHAN SQLite database."""

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
            CREATE TABLE IF NOT EXISTS atlas_records (
                atlas_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT '',
                scale TEXT NOT NULL,
                entities_json TEXT NOT NULL DEFAULT '[]',
                projects_json TEXT NOT NULL DEFAULT '[]',
                relation_types_json TEXT NOT NULL DEFAULT '[]',
                unresolved_questions_json TEXT NOT NULL DEFAULT '[]',
                contradictions_json TEXT NOT NULL DEFAULT '[]',
                confidence REAL NOT NULL DEFAULT 0.5,
                evidence_record_refs_json TEXT NOT NULL DEFAULT '[]',
                parent_atlas_id TEXT,
                child_atlas_ids_json TEXT NOT NULL DEFAULT '[]',
                last_revised_at TEXT NOT NULL,
                revision_reason TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_atlas_scale ON atlas_records(scale, last_revised_at)"
        )
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS atlas_fts
                USING fts5(atlas_id UNINDEXED, title, summary, entities, projects)
                """
            )
        except sqlite3.OperationalError:
            pass

    def upsert(self, record: AtlasRecord) -> AtlasRecord:
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO atlas_records(
                    atlas_id, title, summary, scope, scale,
                    entities_json, projects_json, relation_types_json,
                    unresolved_questions_json, contradictions_json, confidence,
                    evidence_record_refs_json, parent_atlas_id, child_atlas_ids_json,
                    last_revised_at, revision_reason, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(atlas_id) DO UPDATE SET
                    title = excluded.title,
                    summary = excluded.summary,
                    scope = excluded.scope,
                    scale = excluded.scale,
                    entities_json = excluded.entities_json,
                    projects_json = excluded.projects_json,
                    relation_types_json = excluded.relation_types_json,
                    unresolved_questions_json = excluded.unresolved_questions_json,
                    contradictions_json = excluded.contradictions_json,
                    confidence = excluded.confidence,
                    evidence_record_refs_json = excluded.evidence_record_refs_json,
                    parent_atlas_id = excluded.parent_atlas_id,
                    child_atlas_ids_json = excluded.child_atlas_ids_json,
                    last_revised_at = excluded.last_revised_at,
                    revision_reason = excluded.revision_reason,
                    metadata_json = excluded.metadata_json
                """,
                (
                    record.atlas_id,
                    record.title,
                    record.summary,
                    record.scope,
                    record.scale.value,
                    json.dumps(list(record.entities)),
                    json.dumps(list(record.projects)),
                    json.dumps(list(record.relation_types)),
                    json.dumps(list(record.unresolved_questions)),
                    json.dumps(list(record.contradictions)),
                    record.confidence,
                    json.dumps(list(record.evidence_record_refs)),
                    record.parent_atlas_id,
                    json.dumps(list(record.child_atlas_ids)),
                    record.last_revised_at or utc_now(),
                    record.revision_reason,
                    json.dumps(record.metadata),
                ),
            )
            self._upsert_fts(conn, record)
        return record

    def create(
        self,
        *,
        title: str,
        summary: str,
        scale: AtlasScale | str = AtlasScale.THREAD,
        scope: str = "",
        entities: list[str] | None = None,
        projects: list[str] | None = None,
        relation_types: list[str] | None = None,
        unresolved_questions: list[str] | None = None,
        contradictions: list[str] | None = None,
        confidence: float = 0.5,
        evidence_record_refs: list[str] | None = None,
        parent_atlas_id: str | None = None,
        revision_reason: str = "created",
        metadata: dict[str, Any] | None = None,
        atlas_id: str | None = None,
    ) -> AtlasRecord:
        if isinstance(scale, str):
            scale = AtlasScale(scale)
        record = AtlasRecord(
            atlas_id=atlas_id or str(uuid.uuid4()),
            title=title.strip(),
            summary=summary.strip(),
            scope=scope,
            scale=scale,
            entities=tuple(entities or ()),
            projects=tuple(projects or ()),
            relation_types=tuple(relation_types or ()),
            unresolved_questions=tuple(unresolved_questions or ()),
            contradictions=tuple(contradictions or ()),
            confidence=max(0.0, min(1.0, float(confidence))),
            evidence_record_refs=tuple(evidence_record_refs or ()),
            parent_atlas_id=parent_atlas_id,
            child_atlas_ids=(),
            last_revised_at=utc_now(),
            revision_reason=revision_reason,
            metadata=metadata or {},
        )
        return self.upsert(record)

    def revise(
        self,
        atlas_id: str,
        *,
        summary: str | None = None,
        title: str | None = None,
        unresolved_questions: list[str] | None = None,
        contradictions: list[str] | None = None,
        confidence: float | None = None,
        evidence_record_refs: list[str] | None = None,
        revision_reason: str = "revised",
    ) -> AtlasRecord | None:
        """Revise atlas interpretation without rewriting evidence records."""
        existing = self.get(atlas_id)
        if existing is None:
            return None
        revised = AtlasRecord(
            atlas_id=existing.atlas_id,
            title=title if title is not None else existing.title,
            summary=summary if summary is not None else existing.summary,
            scope=existing.scope,
            scale=existing.scale,
            entities=existing.entities,
            projects=existing.projects,
            relation_types=existing.relation_types,
            unresolved_questions=(
                tuple(unresolved_questions)
                if unresolved_questions is not None
                else existing.unresolved_questions
            ),
            contradictions=(
                tuple(contradictions) if contradictions is not None else existing.contradictions
            ),
            confidence=(
                max(0.0, min(1.0, float(confidence)))
                if confidence is not None
                else existing.confidence
            ),
            evidence_record_refs=(
                tuple(evidence_record_refs)
                if evidence_record_refs is not None
                else existing.evidence_record_refs
            ),
            parent_atlas_id=existing.parent_atlas_id,
            child_atlas_ids=existing.child_atlas_ids,
            last_revised_at=utc_now(),
            revision_reason=revision_reason,
            metadata=existing.metadata,
        )
        return self.upsert(revised)

    def get(self, atlas_id: str) -> AtlasRecord | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM atlas_records WHERE atlas_id = ?",
                (atlas_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        entity: str | None = None,
        project: str | None = None,
        unresolved_only: bool = False,
        contradiction_only: bool = False,
        min_confidence: float | None = None,
    ) -> list[AtlasRecord]:
        q = query.strip()
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows: list[sqlite3.Row] = []
            if q:
                try:
                    rows = conn.execute(
                        """
                        SELECT a.* FROM atlas_fts f
                        JOIN atlas_records a ON a.atlas_id = f.atlas_id
                        WHERE atlas_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?
                        """,
                        (q, max(1, min(limit * 3, 100))),
                    ).fetchall()
                except sqlite3.OperationalError:
                    like = f"%{q}%"
                    rows = conn.execute(
                        """
                        SELECT * FROM atlas_records
                        WHERE title LIKE ? OR summary LIKE ?
                        ORDER BY last_revised_at DESC
                        LIMIT ?
                        """,
                        (like, like, max(1, min(limit * 3, 100))),
                    ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM atlas_records ORDER BY last_revised_at DESC LIMIT ?",
                    (max(1, min(limit * 3, 100)),),
                ).fetchall()

        results: list[AtlasRecord] = []
        for row in rows:
            record = self._from_row(row)
            if entity and entity.lower() not in {e.lower() for e in record.entities}:
                continue
            if project and project.lower() not in {p.lower() for p in record.projects}:
                continue
            if unresolved_only and not record.unresolved_questions:
                continue
            if contradiction_only and not record.contradictions:
                continue
            if min_confidence is not None and record.confidence < min_confidence:
                continue
            results.append(record)
            if len(results) >= limit:
                break
        return results

    def _upsert_fts(self, conn: sqlite3.Connection, record: AtlasRecord) -> None:
        try:
            conn.execute("DELETE FROM atlas_fts WHERE atlas_id = ?", (record.atlas_id,))
            conn.execute(
                "INSERT INTO atlas_fts(atlas_id, title, summary, entities, projects) VALUES (?, ?, ?, ?, ?)",
                (
                    record.atlas_id,
                    record.title,
                    record.summary,
                    " ".join(record.entities),
                    " ".join(record.projects),
                ),
            )
        except sqlite3.OperationalError:
            pass

    @staticmethod
    def _from_row(row: sqlite3.Row) -> AtlasRecord:
        return AtlasRecord(
            atlas_id=row["atlas_id"],
            title=row["title"],
            summary=row["summary"],
            scope=row["scope"] or "",
            scale=AtlasScale(row["scale"]),
            entities=tuple(json.loads(row["entities_json"] or "[]")),
            projects=tuple(json.loads(row["projects_json"] or "[]")),
            relation_types=tuple(json.loads(row["relation_types_json"] or "[]")),
            unresolved_questions=tuple(json.loads(row["unresolved_questions_json"] or "[]")),
            contradictions=tuple(json.loads(row["contradictions_json"] or "[]")),
            confidence=float(row["confidence"]),
            evidence_record_refs=tuple(json.loads(row["evidence_record_refs_json"] or "[]")),
            parent_atlas_id=row["parent_atlas_id"],
            child_atlas_ids=tuple(json.loads(row["child_atlas_ids_json"] or "[]")),
            last_revised_at=row["last_revised_at"],
            revision_reason=row["revision_reason"] or "",
            metadata=json.loads(row["metadata_json"] or "{}"),
        )
