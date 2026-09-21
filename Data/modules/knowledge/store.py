from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .chunking import chunk_text
from .hashing import content_sha256, estimate_tokens, file_sha256
from .types import ChunkRecord, DocumentRecord, IngestStatus

INGEST_VERSION = 2
PARSER_VERSION = "1.0.0"
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".rst", ".csv", ".json", ".log"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


class KnowledgeStore:
    """Canonical Knowledge V2 owner: documents, chunks, provenance, ingest states."""

    def __init__(
        self,
        path: Path,
        *,
        data_root: Path | None = None,
        chunk_max_chars: int = 1200,
        chunk_overlap: int = 120,
    ) -> None:
        self.path = path
        self.data_root = data_root
        self.chunk_max_chars = chunk_max_chars
        self.chunk_overlap = chunk_overlap
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
            self._ensure_schema(conn)

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_documents (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        columns = _table_columns(conn, "knowledge_documents")
        alterations = {
            "status": "TEXT NOT NULL DEFAULT 'READY'",
            "content_hash": "TEXT",
            "original_path": "TEXT",
            "source_mtime": "TEXT",
            "size_bytes": "INTEGER",
            "parser": "TEXT NOT NULL DEFAULT 'plain_text'",
            "parser_version": "TEXT NOT NULL DEFAULT '1.0.0'",
            "ingest_version": "INTEGER NOT NULL DEFAULT 1",
            "trust_metadata_json": "TEXT NOT NULL DEFAULT '{}'",
            "error": "TEXT",
        }
        for name, ddl in alterations.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE knowledge_documents ADD COLUMN {name} {ddl}")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                chunk_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                token_estimate INTEGER NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(document_id, chunk_index),
                FOREIGN KEY(document_id) REFERENCES knowledge_documents(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document ON knowledge_chunks(document_id, chunk_index)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_ingest_files (
                path TEXT PRIMARY KEY,
                size_bytes INTEGER NOT NULL,
                mtime TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                document_id TEXT,
                status TEXT NOT NULL,
                parser_version TEXT NOT NULL,
                ingest_version INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
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
            pass
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunk_fts
                USING fts5(chunk_id UNINDEXED, document_id UNINDEXED, title, content)
                """
            )
        except sqlite3.OperationalError:
            pass

        # Backfill V1 documents missing hashes/chunks into READY V2 shape.
        rows = conn.execute(
            """
            SELECT id, title, content, source, created_at, updated_at,
                   content_hash, status
            FROM knowledge_documents
            """
        ).fetchall()
        for row in rows:
            doc_id = row["id"]
            content = row["content"] or ""
            content_hash = row["content_hash"] or content_sha256(content)
            status = row["status"] or IngestStatus.READY.value
            if not row["content_hash"]:
                conn.execute(
                    "UPDATE knowledge_documents SET content_hash = ?, status = ?, parser = COALESCE(parser, 'plain_text'), ingest_version = COALESCE(ingest_version, 1) WHERE id = ?",
                    (content_hash, status, doc_id),
                )
            chunk_count = conn.execute(
                "SELECT COUNT(*) AS c FROM knowledge_chunks WHERE document_id = ?",
                (doc_id,),
            ).fetchone()["c"]
            if chunk_count == 0 and content.strip() and status == IngestStatus.READY.value:
                self._replace_chunks(
                    conn,
                    document_id=doc_id,
                    title=row["title"],
                    content=content,
                )

    def upsert_document(
        self,
        *,
        title: str,
        content: str,
        source: str = "manual",
        document_id: str | None = None,
        original_path: str | None = None,
        source_mtime: str | None = None,
        size_bytes: int | None = None,
        parser: str = "plain_text",
        trust_metadata: dict[str, Any] | None = None,
    ) -> DocumentRecord:
        """Ingest text atomically: INDEXING → chunks → READY, or FAILED."""
        document_id = document_id or str(uuid.uuid4())
        now = utc_now()
        digest = content_sha256(content)
        trust = trust_metadata or {"trust": "manual"}

        with self.connect() as conn:
            self._ensure_schema(conn)
            existing = conn.execute(
                "SELECT created_at FROM knowledge_documents WHERE id = ?",
                (document_id,),
            ).fetchone()
            created_at = existing["created_at"] if existing else now

            conn.execute(
                """
                INSERT INTO knowledge_documents(
                    id, title, content, source, created_at, updated_at,
                    status, content_hash, original_path, source_mtime, size_bytes,
                    parser, parser_version, ingest_version, trust_metadata_json, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    content = excluded.content,
                    source = excluded.source,
                    updated_at = excluded.updated_at,
                    status = excluded.status,
                    content_hash = excluded.content_hash,
                    original_path = excluded.original_path,
                    source_mtime = excluded.source_mtime,
                    size_bytes = excluded.size_bytes,
                    parser = excluded.parser,
                    parser_version = excluded.parser_version,
                    ingest_version = excluded.ingest_version,
                    trust_metadata_json = excluded.trust_metadata_json,
                    error = NULL
                """,
                (
                    document_id,
                    title,
                    content,
                    source,
                    created_at,
                    now,
                    IngestStatus.INDEXING.value,
                    digest,
                    original_path,
                    source_mtime,
                    size_bytes if size_bytes is not None else len(content.encode("utf-8")),
                    parser,
                    PARSER_VERSION,
                    INGEST_VERSION,
                    json.dumps(trust),
                ),
            )

            try:
                self._replace_chunks(conn, document_id=document_id, title=title, content=content)
                # Document FTS (legacy whole-doc index)
                try:
                    conn.execute("DELETE FROM knowledge_fts WHERE document_id = ?", (document_id,))
                    conn.execute(
                        "INSERT INTO knowledge_fts(document_id, title, content) VALUES (?, ?, ?)",
                        (document_id, title, content),
                    )
                except sqlite3.OperationalError:
                    pass
                conn.execute(
                    "UPDATE knowledge_documents SET status = ?, updated_at = ?, error = NULL WHERE id = ?",
                    (IngestStatus.READY.value, utc_now(), document_id),
                )
            except Exception as exc:  # noqa: BLE001 — mark FAILED, re-raise as store error shape
                conn.execute(
                    "UPDATE knowledge_documents SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                    (IngestStatus.FAILED.value, str(exc), utc_now(), document_id),
                )
                raise

        record = self.get_document(document_id)
        assert record is not None
        return record

    def _replace_chunks(self, conn: sqlite3.Connection, *, document_id: str, title: str, content: str) -> list[ChunkRecord]:
        conn.execute("DELETE FROM knowledge_chunks WHERE document_id = ?", (document_id,))
        try:
            conn.execute("DELETE FROM knowledge_chunk_fts WHERE document_id = ?", (document_id,))
        except sqlite3.OperationalError:
            pass

        parts = chunk_text(content, max_chars=self.chunk_max_chars, overlap=self.chunk_overlap)
        records: list[ChunkRecord] = []
        for index, part in enumerate(parts):
            chunk_id = str(uuid.uuid4())
            digest = content_sha256(part)
            tokens = estimate_tokens(part)
            conn.execute(
                """
                INSERT INTO knowledge_chunks(
                    chunk_id, document_id, chunk_index, content, content_hash, token_estimate, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (chunk_id, document_id, index, part, digest, tokens, json.dumps({"title": title})),
            )
            try:
                conn.execute(
                    "INSERT INTO knowledge_chunk_fts(chunk_id, document_id, title, content) VALUES (?, ?, ?, ?)",
                    (chunk_id, document_id, title, part),
                )
            except sqlite3.OperationalError:
                pass
            records.append(
                ChunkRecord(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    chunk_index=index,
                    content=part,
                    content_hash=digest,
                    token_estimate=tokens,
                    metadata={"title": title},
                )
            )
        return records

    def get_document(self, document_id: str) -> DocumentRecord | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute("SELECT * FROM knowledge_documents WHERE id = ?", (document_id,)).fetchone()
        return self._row_to_document(row) if row else None

    def list_documents(self, limit: int = 100, *, status: IngestStatus | None = None) -> list[DocumentRecord]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            if status is None:
                rows = conn.execute(
                    "SELECT * FROM knowledge_documents ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM knowledge_documents WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                    (status.value, limit),
                ).fetchall()
        return [self._row_to_document(row) for row in rows]

    def list_chunks(self, document_id: str) -> list[ChunkRecord]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT chunk_id, document_id, chunk_index, content, content_hash, token_estimate, metadata_json
                FROM knowledge_chunks
                WHERE document_id = ?
                ORDER BY chunk_index ASC
                """,
                (document_id,),
            ).fetchall()
        return [
            ChunkRecord(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                chunk_index=row["chunk_index"],
                content=row["content"],
                content_hash=row["content_hash"],
                token_estimate=row["token_estimate"],
                metadata=json.loads(row["metadata_json"] or "{}"),
            )
            for row in rows
        ]

    def delete_document(self, document_id: str) -> bool:
        with self.connect() as conn:
            self._ensure_schema(conn)
            try:
                conn.execute("DELETE FROM knowledge_chunk_fts WHERE document_id = ?", (document_id,))
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("DELETE FROM knowledge_fts WHERE document_id = ?", (document_id,))
            except sqlite3.OperationalError:
                pass
            conn.execute("DELETE FROM knowledge_chunks WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM knowledge_ingest_files WHERE document_id = ?", (document_id,))
            cursor = conn.execute("DELETE FROM knowledge_documents WHERE id = ?", (document_id,))
            return cursor.rowcount > 0

    def resolve_under_data_root(self, relative_or_absolute: str) -> Path:
        if self.data_root is None:
            raise ValueError("Knowledge data_root is not configured")
        raw = Path(relative_or_absolute)
        if raw.is_absolute():
            candidate = raw.resolve()
        else:
            candidate = (self.data_root / raw).resolve()
        root = self.data_root.resolve() if self.data_root.exists() else self.data_root
        # On POSIX with Windows-style D:/ModelData, resolve may not exist — use string prefix guard.
        try:
            candidate.relative_to(root.resolve() if root.exists() else root)
        except ValueError as exc:
            # Fallback string check for non-existing Windows roots on Linux.
            cand_s = str(candidate).replace("\\", "/")
            root_s = str(self.data_root).replace("\\", "/")
            if not (cand_s == root_s or cand_s.startswith(root_s.rstrip("/") + "/")):
                raise ValueError("Path escapes configured LEVIATHAN_DATA_ROOT") from exc
        return candidate

    def ingest_file(self, path: Path, *, source: str = "modeldata") -> DocumentRecord | None:
        """Incremental file ingest. Returns None when unchanged."""
        if not path.is_file():
            raise FileNotFoundError(str(path))
        if path.suffix.lower() not in TEXT_SUFFIXES:
            raise ValueError(f"Unsupported knowledge file type for V2 plain parser: {path.suffix}")

        data = path.read_bytes()
        text = data.decode("utf-8", errors="replace")
        digest = file_sha256(data)
        stat = path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
        path_key = str(path)

        with self.connect() as conn:
            self._ensure_schema(conn)
            existing = conn.execute(
                "SELECT content_hash, document_id, status FROM knowledge_ingest_files WHERE path = ?",
                (path_key,),
            ).fetchone()
            if (
                existing
                and existing["content_hash"] == digest
                and existing["status"] == IngestStatus.READY.value
                and existing["document_id"]
            ):
                return self.get_document(existing["document_id"])

            conn.execute(
                """
                INSERT INTO knowledge_ingest_files(
                    path, size_bytes, mtime, content_hash, document_id, status,
                    parser_version, ingest_version, updated_at
                ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    size_bytes = excluded.size_bytes,
                    mtime = excluded.mtime,
                    content_hash = excluded.content_hash,
                    status = excluded.status,
                    parser_version = excluded.parser_version,
                    ingest_version = excluded.ingest_version,
                    updated_at = excluded.updated_at
                """,
                (
                    path_key,
                    stat.st_size,
                    mtime,
                    digest,
                    IngestStatus.PARSING.value,
                    PARSER_VERSION,
                    INGEST_VERSION,
                    utc_now(),
                ),
            )

        document_id = existing["document_id"] if existing and existing["document_id"] else str(uuid.uuid4())
        title = path.stem.replace("_", " ").strip() or path.name
        record = self.upsert_document(
            document_id=document_id,
            title=title,
            content=text,
            source=source,
            original_path=path_key,
            source_mtime=mtime,
            size_bytes=stat.st_size,
            parser="plain_text",
            trust_metadata={"trust": "local_file", "root": str(self.data_root)},
        )

        with self.connect() as conn:
            conn.execute(
                """
                UPDATE knowledge_ingest_files
                SET document_id = ?, status = ?, updated_at = ?
                WHERE path = ?
                """,
                (record.document_id, record.status.value, utc_now(), path_key),
            )
        return record

    def scan_data_root(self, *, limit: int = 100) -> list[DocumentRecord]:
        """Scan configured data root for supported text files and ingest incrementally."""
        if self.data_root is None:
            raise ValueError("Knowledge data_root is not configured")
        root = self.data_root
        if not root.exists() or not root.is_dir():
            return []

        results: list[DocumentRecord] = []
        count = 0
        for path in sorted(root.rglob("*")):
            if count >= limit:
                break
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            # Skip huge files in V2 plain path (> 5 MiB) — stream later.
            if path.stat().st_size > 5 * 1024 * 1024:
                continue
            record = self.ingest_file(path)
            if record is not None:
                results.append(record)
                count += 1
        return results

    def search_lexical(
        self,
        query: str,
        *,
        limit: int = 5,
        source: str | None = None,
        status: IngestStatus = IngestStatus.READY,
    ) -> list[dict[str, Any]]:
        """Chunk-level lexical search with document provenance."""
        tokens = re.findall(r"[\w-]{2,}", query.lower(), flags=re.UNICODE)[:12]
        if not tokens:
            return []
        fts_query = " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)

        with self.connect() as conn:
            self._ensure_schema(conn)
            try:
                rows = conn.execute(
                    """
                    SELECT c.chunk_id, c.document_id, c.chunk_index, c.content AS chunk_content,
                           c.content_hash AS chunk_hash, c.token_estimate,
                           d.title, d.source, d.content AS document_content,
                           d.created_at, d.updated_at, d.original_path, d.content_hash AS document_hash,
                           d.status, bm25(knowledge_chunk_fts) AS rank
                    FROM knowledge_chunk_fts
                    JOIN knowledge_chunks c ON c.chunk_id = knowledge_chunk_fts.chunk_id
                    JOIN knowledge_documents d ON d.id = c.document_id
                    WHERE knowledge_chunk_fts MATCH ?
                      AND d.status = ?
                      AND (? IS NULL OR d.source = ?)
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_query, status.value, source, source, limit),
                ).fetchall()
                return [dict(row) for row in rows]
            except sqlite3.OperationalError:
                pattern = "%" + "%".join(tokens[:4]) + "%"
                rows = conn.execute(
                    """
                    SELECT c.chunk_id, c.document_id, c.chunk_index, c.content AS chunk_content,
                           c.content_hash AS chunk_hash, c.token_estimate,
                           d.title, d.source, d.content AS document_content,
                           d.created_at, d.updated_at, d.original_path, d.content_hash AS document_hash,
                           d.status, 0.0 AS rank
                    FROM knowledge_chunks c
                    JOIN knowledge_documents d ON d.id = c.document_id
                    WHERE d.status = ?
                      AND (? IS NULL OR d.source = ?)
                      AND (lower(d.title) LIKE ? OR lower(c.content) LIKE ?)
                    ORDER BY d.updated_at DESC
                    LIMIT ?
                    """,
                    (status.value, source, source, pattern, pattern, limit),
                ).fetchall()
                return [dict(row) for row in rows]

    @staticmethod
    def _row_to_document(row: sqlite3.Row) -> DocumentRecord:
        status_raw = row["status"] if "status" in row.keys() and row["status"] else IngestStatus.READY.value
        try:
            status = IngestStatus(status_raw)
        except ValueError:
            status = IngestStatus.READY
        trust_raw = row["trust_metadata_json"] if "trust_metadata_json" in row.keys() else "{}"
        return DocumentRecord(
            document_id=row["id"],
            title=row["title"],
            content=row["content"],
            source=row["source"],
            status=status,
            content_hash=row["content_hash"] if "content_hash" in row.keys() and row["content_hash"] else content_sha256(row["content"]),
            original_path=row["original_path"] if "original_path" in row.keys() else None,
            source_mtime=row["source_mtime"] if "source_mtime" in row.keys() else None,
            size_bytes=row["size_bytes"] if "size_bytes" in row.keys() else None,
            parser=row["parser"] if "parser" in row.keys() and row["parser"] else "plain_text",
            parser_version=row["parser_version"] if "parser_version" in row.keys() and row["parser_version"] else PARSER_VERSION,
            ingest_version=int(row["ingest_version"]) if "ingest_version" in row.keys() and row["ingest_version"] is not None else 1,
            trust_metadata=json.loads(trust_raw or "{}"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            error=row["error"] if "error" in row.keys() else None,
        )
