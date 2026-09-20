from __future__ import annotations

import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
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

    def create_conversation(self, title: str = "New conversation") -> dict:
        conversation_id = str(uuid.uuid4())
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO conversations(id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (conversation_id, title, now, now),
            )
        return {"id": conversation_id, "title": title, "created_at": now, "updated_at": now}

    def list_conversations(self, limit: int = 50) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_conversation(self, conversation_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        return dict(row) if row else None

    def set_conversation_title(self, conversation_id: str, title: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title[:120], utc_now(), conversation_id),
            )

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
        document_id = document_id or str(uuid.uuid4())
        now = utc_now()
        with self.connect() as conn:
            existing = conn.execute("SELECT created_at FROM knowledge_documents WHERE id = ?", (document_id,)).fetchone()
            created_at = existing["created_at"] if existing else now
            conn.execute(
                """
                INSERT INTO knowledge_documents(id, title, content, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    content = excluded.content,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (document_id, title, content, source, created_at, now),
            )
            try:
                conn.execute("DELETE FROM knowledge_fts WHERE document_id = ?", (document_id,))
                conn.execute(
                    "INSERT INTO knowledge_fts(document_id, title, content) VALUES (?, ?, ?)",
                    (document_id, title, content),
                )
            except sqlite3.OperationalError:
                pass
        return {
            "id": document_id,
            "title": title,
            "content": content,
            "source": source,
            "created_at": created_at,
            "updated_at": now,
        }

    def list_knowledge(self, limit: int = 100) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, title, content, source, created_at, updated_at FROM knowledge_documents ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def search_knowledge(self, query: str, limit: int = 5) -> list[dict]:
        tokens = re.findall(r"[\w-]{2,}", query.lower(), flags=re.UNICODE)[:12]
        if not tokens:
            return []
        fts_query = " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)
        with self.connect() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT d.id, d.title, d.content, d.source, d.created_at, d.updated_at,
                           bm25(knowledge_fts) AS rank
                    FROM knowledge_fts
                    JOIN knowledge_documents d ON d.id = knowledge_fts.document_id
                    WHERE knowledge_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_query, limit),
                ).fetchall()
                return [dict(row) for row in rows]
            except sqlite3.OperationalError:
                pattern = "%" + "%".join(tokens[:4]) + "%"
                rows = conn.execute(
                    """
                    SELECT id, title, content, source, created_at, updated_at
                    FROM knowledge_documents
                    WHERE lower(title) LIKE ? OR lower(content) LIKE ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (pattern, pattern, limit),
                ).fetchall()
                return [dict(row) for row in rows]

    def delete_knowledge(self, document_id: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM knowledge_documents WHERE id = ?", (document_id,))
            try:
                conn.execute("DELETE FROM knowledge_fts WHERE document_id = ?", (document_id,))
            except sqlite3.OperationalError:
                pass
            return cursor.rowcount > 0
