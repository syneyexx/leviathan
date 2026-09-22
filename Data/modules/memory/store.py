from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .types import MEMORY_KIND_PRIORITY, MemoryKind, MemoryRecord, MemoryStatus


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MemoryStore:
    """Durable controlled memory, separate from Knowledge."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

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
        with self._lock:
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
        columns = {row[1] for row in conn.execute("PRAGMA table_info(memory_entries)").fetchall()}
        if "priority" not in columns:
            conn.execute("ALTER TABLE memory_entries ADD COLUMN priority REAL NOT NULL DEFAULT 0.5")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_status ON memory_entries(status, updated_at)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
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
        priority: float | None = None,
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
        kind_priority = MEMORY_KIND_PRIORITY.get(kind, 0.5)
        resolved_priority = (
            max(0.0, min(1.0, float(priority))) if priority is not None else kind_priority
        )
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
            priority=resolved_priority,
        )
        with self._lock:
            with self.connect() as conn:
                self._ensure_schema(conn)
                conn.execute(
                    """
                    INSERT INTO memory_entries(
                        memory_id, kind, status, content, created_at, updated_at,
                        source, trust, run_id, conversation_id, tags_json, metadata_json, priority
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        record.priority,
                    ),
                )
                self._upsert_fts(conn, record)
        return record

    def get(self, memory_id: str) -> MemoryRecord | None:
        with self._lock:
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
        with self._lock:
            with self.connect() as conn:
                self._ensure_schema(conn)
                rows = conn.execute(
                    f"SELECT * FROM memory_entries {where} ORDER BY priority DESC, updated_at DESC LIMIT ?",
                    params,
                ).fetchall()
        return [self._from_row(row) for row in rows]

    def search(self, query: str, *, limit: int = 10) -> list[MemoryRecord]:
        q = query.strip()
        if not q:
            return []
        with self._lock:
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
                        ORDER BY priority DESC, updated_at DESC
                        LIMIT ?
                        """,
                        (MemoryStatus.ACTIVE.value, like, max(1, min(limit, 100))),
                    ).fetchall()
        return [self._from_row(row) for row in rows]

    def budgeted_retrieve(
        self,
        query: str,
        *,
        token_budget: int = 400,
        limit: int = 20,
    ) -> list[MemoryRecord]:
        """Retrieve by relevance then pack under a token budget with priority eviction."""
        candidates = self.search(query, limit=max(limit, 5))
        if not candidates:
            candidates = self.list(limit=limit)
        # Prefer higher priority, then newer.
        ranked = sorted(
            candidates,
            key=lambda item: (item.priority, item.updated_at),
            reverse=True,
        )
        selected: list[MemoryRecord] = []
        used = 0
        for record in ranked:
            tokens = max(1, len(record.content.split()))
            if used + tokens > token_budget:
                continue
            selected.append(record)
            used += tokens
            if len(selected) >= limit:
                break
        return selected

    def set_status(self, memory_id: str, status: MemoryStatus) -> MemoryRecord | None:
        now = utc_now()
        with self._lock:
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

    def snapshot(self, *, label: str = "manual") -> dict[str, Any]:
        """Lock-safe snapshot of ACTIVE memory entries."""
        with self._lock:
            records = self.list(status=MemoryStatus.ACTIVE, limit=500)
            payload = {
                "label": label,
                "created_at": utc_now(),
                "entries": [r.public_dict() for r in records],
            }
            snapshot_id = str(uuid.uuid4())
            with self.connect() as conn:
                self._ensure_schema(conn)
                conn.execute(
                    """
                    INSERT INTO memory_snapshots(snapshot_id, label, created_at, payload_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (snapshot_id, label, payload["created_at"], json.dumps(payload)),
                )
        return {"snapshot_id": snapshot_id, **payload}

    def restore_snapshot(self, snapshot_id: str, *, replace_active: bool = False) -> int:
        """Restore entries from a snapshot. Optionally archive current ACTIVE first."""
        with self._lock:
            with self.connect() as conn:
                self._ensure_schema(conn)
                row = conn.execute(
                    "SELECT payload_json FROM memory_snapshots WHERE snapshot_id = ?",
                    (snapshot_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(f"memory snapshot not found: {snapshot_id}")
                payload = json.loads(row["payload_json"] or "{}")
                if replace_active:
                    conn.execute(
                        "UPDATE memory_entries SET status = ?, updated_at = ? WHERE status = ?",
                        (MemoryStatus.ARCHIVED.value, utc_now(), MemoryStatus.ACTIVE.value),
                    )
                restored = 0
                for item in payload.get("entries") or []:
                    memory_id = str(item.get("memory_id") or uuid.uuid4())
                    kind_raw = item.get("kind") or MemoryKind.NOTE.value
                    try:
                        kind = MemoryKind(kind_raw)
                    except ValueError:
                        kind = MemoryKind.NOTE
                    now = utc_now()
                    conn.execute(
                        """
                        INSERT INTO memory_entries(
                            memory_id, kind, status, content, created_at, updated_at,
                            source, trust, run_id, conversation_id, tags_json, metadata_json, priority
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(memory_id) DO UPDATE SET
                            kind = excluded.kind,
                            status = excluded.status,
                            content = excluded.content,
                            updated_at = excluded.updated_at,
                            source = excluded.source,
                            trust = excluded.trust,
                            tags_json = excluded.tags_json,
                            metadata_json = excluded.metadata_json,
                            priority = excluded.priority
                        """,
                        (
                            memory_id,
                            kind.value,
                            MemoryStatus.ACTIVE.value,
                            str(item.get("content") or "").strip() or "(empty restored memory)",
                            item.get("created_at") or now,
                            now,
                            item.get("source") or "snapshot_restore",
                            item.get("trust") or "imported",
                            item.get("run_id"),
                            item.get("conversation_id"),
                            json.dumps(list(item.get("tags") or [])),
                            json.dumps(item.get("metadata") or {}),
                            float(item.get("priority") or MEMORY_KIND_PRIORITY.get(kind, 0.5)),
                        ),
                    )
                    restored += 1
                return restored

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
        keys = row.keys()
        kind = MemoryKind(row["kind"])
        priority = (
            float(row["priority"])
            if "priority" in keys and row["priority"] is not None
            else MEMORY_KIND_PRIORITY.get(kind, 0.5)
        )
        return MemoryRecord(
            memory_id=row["memory_id"],
            kind=kind,
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
            priority=priority,
        )
