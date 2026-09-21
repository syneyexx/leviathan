from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .types import MemoryKind, MemoryRecord, MemoryStatus


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MemoryStore:
    """Durable controlled memory, separate from Knowledge."""

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
            CREATE TABLE IF NOT EXISTS memory_entries (
                memory_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                source TEXT NOT NULL,
                trust TEXT NOT NULL,
                run_id TEXT,
                conversation_id TEXT,
                tags_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_status ON memory_entries(status, updated_at)"
        )
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
                USING fts5(memory_id UNINDEXED, content, tags)
                """
            )
        except sqlite3.OperationalError:
            pass

    def create(
        self,
        *,
        content: str,
        kind: MemoryKind = MemoryKind.NOTE,
        source: str = "manual",
        trust: str = "explicit",
        run_id: str | None = None,
        conversation_id: str | None = None,
        tags: list[str] | tuple[str, ...] | None = None,
        metadata: dict[str, Any] | None = None,
        memory_id: str | None = None,
    ) -> MemoryRecord:
        text = content.strip()
        if not text:
            raise ValueError("Memory content cannot be empty")
        if trust == "model_output":
            raise ValueError(
                "Refusing to store raw model_output as memory trust; "
                "use explicit/imported/derived with human or policy authority"
            )
        now = utc_now()
        record = MemoryRecord(
            memory_id=memory_id or str(uuid.uuid4()),
            kind=kind,
            status=MemoryStatus.ACTIVE,
            content=text,
            created_at=now,
            updated_at=now,
            source=source,
            trust=trust,
            run_id=run_id,
            conversation_id=conversation_id,
            tags=tuple(tags or ()),
            metadata=metadata or {},
        )
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO memory_entries(
                    memory_id, kind, status, content, created_at, updated_at,
                    source, trust, run_id, conversation_id, tags_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.memory_id,
                    record.kind.value,
                    record.status.value,
                    record.content,
                    record.created_at,
                    record.updated_at,
                    record.source,
                    record.trust,
                    record.run_id,
                    record.conversation_id,
                    json.dumps(list(record.tags)),
                    json.dumps(record.metadata),
                ),
            )
            self._upsert_fts(conn, record)
        return record

    def get(self, memory_id: str) -> MemoryRecord | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM memory_entries WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def list(
        self,
        *,
        status: MemoryStatus | None = MemoryStatus.ACTIVE,
        kind: MemoryKind | None = None,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 500)))
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                f"SELECT * FROM memory_entries {where} ORDER BY updated_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def search(self, query: str, *, limit: int = 10) -> list[MemoryRecord]:
        q = query.strip()
        if not q:
            return []
        with self.connect() as conn:
            self._ensure_schema(conn)
            try:
                rows = conn.execute(
                    """
                    SELECT m.* FROM memory_fts f
                    JOIN memory_entries m ON m.memory_id = f.memory_id
                    WHERE memory_fts MATCH ? AND m.status = ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (q, MemoryStatus.ACTIVE.value, max(1, min(limit, 100))),
                ).fetchall()
            except sqlite3.OperationalError:
                like = f"%{q}%"
                rows = conn.execute(
                    """
                    SELECT * FROM memory_entries
                    WHERE status = ? AND content LIKE ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (MemoryStatus.ACTIVE.value, like, max(1, min(limit, 100))),
                ).fetchall()
        return [self._from_row(row) for row in rows]

    def set_status(self, memory_id: str, status: MemoryStatus) -> MemoryRecord | None:
        now = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM memory_entries WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE memory_entries SET status = ?, updated_at = ? WHERE memory_id = ?",
                (status.value, now, memory_id),
            )
            row = conn.execute(
                "SELECT * FROM memory_entries WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def _upsert_fts(self, conn: sqlite3.Connection, record: MemoryRecord) -> None:
        try:
            conn.execute("DELETE FROM memory_fts WHERE memory_id = ?", (record.memory_id,))
            conn.execute(
                "INSERT INTO memory_fts(memory_id, content, tags) VALUES (?, ?, ?)",
                (record.memory_id, record.content, " ".join(record.tags)),
            )
        except sqlite3.OperationalError:
            pass

    @staticmethod
    def _from_row(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            memory_id=row["memory_id"],
            kind=MemoryKind(row["kind"]),
            status=MemoryStatus(row["status"]),
            content=row["content"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            source=row["source"],
            trust=row["trust"],
            run_id=row["run_id"],
            conversation_id=row["conversation_id"],
            tags=tuple(json.loads(row["tags_json"] or "[]")),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )
