from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from Data.modules.common.sqlite_policy import open_sqlite_connection, ensure_wal


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path, *, knowledge_path: Path | None = None) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._knowledge_path_override = Path(knowledge_path) if knowledge_path is not None else None
        self._wal_ready = False

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        # Hot path: busy_timeout yes; WAL only once during initialize.
        conn = open_sqlite_connection(self.path, set_wal=False)
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
        with self.connect() as conn:
            if not self._wal_ready:
                ensure_wal(conn)
                self._wal_ready = True
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('system', 'user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_messages_conversation
                    ON messages(conversation_id, id);
                """
            )
            # Knowledge tables must NOT materialize on CONTROL (three-DB ownership).
            # Legacy installs that already have them are reconciled by db_upgrade.
            # Idempotent upgrade for DBs created before pinned column existed.
            cols = {row[1] for row in conn.execute("PRAGMA table_info(conversations)").fetchall()}
            if "pinned" not in cols:
                conn.execute(
                    "ALTER TABLE conversations ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"
                )

    def _conversation_row(self, row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        data = dict(row)
        data["pinned"] = bool(data.get("pinned") or 0)
        return data

    def create_conversation(self, title: str = "New conversation") -> dict:
        conversation_id = str(uuid.uuid4())
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO conversations(id, title, created_at, updated_at, pinned) VALUES (?, ?, ?, ?, 0)",
                (conversation_id, title, now, now),
            )
        return {
            "id": conversation_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "pinned": False,
        }

    def list_conversations(self, limit: int = 50, *, q: str | None = None) -> list[dict]:
        page = self.list_conversations_page(limit=limit, q=q)
        return page["items"]

    def list_conversations_page(
        self,
        *,
        limit: int = 50,
        q: str | None = None,
        cursor: str | None = None,
    ) -> dict:
        """Cursor-paginated conversation catalog.

        Cursor format: ``{pinned}|{updated_at}|{id}`` where pinned is 0|1.
        Ordering: pinned DESC, updated_at DESC, id DESC (deterministic).
        """
        limit = max(1, min(int(limit), 200))
        with self.connect() as conn:
            params: list = []
            where_parts: list[str] = []
            if q and q.strip():
                where_parts.append("title LIKE ?")
                params.append(f"%{q.strip()}%")
            if cursor:
                try:
                    pinned_s, updated_at, cid = cursor.split("|", 2)
                    pinned_v = int(pinned_s)
                except ValueError as exc:
                    raise ValueError("invalid conversation cursor") from exc
                # Keyset: (pinned, updated_at, id) lexicographic under DESC order.
                where_parts.append(
                    "("
                    "pinned < ? OR "
                    "(pinned = ? AND updated_at < ?) OR "
                    "(pinned = ? AND updated_at = ? AND id < ?)"
                    ")"
                )
                params.extend([pinned_v, pinned_v, updated_at, pinned_v, updated_at, cid])
            where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
            rows = conn.execute(
                f"""
                SELECT id, title, created_at, updated_at, pinned
                FROM conversations
                {where_sql}
                ORDER BY pinned DESC, updated_at DESC, id DESC
                LIMIT ?
                """,
                (*params, limit + 1),
            ).fetchall()
            items = [self._conversation_row(row) for row in rows[:limit]]  # type: ignore[misc]
            has_more = len(rows) > limit
            next_cursor = None
            if has_more and items:
                last = items[-1]
                next_cursor = f"{1 if last.get('pinned') else 0}|{last['updated_at']}|{last['id']}"
            # Total count only when cheap (no cursor / unbounded search avoided).
            total = None
            if cursor is None:
                if q and q.strip():
                    total_row = conn.execute(
                        "SELECT COUNT(*) AS c FROM conversations WHERE title LIKE ?",
                        (f"%{q.strip()}%",),
                    ).fetchone()
                else:
                    total_row = conn.execute("SELECT COUNT(*) AS c FROM conversations").fetchone()
                total = int(total_row[0] if not isinstance(total_row, sqlite3.Row) else total_row["c"])
        return {
            "items": items,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "total": total,
        }

    def get_conversation(self, conversation_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id, title, created_at, updated_at, pinned FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        return self._conversation_row(row)

    def set_conversation_title(self, conversation_id: str, title: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title[:120], utc_now(), conversation_id),
            )

    def update_conversation(
        self,
        conversation_id: str,
        *,
        title: str | None = None,
        pinned: bool | None = None,
    ) -> dict | None:
        existing = self.get_conversation(conversation_id)
        if existing is None:
            return None
        new_title = existing["title"] if title is None else title.strip()[:120]
        new_pinned = existing["pinned"] if pinned is None else bool(pinned)
        if not new_title:
            new_title = existing["title"]
        with self.connect() as conn:
            conn.execute(
                "UPDATE conversations SET title = ?, pinned = ?, updated_at = ? WHERE id = ?",
                (new_title, 1 if new_pinned else 0, utc_now(), conversation_id),
            )
        return self.get_conversation(conversation_id)

    def delete_conversation(self, conversation_id: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            return cursor.rowcount > 0

    def add_message(self, conversation_id: str, role: str, content: str) -> dict:
        now = utc_now()
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO messages(conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (conversation_id, role, content, now),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
            message_id = int(cursor.lastrowid)
        return {"id": message_id, "conversation_id": conversation_id, "role": role, "content": content, "created_at": now}

    def get_messages(self, conversation_id: str, limit: int = 100) -> list[dict]:
        page = self.get_messages_page(conversation_id, limit=limit)
        return page["items"]

    def get_messages_page(
        self,
        conversation_id: str,
        *,
        limit: int = 100,
        before_id: int | None = None,
        after_id: int | None = None,
    ) -> dict:
        """Paginated message history.

        Default: most recent ``limit`` messages (ascending within page).
        ``before_id``: older page (scroll upward) — messages with id < before_id.
        ``after_id``: newer page — messages with id > after_id.
        """
        limit = max(1, min(int(limit), 500))
        with self.connect() as conn:
            if before_id is not None:
                rows = conn.execute(
                    """
                    SELECT id, conversation_id, role, content, created_at
                    FROM (
                        SELECT id, conversation_id, role, content, created_at
                        FROM messages
                        WHERE conversation_id = ? AND id < ?
                        ORDER BY id DESC
                        LIMIT ?
                    )
                    ORDER BY id ASC
                    """,
                    (conversation_id, int(before_id), limit + 1),
                ).fetchall()
                raw = [dict(row) for row in rows]
                has_more = len(raw) > limit
                items = raw[-limit:] if has_more else raw
                next_before = items[0]["id"] if has_more and items else None
                return {
                    "items": items,
                    "has_more": has_more,
                    "next_before_id": next_before,
                    "next_after_id": None,
                }
            if after_id is not None:
                rows = conn.execute(
                    """
                    SELECT id, conversation_id, role, content, created_at
                    FROM messages
                    WHERE conversation_id = ? AND id > ?
                    ORDER BY id ASC
                    LIMIT ?
                    """,
                    (conversation_id, int(after_id), limit + 1),
                ).fetchall()
                raw = [dict(row) for row in rows]
                has_more = len(raw) > limit
                items = raw[:limit]
                return {
                    "items": items,
                    "has_more": has_more,
                    "next_before_id": None,
                    "next_after_id": items[-1]["id"] if has_more and items else None,
                }
            # Recent window.
            rows = conn.execute(
                """
                SELECT id, conversation_id, role, content, created_at
                FROM (
                    SELECT id, conversation_id, role, content, created_at
                    FROM messages
                    WHERE conversation_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                )
                ORDER BY id ASC
                """,
                (conversation_id, limit + 1),
            ).fetchall()
            raw = [dict(row) for row in rows]
            # We fetched limit+1 newest; if more than limit, older exist.
            has_more = len(raw) > limit
            items = raw[-limit:] if has_more else raw
            next_before = items[0]["id"] if has_more and items else None
            return {
                "items": items,
                "has_more": has_more,
                "next_before_id": next_before,
                "next_after_id": None,
            }

    def count_messages(self, conversation_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return int(row[0] if not isinstance(row, sqlite3.Row) else row["c"])

    def upsert_knowledge(self, title: str, content: str, source: str = "manual", document_id: str | None = None) -> dict:
        from Data.modules.knowledge import KnowledgeStore

        store = KnowledgeStore(self._knowledge_db_path())
        store.initialize()
        record = store.upsert_document(
            title=title,
            content=content,
            source=source,
            document_id=document_id,
        )
        return record.legacy_dict()

    def list_knowledge(self, limit: int = 100) -> list[dict]:
        from Data.modules.knowledge import KnowledgeStore

        store = KnowledgeStore(self._knowledge_db_path())
        store.initialize()
        return [item.legacy_dict() for item in store.list_documents(limit=limit)]

    def search_knowledge(self, query: str, limit: int = 5) -> list[dict]:
        from Data.modules.knowledge import HybridRetriever, KnowledgeStore, RetrievalQuery

        store = KnowledgeStore(self._knowledge_db_path())
        store.initialize()
        hits = HybridRetriever(store).search(RetrievalQuery(text=query, limit=limit))
        return [hit.as_context_document() for hit in hits]

    def delete_knowledge(self, document_id: str) -> bool:
        from Data.modules.knowledge import KnowledgeStore

        store = KnowledgeStore(self._knowledge_db_path())
        store.initialize()
        return store.delete_document(document_id)

    def _knowledge_db_path(self) -> Path:
        """Legacy Database facade must never write Knowledge tables into CONTROL."""
        override = getattr(self, "_knowledge_path_override", None)
        if override is not None:
            return Path(override)
        try:
            from Data.backend.config import load_settings

            return Path(load_settings().knowledge_database_path)
        except Exception:  # noqa: BLE001
            # Test/single-file fixtures: sibling knowledge DB next to CONTROL.
            return self.path.parent / "leviathan_knowledge.db"
