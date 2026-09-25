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
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
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

                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'manual',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            try:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts
                    USING fts5(document_id UNINDEXED, title, content)
                    """
                )
            except sqlite3.OperationalError:
                # Some stripped SQLite builds omit FTS5. Search falls back to LIKE.
                pass
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
        with self.connect() as conn:
            if q and q.strip():
                like = f"%{q.strip()}%"
                rows = conn.execute(
                    """
                    SELECT id, title, created_at, updated_at, pinned
                    FROM conversations
                    WHERE title LIKE ?
                    ORDER BY pinned DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (like, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, title, created_at, updated_at, pinned
                    FROM conversations
                    ORDER BY pinned DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [self._conversation_row(row) for row in rows]  # type: ignore[misc]

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
        with self.connect() as conn:
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
                (conversation_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_knowledge(self, title: str, content: str, source: str = "manual", document_id: str | None = None) -> dict:
        from Data.modules.knowledge import KnowledgeStore

        store = KnowledgeStore(self.path)
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

        store = KnowledgeStore(self.path)
        store.initialize()
        return [item.legacy_dict() for item in store.list_documents(limit=limit)]

    def search_knowledge(self, query: str, limit: int = 5) -> list[dict]:
        from Data.modules.knowledge import HybridRetriever, KnowledgeStore, RetrievalQuery

        store = KnowledgeStore(self.path)
        store.initialize()
        hits = HybridRetriever(store).search(RetrievalQuery(text=query, limit=limit))
        return [hit.as_context_document() for hit in hits]

    def delete_knowledge(self, document_id: str) -> bool:
        from Data.modules.knowledge import KnowledgeStore

        store = KnowledgeStore(self.path)
        store.initialize()
        return store.delete_document(document_id)
