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

        with self._lock:
            with self.connect() as conn:
                ensure_wal(conn)
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
        # Semantic index — CONTROL DB ownership (no memory.db / vector-memory.db).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_embeddings (
                memory_id TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                model_id TEXT,
                dimensions INTEGER NOT NULL,
                vector_blob BLOB NOT NULL,
                indexed_at TEXT NOT NULL,
                stale INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(memory_id) REFERENCES memory_entries(memory_id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_embeddings_stale "
            "ON memory_embeddings(stale, indexed_at)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                memory_id TEXT,
                actor TEXT,
                detail_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_events_created "
            "ON memory_events(created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_events_type "
            "ON memory_events(event_type, created_at DESC)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_search_telemetry (
                telemetry_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                mode TEXT NOT NULL,
                duration_ms REAL,
                result_count INTEGER NOT NULL DEFAULT 0,
                scope_class TEXT,
                success INTEGER NOT NULL DEFAULT 1,
                topic_label TEXT,
                query_hash TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_search_telemetry_created "
            "ON memory_search_telemetry(created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_kind_status "
            "ON memory_entries(kind, status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_source "
            "ON memory_entries(source, status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_created "
            "ON memory_entries(created_at DESC)"
        )

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
        self.record_event(
            "memory.created",
            memory_id=record.memory_id,
            actor="api",
            detail={"kind": record.kind.value, "source": record.source},
        )
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
        offset: int = 0,
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
        params.extend([max(1, min(limit, 500)), max(0, offset)])
        with self._lock:
            with self.connect() as conn:
                self._ensure_schema(conn)
                rows = conn.execute(
                    f"SELECT * FROM memory_entries {where} ORDER BY priority DESC, updated_at DESC, memory_id LIMIT ? OFFSET ?",
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

    def correct_preference(
        self,
        content: str,
        *,
        preference_key: str,
        previous_memory_id: str | None = None,
        conversation_id: str | None = None,
        project_id: str | None = None,
        workspace_id: str | None = None,
        user_id: str | None = None,
        scope: MemoryScope | str | None = None,
        source: str = "user",
        trust: str = "explicit",
        tags: list[str] | tuple[str, ...] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord:
        """Persist a corrected user preference; prior matching prefs become SUPERSEDED.

        A08 / W08: the current preference must win on retrieval — stale ACTIVE
        duplicates with the same preference_key are closed, not left competing.
        Canonical kind is PREFERENCE; legacy FACT rows tagged as preferences are
        also superseded so BehaviorProfile overlays and MemoryStore stay aligned
        without a parallel preference store.
        """
        key = (preference_key or "").strip()
        if not key:
            raise ValueError("preference_key is required for preference correction")
        resolved_scope: MemoryScope | None = None
        if isinstance(scope, MemoryScope):
            resolved_scope = scope
        elif isinstance(scope, str) and scope.strip():
            try:
                resolved_scope = MemoryScope(scope.strip().upper())
            except ValueError as exc:
                raise ValueError(f"Invalid memory scope: {scope}") from exc

        stale_ids: list[str] = []
        if previous_memory_id:
            stale_ids.append(previous_memory_id)
        # Close every ACTIVE preference (PREFERENCE or legacy FACT) sharing the key.
        # Stay in-scope: do not silently supersede GLOBAL prefs from a conversation edit.
        scoped = bool(conversation_id or project_id or workspace_id or user_id or resolved_scope)
        for kind in (MemoryKind.PREFERENCE, MemoryKind.FACT):
            active = self.list(
                status=MemoryStatus.ACTIVE,
                kind=kind,
                conversation_id=conversation_id,
                project_id=project_id,
                workspace_id=workspace_id,
                user_id=user_id,
                scope=resolved_scope,
                include_global=not scoped,
                limit=200,
            )
            for record in active:
                if previous_memory_id and record.memory_id == previous_memory_id:
                    continue
                meta = dict(record.metadata or {})
                if str(meta.get("preference_key") or "") == key or key in record.tags:
                    if record.memory_id not in stale_ids:
                        stale_ids.append(record.memory_id)

        supersedes_id = stale_ids[0] if stale_ids else None
        merged_tags = list(tags or ())
        if key not in merged_tags:
            merged_tags.append(key)
        if "preference" not in merged_tags:
            merged_tags.append("preference")
        meta = dict(metadata or {})
        meta["preference_key"] = key
        meta["correction"] = True
        if stale_ids:
            meta["supersedes_preference"] = supersedes_id
            meta["superseded_preference_ids"] = list(stale_ids)
        record = self.create(
            content=content,
            kind=MemoryKind.PREFERENCE,
            source=source,
            trust=trust,
            conversation_id=conversation_id,
            project_id=project_id,
            workspace_id=workspace_id,
            user_id=user_id,
            scope=scope,
            tags=merged_tags,
            metadata=meta,
            supersedes_id=supersedes_id,
            confidence=1.0,
            priority=MEMORY_KIND_PRIORITY.get(MemoryKind.PREFERENCE, 0.95),
        )
        # create() supersedes only one id; close any additional stale duplicates.
        for extra_id in stale_ids[1:]:
            if extra_id == record.memory_id:
                continue
            self.set_status(extra_id, MemoryStatus.SUPERSEDED)
        return record

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
        record = self._from_row(row) if row else None
        if record is not None:
            event = {
                MemoryStatus.ARCHIVED: "memory.archived",
                MemoryStatus.REVOKED: "memory.revoked",
                MemoryStatus.ACTIVE: "memory.activated",
                MemoryStatus.SUPERSEDED: "memory.superseded",
            }.get(status, "memory.status_changed")
            self.record_event(event, memory_id=memory_id, actor="api", detail={"status": status.value})
            if status in {MemoryStatus.REVOKED, MemoryStatus.ARCHIVED, MemoryStatus.SUPERSEDED}:
                self.mark_embedding_stale(memory_id)
        return record

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

    # ------------------------------------------------------------------
    # Wave 1+: pagination, patch, pin, correct, restore, overview
    # ------------------------------------------------------------------

    PINNED_TAG = "pinned"

    def list_page(
        self,
        *,
        status: MemoryStatus | None = MemoryStatus.ACTIVE,
        kind: MemoryKind | None = None,
        source: str | None = None,
        trust: str | None = None,
        scope: MemoryScope | None = None,
        conversation_id: str | None = None,
        project_id: str | None = None,
        workspace_id: str | None = None,
        user_id: str | None = None,
        tag: str | None = None,
        pinned_only: bool = False,
        priority_min: float | None = None,
        priority_max: float | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        sort: str = "newest",
        limit: int = 50,
        cursor: str | None = None,
        include_global: bool = True,
    ) -> dict[str, Any]:
        """Bounded cursor pagination — never load the full store into the UI."""
        limit_n = max(1, min(int(limit), 100))
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind.value)
        if source:
            clauses.append("LOWER(source) = LOWER(?)")
            params.append(source.strip())
        if trust:
            clauses.append("LOWER(trust) = LOWER(?)")
            params.append(trust.strip())
        if tag or pinned_only:
            needle = self.PINNED_TAG if pinned_only else str(tag)
            clauses.append("LOWER(tags_json) LIKE ?")
            params.append(f"%{needle.lower()}%")
        if priority_min is not None:
            clauses.append("priority >= ?")
            params.append(float(priority_min))
        if priority_max is not None:
            clauses.append("priority <= ?")
            params.append(float(priority_max))
        if created_after:
            clauses.append("created_at >= ?")
            params.append(created_after)
        if created_before:
            clauses.append("created_at <= ?")
            params.append(created_before)
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

        # Cursor encodes updated_at|memory_id for keyset pagination.
        if cursor:
            try:
                cur_updated, cur_id = cursor.split("|", 1)
                if sort in {"oldest", "kind", "source", "priority"}:
                    # Fall back to updated_at keyset for non-newest sorts still using cursor.
                    clauses.append("(updated_at < ? OR (updated_at = ? AND memory_id < ?))")
                    params.extend([cur_updated, cur_updated, cur_id])
                else:
                    clauses.append("(updated_at < ? OR (updated_at = ? AND memory_id < ?))")
                    params.extend([cur_updated, cur_updated, cur_id])
            except ValueError:
                pass

        order = {
            "newest": "updated_at DESC, memory_id DESC",
            "oldest": "updated_at ASC, memory_id ASC",
            "priority": "priority DESC, updated_at DESC, memory_id DESC",
            "kind": "kind ASC, updated_at DESC, memory_id DESC",
            "source": "source ASC, updated_at DESC, memory_id DESC",
        }.get(sort, "updated_at DESC, memory_id DESC")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit_n + 1)
        with self._lock:
            with self.connect() as conn:
                self._ensure_schema(conn)
                rows = conn.execute(
                    f"SELECT * FROM memory_entries {where} ORDER BY {order} LIMIT ?",
                    params,
                ).fetchall()
        items = [self._from_row(row) for row in rows[:limit_n]]
        next_cursor = None
        if len(rows) > limit_n and items:
            last = items[-1]
            next_cursor = f"{last.updated_at}|{last.memory_id}"
        return {
            "memory": items,
            "next_cursor": next_cursor,
            "limit": limit_n,
            "sort": sort,
        }

    def update(
        self,
        memory_id: str,
        *,
        tags: list[str] | tuple[str, ...] | None = None,
        priority: float | None = None,
        valid_until: str | None = None,
        metadata_patch: dict[str, Any] | None = None,
        clear_valid_until: bool = False,
    ) -> MemoryRecord | None:
        """Controlled metadata update — never silently mutates content/provenance."""
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
                record = self._from_row(row)
                new_tags = list(tags) if tags is not None else list(record.tags)
                new_priority = (
                    max(0.0, min(1.0, float(priority)))
                    if priority is not None
                    else record.priority
                )
                new_valid_until = record.valid_until
                if clear_valid_until:
                    new_valid_until = None
                elif valid_until is not None:
                    new_valid_until = valid_until
                new_meta = dict(record.metadata or {})
                if metadata_patch:
                    new_meta.update(metadata_patch)
                conn.execute(
                    """
                    UPDATE memory_entries
                    SET tags_json = ?, priority = ?, valid_until = ?,
                        metadata_json = ?, updated_at = ?
                    WHERE memory_id = ?
                    """,
                    (
                        json.dumps(new_tags),
                        new_priority,
                        new_valid_until,
                        json.dumps(new_meta),
                        now,
                        memory_id,
                    ),
                )
                updated = self._from_row(
                    conn.execute(
                        "SELECT * FROM memory_entries WHERE memory_id = ?",
                        (memory_id,),
                    ).fetchone()
                )
                self._upsert_fts(conn, updated)
        self.record_event("memory.updated", memory_id=memory_id, actor="api")
        return updated

    def pin(self, memory_id: str) -> MemoryRecord | None:
        record = self.get(memory_id)
        if record is None:
            return None
        tags = list(record.tags)
        if not any(t.lower() == self.PINNED_TAG for t in tags):
            tags.append(self.PINNED_TAG)
        updated = self.update(memory_id, tags=tags, metadata_patch={"pinned": True})
        if updated:
            self.record_event("memory.pinned", memory_id=memory_id, actor="api")
        return updated

    def unpin(self, memory_id: str) -> MemoryRecord | None:
        record = self.get(memory_id)
        if record is None:
            return None
        tags = [t for t in record.tags if t.lower() != self.PINNED_TAG]
        meta = dict(record.metadata or {})
        meta["pinned"] = False
        updated = self.update(memory_id, tags=tags, metadata_patch=meta)
        if updated:
            self.record_event("memory.unpinned", memory_id=memory_id, actor="api")
        return updated

    def correct(
        self,
        memory_id: str,
        *,
        content: str,
        kind: MemoryKind | None = None,
        trust: str = "explicit",
        source: str = "correction",
        tags: list[str] | tuple[str, ...] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord:
        """Create a CORRECTION that supersedes the target — never PATCH content in place."""
        original = self.get(memory_id)
        if original is None:
            raise KeyError(f"memory not found: {memory_id}")
        if original.status == MemoryStatus.REVOKED:
            raise ValueError("Cannot correct a REVOKED memory")
        text = content.strip()
        if not text:
            raise ValueError("Correction content cannot be empty")
        meta = dict(metadata or {})
        meta["correction_of"] = memory_id
        meta["original_content_excerpt"] = original.content[:240]
        meta["correction"] = True
        merged_tags = list(tags or original.tags)
        if "correction" not in merged_tags:
            merged_tags.append("correction")
        record = self.create(
            content=text,
            kind=kind or MemoryKind.CORRECTION,
            source=source,
            trust=trust,
            tags=merged_tags,
            metadata=meta,
            conversation_id=original.conversation_id,
            run_id=original.run_id,
            scope=original.scope,
            workspace_id=original.workspace_id,
            project_id=original.project_id,
            user_id=original.user_id,
            supersedes_id=memory_id,
            source_refs=list(original.source_refs) + [f"memory:{memory_id}"],
            confidence=max(original.confidence, 0.7),
            priority=max(original.priority, MEMORY_KIND_PRIORITY.get(MemoryKind.CORRECTION, 0.97)),
        )
        self.record_event(
            "memory.corrected",
            memory_id=record.memory_id,
            actor="api",
            detail={"supersedes_id": memory_id},
        )
        # Mark any embedding for superseded row stale.
        self.mark_embedding_stale(memory_id)
        return record

    def restore(self, memory_id: str) -> MemoryRecord | None:
        """Restore ARCHIVED → ACTIVE. REVOKED cannot be casually restored."""
        record = self.get(memory_id)
        if record is None:
            return None
        if record.status == MemoryStatus.REVOKED:
            raise ValueError("REVOKED memory cannot be restored; create a correction or new record")
        if record.status == MemoryStatus.SUPERSEDED:
            raise ValueError("SUPERSEDED memory cannot be restored; it was replaced by a correction")
        if record.status != MemoryStatus.ARCHIVED:
            raise ValueError(f"Only ARCHIVED memories can be restored (status={record.status.value})")
        updated = self.set_status(memory_id, MemoryStatus.ACTIVE)
        if updated:
            self.record_event("memory.restored", memory_id=memory_id, actor="api")
        return updated

    def overview(self) -> dict[str, Any]:
        """Bounded aggregate overview — SQL aggregates, not full-table Python scans."""
        with self._lock:
            with self.connect() as conn:
                self._ensure_schema(conn)
                total = int(
                    conn.execute("SELECT COUNT(*) AS c FROM memory_entries").fetchone()["c"]
                )
                by_status: dict[str, int] = {}
                for row in conn.execute(
                    "SELECT status, COUNT(*) AS c FROM memory_entries GROUP BY status"
                ):
                    by_status[str(row["status"])] = int(row["c"])
                by_kind: dict[str, int] = {}
                for row in conn.execute(
                    "SELECT kind, COUNT(*) AS c FROM memory_entries "
                    "WHERE status = ? GROUP BY kind ORDER BY c DESC",
                    (MemoryStatus.ACTIVE.value,),
                ):
                    by_kind[str(row["kind"])] = int(row["c"])
                by_scope: dict[str, int] = {}
                for row in conn.execute(
                    "SELECT scope, COUNT(*) AS c FROM memory_entries "
                    "WHERE status = ? GROUP BY scope",
                    (MemoryStatus.ACTIVE.value,),
                ):
                    by_scope[str(row["scope"])] = int(row["c"])
                by_trust: dict[str, int] = {}
                for row in conn.execute(
                    "SELECT trust, COUNT(*) AS c FROM memory_entries "
                    "WHERE status = ? GROUP BY trust",
                    (MemoryStatus.ACTIVE.value,),
                ):
                    by_trust[str(row["trust"])] = int(row["c"])
                unique_sources = int(
                    conn.execute(
                        "SELECT COUNT(DISTINCT LOWER(source)) AS c FROM memory_entries"
                    ).fetchone()["c"]
                )
                newest = conn.execute(
                    "SELECT MAX(created_at) AS m FROM memory_entries"
                ).fetchone()["m"]
                content_bytes = int(
                    conn.execute(
                        "SELECT COALESCE(SUM(LENGTH(content) + LENGTH(tags_json) "
                        "+ LENGTH(metadata_json)), 0) AS b FROM memory_entries"
                    ).fetchone()["b"]
                )
                emb_count = 0
                emb_stale = 0
                emb_bytes = 0
                emb_dims: int | None = None
                emb_provider: str | None = None
                emb_model: str | None = None
                try:
                    emb_count = int(
                        conn.execute(
                            "SELECT COUNT(*) AS c FROM memory_embeddings WHERE stale = 0"
                        ).fetchone()["c"]
                    )
                    emb_stale = int(
                        conn.execute(
                            "SELECT COUNT(*) AS c FROM memory_embeddings WHERE stale = 1"
                        ).fetchone()["c"]
                    )
                    emb_bytes = int(
                        conn.execute(
                            "SELECT COALESCE(SUM(LENGTH(vector_blob)), 0) AS b "
                            "FROM memory_embeddings"
                        ).fetchone()["b"]
                    )
                    meta_row = conn.execute(
                        "SELECT provider_id, model_id, dimensions FROM memory_embeddings "
                        "WHERE stale = 0 ORDER BY indexed_at DESC LIMIT 1"
                    ).fetchone()
                    if meta_row:
                        emb_provider = str(meta_row["provider_id"] or "") or None
                        emb_model = str(meta_row["model_id"] or "") or None
                        emb_dims = int(meta_row["dimensions"]) if meta_row["dimensions"] else None
                except sqlite3.OperationalError:
                    pass
                search_7d = 0
                try:
                    search_7d = int(
                        conn.execute(
                            "SELECT COUNT(*) AS c FROM memory_search_telemetry "
                            "WHERE created_at >= datetime('now', '-7 days')"
                        ).fetchone()["c"]
                    )
                except sqlite3.OperationalError:
                    pass
        storage_total = content_bytes + emb_bytes
        return {
            "total": total,
            "active": by_status.get(MemoryStatus.ACTIVE.value, 0),
            "archived": by_status.get(MemoryStatus.ARCHIVED.value, 0),
            "revoked": by_status.get(MemoryStatus.REVOKED.value, 0),
            "superseded": by_status.get(MemoryStatus.SUPERSEDED.value, 0),
            "by_kind": by_kind,
            "by_scope": by_scope,
            "by_trust": by_trust,
            "unique_sources": unique_sources,
            "newest_at": newest,
            "semantic_index": {
                "indexed_count": emb_count,
                "stale_count": emb_stale,
                "provider_id": emb_provider,
                "model_id": emb_model,
                "dimensions": emb_dims,
                "backend": "sqlite_control_memory_embeddings",
                "bytes": emb_bytes,
                "bytes_provenance": "MEASURED",
                "status": "HEALTHY" if emb_count > 0 else "EMPTY",
            },
            "storage": {
                "content_bytes": content_bytes,
                "embedding_bytes": emb_bytes,
                "total_bytes": storage_total,
                "provenance": "MEASURED",
                "label": "Memory payload + semantic index",
            },
            "search_count_7d": search_7d,
            "truth": {
                "total_includes_all_statuses": True,
                "no_full_store_scan_in_python": True,
                "memory_is_not_knowledge": True,
            },
        }

    def record_event(
        self,
        event_type: str,
        *,
        memory_id: str | None = None,
        actor: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        event_id = str(uuid.uuid4())
        now = utc_now()
        with self._lock:
            with self.connect() as conn:
                self._ensure_schema(conn)
                conn.execute(
                    """
                    INSERT INTO memory_events(
                        event_id, event_type, memory_id, actor, detail_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        event_type,
                        memory_id,
                        actor,
                        json.dumps(detail or {}),
                        now,
                    ),
                )

    def list_activity(self, *, limit: int = 40) -> list[dict[str, Any]]:
        limit_n = max(1, min(int(limit), 200))
        with self._lock:
            with self.connect() as conn:
                self._ensure_schema(conn)
                rows = conn.execute(
                    "SELECT * FROM memory_events ORDER BY created_at DESC LIMIT ?",
                    (limit_n,),
                ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "event_id": row["event_id"],
                    "event_type": row["event_type"],
                    "memory_id": row["memory_id"],
                    "actor": row["actor"] or "System",
                    "detail": json.loads(row["detail_json"] or "{}"),
                    "created_at": row["created_at"],
                }
            )
        return out

    def record_search_telemetry(
        self,
        *,
        mode: str,
        duration_ms: float | None,
        result_count: int,
        scope_class: str | None = None,
        success: bool = True,
        topic_label: str | None = None,
        query_hash: str | None = None,
    ) -> None:
        """Privacy-conscious search telemetry — no raw query content by default."""
        with self._lock:
            with self.connect() as conn:
                self._ensure_schema(conn)
                conn.execute(
                    """
                    INSERT INTO memory_search_telemetry(
                        telemetry_id, created_at, mode, duration_ms, result_count,
                        scope_class, success, topic_label, query_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        utc_now(),
                        mode,
                        duration_ms,
                        int(result_count),
                        scope_class,
                        1 if success else 0,
                        (topic_label or "")[:80] or None,
                        query_hash,
                    ),
                )

    def analytics(self, *, range_key: str = "7d") -> dict[str, Any]:
        windows = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}
        days = windows.get(range_key, 7)
        with self._lock:
            with self.connect() as conn:
                self._ensure_schema(conn)
                series_new: list[dict[str, Any]] = []
                series_search: list[dict[str, Any]] = []
                series_emb: list[dict[str, Any]] = []
                for offset in range(days - 1, -1, -1):
                    day_expr = f"-{offset} days"
                    day_label = conn.execute(
                        f"SELECT date('now', '{day_expr}') AS d"
                    ).fetchone()["d"]
                    new_c = int(
                        conn.execute(
                            "SELECT COUNT(*) AS c FROM memory_entries "
                            "WHERE date(created_at) = ?",
                            (day_label,),
                        ).fetchone()["c"]
                    )
                    series_new.append({"date": day_label, "count": new_c})
                    try:
                        s_c = int(
                            conn.execute(
                                "SELECT COUNT(*) AS c FROM memory_search_telemetry "
                                "WHERE date(created_at) = ?",
                                (day_label,),
                            ).fetchone()["c"]
                        )
                    except sqlite3.OperationalError:
                        s_c = 0
                    series_search.append({"date": day_label, "count": s_c})
                    try:
                        e_c = int(
                            conn.execute(
                                "SELECT COUNT(*) AS c FROM memory_embeddings "
                                "WHERE date(indexed_at) = ? AND stale = 0",
                                (day_label,),
                            ).fetchone()["c"]
                        )
                    except sqlite3.OperationalError:
                        e_c = 0
                    series_emb.append({"date": day_label, "count": e_c})

                # Top sources
                top_sources: list[dict[str, Any]] = []
                for row in conn.execute(
                    "SELECT source, COUNT(*) AS items, "
                    "COALESCE(SUM(LENGTH(content)), 0) AS bytes "
                    "FROM memory_entries GROUP BY source ORDER BY items DESC LIMIT 20"
                ):
                    top_sources.append(
                        {
                            "source": row["source"],
                            "items": int(row["items"]),
                            "bytes": int(row["bytes"]),
                            "bytes_provenance": "MEASURED",
                        }
                    )

                # Topics from safe telemetry labels (never raw query).
                topics: list[dict[str, Any]] = []
                half = max(1, days // 2)
                for row in conn.execute(
                    """
                    SELECT topic_label, COUNT(*) AS c
                    FROM memory_search_telemetry
                    WHERE topic_label IS NOT NULL AND topic_label != ''
                      AND created_at >= datetime('now', ?)
                    GROUP BY topic_label
                    ORDER BY c DESC
                    LIMIT 15
                    """,
                    (f"-{days} days",),
                ):
                    label = str(row["topic_label"])
                    current = int(row["c"])
                    prev = int(
                        conn.execute(
                            """
                            SELECT COUNT(*) AS c FROM memory_search_telemetry
                            WHERE topic_label = ?
                              AND created_at >= datetime('now', ?)
                              AND created_at < datetime('now', ?)
                            """,
                            (label, f"-{days} days", f"-{half} days"),
                        ).fetchone()["c"]
                    )
                    # Trend: current half vs previous half of window.
                    cur_half = int(
                        conn.execute(
                            """
                            SELECT COUNT(*) AS c FROM memory_search_telemetry
                            WHERE topic_label = ?
                              AND created_at >= datetime('now', ?)
                            """,
                            (label, f"-{half} days"),
                        ).fetchone()["c"]
                    )
                    trend_pct: float | None
                    if prev <= 0:
                        trend_pct = None if cur_half == 0 else None
                    else:
                        trend_pct = round(((cur_half - prev) / prev) * 100.0, 1)
                    topics.append(
                        {
                            "topic": label,
                            "queries": current,
                            "trend_pct": trend_pct,
                        }
                    )

                by_kind: dict[str, int] = {}
                for row in conn.execute(
                    "SELECT kind, COUNT(*) AS c FROM memory_entries "
                    "WHERE status = ? GROUP BY kind",
                    (MemoryStatus.ACTIVE.value,),
                ):
                    by_kind[str(row["kind"])] = int(row["c"])

        return {
            "range": range_key if range_key in windows else "7d",
            "days": days,
            "series": {
                "new_items": series_new,
                "searches": series_search,
                "embeddings": series_emb,
            },
            "top_sources": top_sources,
            "topics": topics,
            "by_kind": by_kind,
            "truth": {
                "no_fabricated_trends": True,
                "raw_queries_not_persisted": True,
            },
        }

    # ------------------------------------------------------------------
    # Semantic index (CONTROL DB)
    # ------------------------------------------------------------------

    @staticmethod
    def content_hash(content: str) -> str:
        import hashlib

        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def upsert_embedding(
        self,
        memory_id: str,
        *,
        vector: list[float],
        provider_id: str,
        model_id: str | None,
        content_hash: str,
        dimensions: int | None = None,
    ) -> dict[str, Any]:
        import struct

        dims = int(dimensions or len(vector))
        if dims <= 0 or len(vector) != dims:
            raise ValueError("embedding dimensions mismatch")
        blob = struct.pack(f"{dims}f", *[float(x) for x in vector])
        now = utc_now()
        with self._lock:
            with self.connect() as conn:
                self._ensure_schema(conn)
                conn.execute(
                    """
                    INSERT INTO memory_embeddings(
                        memory_id, content_hash, provider_id, model_id,
                        dimensions, vector_blob, indexed_at, stale
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                    ON CONFLICT(memory_id) DO UPDATE SET
                        content_hash = excluded.content_hash,
                        provider_id = excluded.provider_id,
                        model_id = excluded.model_id,
                        dimensions = excluded.dimensions,
                        vector_blob = excluded.vector_blob,
                        indexed_at = excluded.indexed_at,
                        stale = 0
                    """,
                    (memory_id, content_hash, provider_id, model_id, dims, blob, now),
                )
        self.record_event(
            "memory.embedded",
            memory_id=memory_id,
            actor="Memory Worker",
            detail={"provider_id": provider_id, "dimensions": dims},
        )
        return {
            "memory_id": memory_id,
            "provider_id": provider_id,
            "model_id": model_id,
            "dimensions": dims,
            "indexed_at": now,
            "stale": False,
        }

    def mark_embedding_stale(self, memory_id: str) -> None:
        with self._lock:
            with self.connect() as conn:
                self._ensure_schema(conn)
                try:
                    conn.execute(
                        "UPDATE memory_embeddings SET stale = 1 WHERE memory_id = ?",
                        (memory_id,),
                    )
                except sqlite3.OperationalError:
                    pass

    def get_embedding(self, memory_id: str) -> dict[str, Any] | None:
        import struct

        with self._lock:
            with self.connect() as conn:
                self._ensure_schema(conn)
                row = conn.execute(
                    "SELECT * FROM memory_embeddings WHERE memory_id = ?",
                    (memory_id,),
                ).fetchone()
        if row is None:
            return None
        dims = int(row["dimensions"])
        vector = list(struct.unpack(f"{dims}f", row["vector_blob"]))
        return {
            "memory_id": row["memory_id"],
            "content_hash": row["content_hash"],
            "provider_id": row["provider_id"],
            "model_id": row["model_id"],
            "dimensions": dims,
            "vector": vector,
            "indexed_at": row["indexed_at"],
            "stale": bool(row["stale"]),
        }

    def list_embedding_targets(
        self,
        *,
        limit: int = 50,
        include_stale: bool = True,
        only_missing: bool = False,
    ) -> list[MemoryRecord]:
        """ACTIVE memories needing (re)index — bounded."""
        limit_n = max(1, min(int(limit), 200))
        with self._lock:
            with self.connect() as conn:
                self._ensure_schema(conn)
                if only_missing:
                    rows = conn.execute(
                        """
                        SELECT m.* FROM memory_entries m
                        LEFT JOIN memory_embeddings e ON e.memory_id = m.memory_id
                        WHERE m.status = ? AND e.memory_id IS NULL
                        ORDER BY m.updated_at DESC
                        LIMIT ?
                        """,
                        (MemoryStatus.ACTIVE.value, limit_n),
                    ).fetchall()
                elif include_stale:
                    rows = conn.execute(
                        """
                        SELECT m.* FROM memory_entries m
                        LEFT JOIN memory_embeddings e ON e.memory_id = m.memory_id
                        WHERE m.status = ?
                          AND (e.memory_id IS NULL OR e.stale = 1)
                        ORDER BY m.updated_at DESC
                        LIMIT ?
                        """,
                        (MemoryStatus.ACTIVE.value, limit_n),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT m.* FROM memory_entries m
                        LEFT JOIN memory_embeddings e ON e.memory_id = m.memory_id
                        WHERE m.status = ? AND e.memory_id IS NULL
                        ORDER BY m.updated_at DESC
                        LIMIT ?
                        """,
                        (MemoryStatus.ACTIVE.value, limit_n),
                    ).fetchall()
        # Prefer Python content-hash check for staleness correctness.
        out: list[MemoryRecord] = []
        for row in rows:
            rec = self._from_row(row)
            emb = self.get_embedding(rec.memory_id)
            if emb is None or emb.get("stale") or emb.get("content_hash") != self.content_hash(rec.content):
                out.append(rec)
            if len(out) >= limit_n:
                break
        if not out and only_missing:
            return [self._from_row(r) for r in rows][:limit_n]
        return out[:limit_n]

    def delete_orphan_embeddings(self) -> int:
        with self._lock:
            with self.connect() as conn:
                self._ensure_schema(conn)
                cur = conn.execute(
                    """
                    DELETE FROM memory_embeddings
                    WHERE memory_id NOT IN (SELECT memory_id FROM memory_entries)
                    """
                )
                return int(cur.rowcount or 0)

    def find_exact_duplicates(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Exact normalized-content duplicates within same scope class."""
        limit_n = max(1, min(int(limit), 500))
        with self._lock:
            with self.connect() as conn:
                self._ensure_schema(conn)
                rows = conn.execute(
                    """
                    SELECT LOWER(TRIM(content)) AS norm, scope, conversation_id, project_id,
                           COUNT(*) AS c,
                           GROUP_CONCAT(memory_id) AS ids
                    FROM memory_entries
                    WHERE status = ?
                    GROUP BY norm, scope, IFNULL(conversation_id, ''), IFNULL(project_id, '')
                    HAVING c > 1
                    ORDER BY c DESC
                    LIMIT ?
                    """,
                    (MemoryStatus.ACTIVE.value, limit_n),
                ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            ids = [i for i in str(row["ids"] or "").split(",") if i]
            out.append(
                {
                    "content_norm": str(row["norm"])[:120],
                    "scope": row["scope"],
                    "conversation_id": row["conversation_id"],
                    "project_id": row["project_id"],
                    "count": int(row["c"]),
                    "memory_ids": ids,
                    "match": "exact_hash",
                }
            )
        return out

    def search_scored(
        self,
        query: str,
        *,
        mode: str = "lexical",
        limit: int = 10,
        scope: MemoryScope | None = None,
        conversation_id: str | None = None,
        project_id: str | None = None,
        workspace_id: str | None = None,
        user_id: str | None = None,
        include_global: bool = True,
        query_vector: list[float] | None = None,
        is_semantic_provider: bool = False,
    ) -> dict[str, Any]:
        """Search with explicit score provenance.

        mode: lexical | semantic | hybrid
        Semantic scores only when real query_vector + is_semantic_provider.
        """
        import math
        import struct
        import time

        q = query.strip()
        if not q:
            return {"memory": [], "mode": mode, "scores": [], "degraded": False}
        limit_n = max(1, min(int(limit), 100))
        started = time.perf_counter()
        mode_l = (mode or "lexical").strip().lower()
        if mode_l not in {"lexical", "semantic", "hybrid"}:
            mode_l = "lexical"

        lexical_hits = self.search(
            q,
            limit=limit_n * 3 if mode_l == "hybrid" else limit_n,
            scope=scope,
            conversation_id=conversation_id,
            project_id=project_id,
            workspace_id=workspace_id,
            user_id=user_id,
            include_global=include_global,
        )
        lexical_scores: dict[str, float] = {}
        for i, hit in enumerate(lexical_hits):
            # FTS returns rank order; approximate decreasing score.
            lexical_scores[hit.memory_id] = max(0.05, 1.0 - (i * 0.05))

        semantic_scores: dict[str, float] = {}
        degraded = False
        degrade_reason = None
        if mode_l in {"semantic", "hybrid"}:
            if not query_vector or not is_semantic_provider:
                degraded = True
                degrade_reason = (
                    "SEMANTIC_UNAVAILABLE"
                    if not query_vector
                    else "PROVIDER_NOT_SEMANTIC"
                )
                if mode_l == "semantic":
                    mode_l = "lexical"
            else:
                qnorm = math.sqrt(sum(v * v for v in query_vector)) or 1.0
                with self._lock:
                    with self.connect() as conn:
                        self._ensure_schema(conn)
                        # Scope-safe candidate set: FTS candidates first, else ACTIVE scoped.
                        candidate_ids = [h.memory_id for h in lexical_hits] if lexical_hits else []
                        if not candidate_ids:
                            scoped = self.list(
                                status=MemoryStatus.ACTIVE,
                                limit=min(200, limit_n * 10),
                                scope=scope,
                                conversation_id=conversation_id,
                                project_id=project_id,
                                workspace_id=workspace_id,
                                user_id=user_id,
                                include_global=include_global,
                            )
                            candidate_ids = [r.memory_id for r in scoped]
                        if candidate_ids:
                            placeholders = ",".join("?" * len(candidate_ids))
                            rows = conn.execute(
                                f"SELECT * FROM memory_embeddings WHERE stale = 0 "
                                f"AND memory_id IN ({placeholders})",
                                candidate_ids,
                            ).fetchall()
                            for row in rows:
                                dims = int(row["dimensions"])
                                if dims != len(query_vector):
                                    continue
                                vec = struct.unpack(f"{dims}f", row["vector_blob"])
                                dot = sum(a * b for a, b in zip(query_vector, vec))
                                vnorm = math.sqrt(sum(v * v for v in vec)) or 1.0
                                semantic_scores[row["memory_id"]] = max(
                                    0.0, min(1.0, dot / (qnorm * vnorm))
                                )

        combined: dict[str, float] = {}
        all_ids = set(lexical_scores) | set(semantic_scores)
        if mode_l == "lexical" or (degraded and not semantic_scores):
            combined = dict(lexical_scores)
            effective_mode = "lexical"
        elif mode_l == "semantic":
            combined = dict(semantic_scores)
            effective_mode = "semantic"
        else:
            # Hybrid: 0.55 lexical + 0.45 semantic when both exist.
            for mid in all_ids:
                lex = lexical_scores.get(mid, 0.0)
                sem = semantic_scores.get(mid, 0.0)
                if mid in lexical_scores and mid in semantic_scores:
                    combined[mid] = 0.55 * lex + 0.45 * sem
                elif mid in lexical_scores:
                    combined[mid] = 0.7 * lex
                else:
                    combined[mid] = 0.7 * sem
            effective_mode = "hybrid"

        ranked_ids = sorted(combined.keys(), key=lambda m: combined[m], reverse=True)[:limit_n]
        id_to_record: dict[str, MemoryRecord] = {h.memory_id: h for h in lexical_hits}
        missing = [mid for mid in ranked_ids if mid not in id_to_record]
        for mid in missing:
            rec = self.get(mid)
            if rec and rec.status == MemoryStatus.ACTIVE:
                id_to_record[mid] = rec

        results = []
        score_rows = []
        for mid in ranked_ids:
            rec = id_to_record.get(mid)
            if not rec:
                continue
            lex = lexical_scores.get(mid)
            sem = semantic_scores.get(mid)
            comb = combined.get(mid, 0.0)
            payload = rec.public_dict()
            payload["scores"] = {
                "lexical_score": lex,
                "semantic_score": sem if is_semantic_provider else None,
                "combined_score": comb,
                "relevance_pct": round(comb * 100.0, 1) if comb is not None else None,
            }
            results.append(payload)
            score_rows.append(payload["scores"])

        duration_ms = (time.perf_counter() - started) * 1000.0
        return {
            "memory": results,
            "mode": effective_mode,
            "requested_mode": mode,
            "degraded": degraded,
            "degrade_reason": degrade_reason,
            "duration_ms": round(duration_ms, 2),
            "truth": {
                "scope_filter_required_for_retrieval": True,
                "hash_vectors_are_not_semantic_embeddings": not is_semantic_provider,
                "relevance_requires_query_context": True,
            },
        }

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
