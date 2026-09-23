from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .types import (
    MEMORY_KIND_PRIORITY,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
)


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
        for col, ddl in (
            ("scope", "scope TEXT NOT NULL DEFAULT 'CONVERSATION'"),
            ("workspace_id", "workspace_id TEXT"),
            ("project_id", "project_id TEXT"),
            ("user_id", "user_id TEXT"),
            ("confidence", "confidence REAL NOT NULL DEFAULT 0.5"),
            ("valid_from", "valid_from TEXT"),
            ("valid_until", "valid_until TEXT"),
            ("supersedes_id", "supersedes_id TEXT"),
            ("source_refs_json", "source_refs_json TEXT NOT NULL DEFAULT '[]'"),
        ):
            if col not in columns:
                conn.execute(f"ALTER TABLE memory_entries ADD COLUMN {ddl}")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_status ON memory_entries(status, updated_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_scope "
            "ON memory_entries(scope, conversation_id, project_id, status)"
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
        scope: MemoryScope | str | None = None,
        workspace_id: str | None = None,
        project_id: str | None = None,
        user_id: str | None = None,
        confidence: float = 0.5,
        valid_from: str | None = None,
        valid_until: str | None = None,
        supersedes_id: str | None = None,
        source_refs: list[str] | tuple[str, ...] | None = None,
    ) -> MemoryRecord:
        text = content.strip()
        if not text:
            raise ValueError("Memory content cannot be empty")
        if trust == "model_output":
            raise ValueError(
                "Refusing to store raw model_output as memory trust; "
                "use explicit/imported/derived with human or policy authority"
            )
        # Model speculation must never become user FACT.
        source_l = (source or "").lower()
        if kind == MemoryKind.FACT and source_l in {
            "model",
            "assistant",
            "llm",
            "inference",
            "speculation",
            "model_inference",
        }:
            raise ValueError(
                "Refusing to store model speculation as FACT; "
                "use NOTE/RESIDUE with trust=derived or wait for explicit user confirmation"
            )
        if scope is None:
            scope = MemoryScope.CONVERSATION if conversation_id else MemoryScope.GLOBAL
        elif isinstance(scope, str):
            try:
                scope = MemoryScope(scope.upper())
            except ValueError as exc:
                raise ValueError(f"Invalid memory scope: {scope}") from exc
        # Conversation-scoped memories require a conversation_id to prevent silent global leak.
        if scope == MemoryScope.CONVERSATION and not conversation_id:
            raise ValueError("CONVERSATION scope requires conversation_id")
        if scope == MemoryScope.PROJECT and not project_id:
            raise ValueError("PROJECT scope requires project_id")
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
            scope=scope,
            workspace_id=workspace_id,
            project_id=project_id,
            user_id=user_id,
            confidence=max(0.0, min(1.0, float(confidence))),
            valid_from=valid_from or now,
            valid_until=valid_until,
            supersedes_id=supersedes_id,
            source_refs=tuple(source_refs or ()),
        )
        with self._lock:
            with self.connect() as conn:
                self._ensure_schema(conn)
                if supersedes_id:
                    conn.execute(
                        "UPDATE memory_entries SET status = ?, updated_at = ? WHERE memory_id = ?",
                        (MemoryStatus.SUPERSEDED.value, now, supersedes_id),
                    )
                conn.execute(
                    """
                    INSERT INTO memory_entries(
                        memory_id, kind, status, content, created_at, updated_at,
                        source, trust, run_id, conversation_id, tags_json, metadata_json, priority,
                        scope, workspace_id, project_id, user_id, confidence,
                        valid_from, valid_until, supersedes_id, source_refs_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        record.scope.value,
                        record.workspace_id,
                        record.project_id,
                        record.user_id,
                        record.confidence,
                        record.valid_from,
                        record.valid_until,
                        record.supersedes_id,
                        json.dumps(list(record.source_refs)),
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
        scope: MemoryScope | None = None,
        conversation_id: str | None = None,
        project_id: str | None = None,
        workspace_id: str | None = None,
        user_id: str | None = None,
        limit: int = 100,
        include_global: bool = True,
    ) -> list[MemoryRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind.value)
        scope_clause, scope_params = self._scope_filter_sql(
            scope=scope,
            conversation_id=conversation_id,
            project_id=project_id,
            workspace_id=workspace_id,
            user_id=user_id,
            include_global=include_global,
            active_filter=False,
        )
        if scope_clause and any((scope, conversation_id, project_id, workspace_id, user_id)):
            clauses.append(scope_clause)
            params.extend(scope_params)
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

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        scope: MemoryScope | None = None,
        conversation_id: str | None = None,
        project_id: str | None = None,
        workspace_id: str | None = None,
        user_id: str | None = None,
        include_global: bool = True,
        require_scope: bool = False,
    ) -> list[MemoryRecord]:
        """Search ACTIVE memories. Scoped filters prevent cross-conversation leakage."""
        q = query.strip()
        if not q:
            return []
        if require_scope and not any((conversation_id, project_id, workspace_id, user_id, scope)):
            raise ValueError(
                "scoped memory search requires conversation_id/project_id/workspace_id/user_id/scope"
            )
        # Default safe behavior: if no scope context, only GLOBAL (no conversation leak).
        scoped = any((conversation_id, project_id, workspace_id, user_id, scope))
        scope_clause, scope_params = self._scope_filter_sql(
            scope=scope,
            conversation_id=conversation_id,
            project_id=project_id,
            workspace_id=workspace_id,
            user_id=user_id,
            include_global=include_global,
            active_filter=True,
        )
        with self._lock:
            with self.connect() as conn:
                self._ensure_schema(conn)
                try:
                    sql = """
                        SELECT m.* FROM memory_fts f
                        JOIN memory_entries m ON m.memory_id = f.memory_id
                        WHERE memory_fts MATCH ? AND m.status = ?
                    """
                    params: list[Any] = [q, MemoryStatus.ACTIVE.value]
                    if scoped or True:
                        sql += f" AND ({scope_clause})"
                        params.extend(scope_params)
                    sql += " ORDER BY rank LIMIT ?"
                    params.append(max(1, min(limit, 100)))
                    rows = conn.execute(sql, params).fetchall()
                except sqlite3.OperationalError:
                    like = f"%{q}%"
                    sql = """
                        SELECT * FROM memory_entries
                        WHERE status = ? AND content LIKE ?
                    """
                    params = [MemoryStatus.ACTIVE.value, like]
                    sql += f" AND ({scope_clause})"
                    params.extend(scope_params)
                    sql += " ORDER BY priority DESC, updated_at DESC LIMIT ?"
                    params.append(max(1, min(limit, 100)))
                    rows = conn.execute(sql, params).fetchall()
        return [self._from_row(row) for row in rows]

    def budgeted_retrieve(
        self,
        query: str,
        *,
        token_budget: int = 400,
        limit: int = 20,
        conversation_id: str | None = None,
        project_id: str | None = None,
        workspace_id: str | None = None,
        user_id: str | None = None,
        include_global: bool = True,
        require_scope: bool = False,
    ) -> list[MemoryRecord]:
        """Retrieve by relevance then pack under a token budget with priority eviction."""
        candidates = self.search(
            query,
            limit=max(limit, 5),
            conversation_id=conversation_id,
            project_id=project_id,
            workspace_id=workspace_id,
            user_id=user_id,
            include_global=include_global,
            require_scope=require_scope,
        )
        if not candidates:
            candidates = self.list(
                limit=limit,
                conversation_id=conversation_id,
                project_id=project_id,
                workspace_id=workspace_id,
                user_id=user_id,
                include_global=include_global,
            )
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

    @staticmethod
    def _scope_filter_sql(
        *,
        scope: MemoryScope | None,
        conversation_id: str | None,
        project_id: str | None,
        workspace_id: str | None,
        user_id: str | None,
        include_global: bool,
        active_filter: bool = True,
    ) -> tuple[str, list[Any]]:
        """Build SQL that prevents cross-conversation / cross-project leakage."""
        _ = active_filter
        if scope is not None and not any((conversation_id, project_id, workspace_id, user_id)):
            return "scope = ?", [scope.value]

        parts: list[str] = []
        params: list[Any] = []
        if include_global:
            parts.append("scope = 'GLOBAL'")
        if conversation_id:
            parts.append("(scope = 'CONVERSATION' AND conversation_id = ?)")
            params.append(conversation_id)
        if project_id:
            parts.append("(scope = 'PROJECT' AND project_id = ?)")
            params.append(project_id)
        if workspace_id:
            parts.append("(scope = 'WORKSPACE' AND workspace_id = ?)")
            params.append(workspace_id)
        if user_id:
            parts.append("(scope = 'USER' AND user_id = ?)")
            params.append(user_id)
        if not parts:
            # No scope context → only GLOBAL is safe (blocks conversation leak).
            return "scope = 'GLOBAL'", []
        return "(" + " OR ".join(parts) + ")", params

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
        scope_raw = row["scope"] if "scope" in keys and row["scope"] else MemoryScope.GLOBAL.value
        try:
            scope = MemoryScope(str(scope_raw))
        except ValueError:
            scope = MemoryScope.GLOBAL
        source_refs = ()
        if "source_refs_json" in keys:
            source_refs = tuple(json.loads(row["source_refs_json"] or "[]"))
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
            scope=scope,
            workspace_id=row["workspace_id"] if "workspace_id" in keys else None,
            project_id=row["project_id"] if "project_id" in keys else None,
            user_id=row["user_id"] if "user_id" in keys else None,
            confidence=float(row["confidence"]) if "confidence" in keys and row["confidence"] is not None else 0.5,
            valid_from=row["valid_from"] if "valid_from" in keys else None,
            valid_until=row["valid_until"] if "valid_until" in keys else None,
            supersedes_id=row["supersedes_id"] if "supersedes_id" in keys else None,
            source_refs=source_refs,
        )
