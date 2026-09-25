from __future__ import annotations

import json
import re
import sqlite3
import struct
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .chunking import chunk_text_spans
from .embeddings import EmbeddingProvider, NullEmbeddingProvider, cosine_similarity
from .hashing import content_sha256, estimate_tokens, file_sha256
from .types import ChunkRecord, DirectionalRelationAtom, DocumentRecord, IngestStatus, RelationClass

INGEST_VERSION = 3
PARSER_VERSION = "1.0.0"
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".rst", ".csv", ".json", ".log"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _pack_embedding(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack_embedding(blob: bytes) -> list[float]:
    if not blob:
        return []
    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob))


class KnowledgeStore:
    """Canonical Knowledge V2/V3 owner: documents, chunks, provenance, ingest states."""

    def __init__(
        self,
        path: Path,
        *,
        data_root: Path | None = None,
        chunk_max_chars: int = 1200,
        chunk_overlap: int = 120,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.path = path
        self.data_root = data_root
        self.chunk_max_chars = chunk_max_chars
        self.chunk_overlap = chunk_overlap
        self.embedding_provider = embedding_provider or NullEmbeddingProvider()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        from Data.modules.common.sqlite_policy import open_sqlite_connection

        # Hot path: busy_timeout yes; journal_mode set during initialize only.
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
        from Data.modules.common.sqlite_policy import ensure_wal

        with self.connect() as conn:
            ensure_wal(conn)
            self._ensure_schema(conn)

    def initialize_schema(self) -> None:
        """Alias for :meth:`initialize` — DDL only."""
        self.initialize()

    def count_pending_content_backfill(self) -> int:
        """Documents READY with content but zero chunks (legacy V1 shape)."""
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM knowledge_documents d
                WHERE COALESCE(d.status, 'READY') = 'READY'
                  AND LENGTH(TRIM(COALESCE(d.content, ''))) > 0
                  AND NOT EXISTS (
                    SELECT 1 FROM knowledge_chunks c WHERE c.document_id = d.id
                  )
                """
            ).fetchone()
            return int(row["c"] if row else 0)

    def backfill_content(self, *, limit: int = 50) -> dict[str, Any]:
        """Resumable content backfill — chunk (+ embed) legacy docs lacking chunks.

        Safe to call from a knowledge_prepare worker. Idempotent per document.
        """
        safe_limit = min(max(int(limit), 1), 500)
        processed: list[str] = []
        errors: list[dict[str, str]] = []
        with self.connect() as conn:
            self._ensure_schema(conn)
            # Hash-only fixes (no chunk work) — cheap, keep inline with backfill job.
            missing_hash = conn.execute(
                """
                SELECT id, content FROM knowledge_documents
                WHERE content_hash IS NULL OR content_hash = ''
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
            for row in missing_hash:
                content = row["content"] or ""
                conn.execute(
                    "UPDATE knowledge_documents SET content_hash = ?, "
                    "parser = COALESCE(parser, 'plain_text'), "
                    "ingest_version = COALESCE(ingest_version, 1) WHERE id = ?",
                    (content_sha256(content), row["id"]),
                )
            rows = conn.execute(
                """
                SELECT d.id, d.title, d.content, d.source, d.content_hash,
                       d.original_path, d.source_mtime, d.status
                FROM knowledge_documents d
                WHERE COALESCE(d.status, 'READY') = 'READY'
                  AND LENGTH(TRIM(COALESCE(d.content, ''))) > 0
                  AND NOT EXISTS (
                    SELECT 1 FROM knowledge_chunks c WHERE c.document_id = d.id
                  )
                ORDER BY d.updated_at ASC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
            for row in rows:
                doc_id = row["id"]
                content = row["content"] or ""
                content_hash = row["content_hash"] or content_sha256(content)
                try:
                    self._replace_chunks(
                        conn,
                        document_id=doc_id,
                        title=row["title"],
                        content=content,
                        original_path=row["original_path"] if "original_path" in row.keys() else None,
                        source_mtime=row["source_mtime"] if "source_mtime" in row.keys() else None,
                        document_hash=content_hash,
                        source=row["source"] or "manual",
                    )
                    processed.append(doc_id)
                except Exception as exc:  # noqa: BLE001
                    errors.append({"document_id": doc_id, "error": str(exc)[:300]})
                    conn.execute(
                        "UPDATE knowledge_documents SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                        (IngestStatus.FAILED.value, str(exc)[:500], utc_now(), doc_id),
                    )
        remaining = self.count_pending_content_backfill()
        return {
            "processed": len(processed),
            "document_ids": processed,
            "errors": errors,
            "remaining": remaining,
            "status": "KNOWLEDGE_BACKFILL_PENDING" if remaining else "KNOWLEDGE_BACKFILL_DONE",
        }

    def stage_document(
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
        """Persist document metadata + content as INDEXING without chunking/embedding.

        Control-plane safe: bounded SQLite write only. Worker calls
        :meth:`prepare_staged_document` to finish.
        """
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
        record = self.get_document(document_id)
        assert record is not None
        return record

    def prepare_staged_document(self, document_id: str) -> DocumentRecord:
        """Chunk + embed a previously staged INDEXING document (worker-side)."""
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM knowledge_documents WHERE id = ?",
                (document_id,),
            ).fetchone()
            if row is None:
                raise KeyError(document_id)
            content = row["content"] or ""
            content_hash = row["content_hash"] or content_sha256(content)
            try:
                self._replace_chunks(
                    conn,
                    document_id=document_id,
                    title=row["title"],
                    content=content,
                    original_path=row["original_path"] if "original_path" in row.keys() else None,
                    source_mtime=row["source_mtime"] if "source_mtime" in row.keys() else None,
                    document_hash=content_hash,
                    source=row["source"] or "manual",
                )
                conn.execute(
                    "UPDATE knowledge_documents SET status = ?, error = NULL, updated_at = ? WHERE id = ?",
                    (IngestStatus.READY.value, utc_now(), document_id),
                )
            except Exception as exc:  # noqa: BLE001
                conn.execute(
                    "UPDATE knowledge_documents SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                    (IngestStatus.FAILED.value, str(exc)[:500], utc_now(), document_id),
                )
                raise
        record = self.get_document(document_id)
        assert record is not None
        return record

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
        chunk_cols = _table_columns(conn, "knowledge_chunks")
        for name, ddl in {
            "start_offset": "INTEGER NOT NULL DEFAULT 0",
            "end_offset": "INTEGER NOT NULL DEFAULT 0",
            "confidence": "REAL NOT NULL DEFAULT 1.0",
            "uncertainty_notes": "TEXT NOT NULL DEFAULT ''",
            "source_type": "TEXT NOT NULL DEFAULT 'document'",
            "provenance_json": "TEXT NOT NULL DEFAULT '{}'",
        }.items():
            if name not in chunk_cols:
                conn.execute(f"ALTER TABLE knowledge_chunks ADD COLUMN {name} {ddl}")

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document ON knowledge_chunks(document_id, chunk_index)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_documents_content_hash "
            "ON knowledge_documents(content_hash)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_content_hash "
            "ON knowledge_chunks(content_hash)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_documents_updated "
            "ON knowledge_documents(updated_at)"
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_chunk_embeddings (
                chunk_id TEXT PRIMARY KEY,
                provider_id TEXT NOT NULL,
                dimensions INTEGER NOT NULL,
                embedding BLOB NOT NULL,
                content_hash TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(chunk_id) REFERENCES knowledge_chunks(chunk_id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS directional_relation_atoms (
                atom_id TEXT PRIMARY KEY,
                subject_ref TEXT NOT NULL,
                object_ref TEXT NOT NULL,
                relation_class TEXT NOT NULL,
                comparison_vector_json TEXT NOT NULL DEFAULT '[]',
                supporting_evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                document_id TEXT,
                chunk_id TEXT,
                confidence REAL NOT NULL DEFAULT 0.5,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_relation_atoms_subject "
            "ON directional_relation_atoms(subject_ref, relation_class)"
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

        # Content backfill (chunk/embed legacy docs) is intentionally NOT done here.
        # Call :meth:`backfill_content` from a knowledge_prepare worker / migration job.

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
        source_type: str = "document",
        confidence: float = 1.0,
        uncertainty_notes: str = "",
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
                self._replace_chunks(
                    conn,
                    document_id=document_id,
                    title=title,
                    content=content,
                    original_path=original_path,
                    source_mtime=source_mtime,
                    document_hash=digest,
                    source=source,
                    source_type=source_type,
                    confidence=confidence,
                    uncertainty_notes=uncertainty_notes,
                )
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

    def _replace_chunks(
        self,
        conn: sqlite3.Connection,
        *,
        document_id: str,
        title: str,
        content: str,
        original_path: str | None = None,
        source_mtime: str | None = None,
        document_hash: str | None = None,
        source: str = "manual",
        source_type: str = "document",
        confidence: float = 1.0,
        uncertainty_notes: str = "",
    ) -> list[ChunkRecord]:
        conn.execute("DELETE FROM knowledge_chunks WHERE document_id = ?", (document_id,))
        try:
            conn.execute("DELETE FROM knowledge_chunk_fts WHERE document_id = ?", (document_id,))
        except sqlite3.OperationalError:
            pass

        parts = chunk_text_spans(content, max_chars=self.chunk_max_chars, overlap=self.chunk_overlap)
        records: list[ChunkRecord] = []
        embed_texts: list[str] = []
        for index, part in enumerate(parts):
            chunk_id = str(uuid.uuid4())
            digest = content_sha256(part.text)
            tokens = estimate_tokens(part.text)
            provenance = {
                "path": original_path,
                "mtime": source_mtime,
                "document_hash": document_hash,
                "source": source,
                "title": title,
            }
            metadata = {"title": title}
            conn.execute(
                """
                INSERT INTO knowledge_chunks(
                    chunk_id, document_id, chunk_index, content, content_hash, token_estimate,
                    metadata_json, start_offset, end_offset, confidence, uncertainty_notes,
                    source_type, provenance_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk_id,
                    document_id,
                    index,
                    part.text,
                    digest,
                    tokens,
                    json.dumps(metadata),
                    part.start,
                    part.end,
                    confidence,
                    uncertainty_notes,
                    source_type,
                    json.dumps(provenance),
                ),
            )
            try:
                conn.execute(
                    "INSERT INTO knowledge_chunk_fts(chunk_id, document_id, title, content) VALUES (?, ?, ?, ?)",
                    (chunk_id, document_id, title, part.text),
                )
            except sqlite3.OperationalError:
                pass
            records.append(
                ChunkRecord(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    chunk_index=index,
                    content=part.text,
                    content_hash=digest,
                    token_estimate=tokens,
                    start_offset=part.start,
                    end_offset=part.end,
                    confidence=confidence,
                    uncertainty_notes=uncertainty_notes,
                    source_type=source_type,
                    provenance=provenance,
                    metadata=metadata,
                )
            )
            embed_texts.append(part.text)

        if records and self.embedding_provider.available():
            vectors = self.embedding_provider.embed_documents(embed_texts)
            now = utc_now()
            for record, vector in zip(records, vectors):
                conn.execute(
                    """
                    INSERT INTO knowledge_chunk_embeddings(
                        chunk_id, provider_id, dimensions, embedding, content_hash, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(chunk_id) DO UPDATE SET
                        provider_id = excluded.provider_id,
                        dimensions = excluded.dimensions,
                        embedding = excluded.embedding,
                        content_hash = excluded.content_hash,
                        updated_at = excluded.updated_at
                    """,
                    (
                        record.chunk_id,
                        self.embedding_provider.provider_id,
                        len(vector),
                        _pack_embedding(vector),
                        record.content_hash,
                        now,
                    ),
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
                SELECT chunk_id, document_id, chunk_index, content, content_hash, token_estimate,
                       metadata_json, start_offset, end_offset, confidence, uncertainty_notes,
                       source_type, provenance_json
                FROM knowledge_chunks
                WHERE document_id = ?
                ORDER BY chunk_index ASC
                """,
                (document_id,),
            ).fetchall()
        return [self._row_to_chunk(row) for row in rows]

    def get_chunk(self, chunk_id: str) -> ChunkRecord | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                """
                SELECT chunk_id, document_id, chunk_index, content, content_hash, token_estimate,
                       metadata_json, start_offset, end_offset, confidence, uncertainty_notes,
                       source_type, provenance_json
                FROM knowledge_chunks WHERE chunk_id = ?
                """,
                (chunk_id,),
            ).fetchone()
        return self._row_to_chunk(row) if row else None

    def delete_document(self, document_id: str) -> bool:
        with self.connect() as conn:
            self._ensure_schema(conn)
            chunk_ids = [
                row["chunk_id"]
                for row in conn.execute(
                    "SELECT chunk_id FROM knowledge_chunks WHERE document_id = ?",
                    (document_id,),
                ).fetchall()
            ]
            for chunk_id in chunk_ids:
                conn.execute("DELETE FROM knowledge_chunk_embeddings WHERE chunk_id = ?", (chunk_id,))
            try:
                conn.execute("DELETE FROM knowledge_chunk_fts WHERE document_id = ?", (document_id,))
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("DELETE FROM knowledge_fts WHERE document_id = ?", (document_id,))
            except sqlite3.OperationalError:
                pass
            conn.execute("DELETE FROM directional_relation_atoms WHERE document_id = ?", (document_id,))
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
        try:
            candidate.relative_to(root.resolve() if root.exists() else root)
        except ValueError as exc:
            cand_s = str(candidate).replace("\\", "/")
            root_s = str(self.data_root).replace("\\", "/")
            if not (cand_s == root_s or cand_s.startswith(root_s.rstrip("/") + "/")):
                raise ValueError("Path escapes configured LEVIATHAN_DATA_ROOT") from exc
        return candidate

    def ingest_file(self, path: Path, *, source: str = "modeldata") -> DocumentRecord | None:
        """Incremental file ingest. Returns existing record when unchanged (no re-chunk)."""
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
                # Unchanged — return existing without re-chunking.
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
            source_type="file",
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
                           c.start_offset, c.end_offset, c.confidence, c.uncertainty_notes,
                           c.source_type, c.provenance_json,
                           d.title, d.source, d.content AS document_content,
                           d.created_at, d.updated_at, d.original_path, d.content_hash AS document_hash,
                           d.source_mtime, d.trust_metadata_json,
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
                return [self._enrich_search_row(dict(row)) for row in rows]
            except sqlite3.OperationalError:
                pattern = "%" + "%".join(tokens[:4]) + "%"
                rows = conn.execute(
                    """
                    SELECT c.chunk_id, c.document_id, c.chunk_index, c.content AS chunk_content,
                           c.content_hash AS chunk_hash, c.token_estimate,
                           c.start_offset, c.end_offset, c.confidence, c.uncertainty_notes,
                           c.source_type, c.provenance_json,
                           d.title, d.source, d.content AS document_content,
                           d.created_at, d.updated_at, d.original_path, d.content_hash AS document_hash,
                           d.source_mtime, d.trust_metadata_json,
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
                return [self._enrich_search_row(dict(row)) for row in rows]

    def get_chunk_embedding(self, chunk_id: str) -> list[float] | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT embedding FROM knowledge_chunk_embeddings WHERE chunk_id = ?",
                (chunk_id,),
            ).fetchone()
        if row is None:
            return None
        return _unpack_embedding(row["embedding"])

    def search_dense(
        self,
        query_vector: list[float],
        *,
        limit: int = 5,
        source: str | None = None,
        status: IngestStatus = IngestStatus.READY,
    ) -> list[dict[str, Any]]:
        """Brute-force cosine over stored chunk embeddings (central SQLite only)."""
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT c.chunk_id, c.document_id, c.chunk_index, c.content AS chunk_content,
                       c.content_hash AS chunk_hash, c.token_estimate,
                       c.start_offset, c.end_offset, c.confidence, c.uncertainty_notes,
                       c.source_type, c.provenance_json,
                       d.title, d.source, d.updated_at, d.original_path,
                       d.source_mtime, d.trust_metadata_json,
                       d.content_hash AS document_hash, e.embedding
                FROM knowledge_chunk_embeddings e
                JOIN knowledge_chunks c ON c.chunk_id = e.chunk_id
                JOIN knowledge_documents d ON d.id = c.document_id
                WHERE d.status = ?
                  AND (? IS NULL OR d.source = ?)
                """,
                (status.value, source, source),
            ).fetchall()

        scored: list[dict[str, Any]] = []
        for row in rows:
            vec = _unpack_embedding(row["embedding"])
            score = cosine_similarity(query_vector, vec)
            item = self._enrich_search_row(dict(row))
            item.pop("embedding", None)
            item["dense_score"] = score
            scored.append(item)
        scored.sort(key=lambda item: item["dense_score"], reverse=True)
        return scored[:limit]

    @staticmethod
    def _enrich_search_row(row: dict[str, Any]) -> dict[str, Any]:
        """Parse trust metadata for provenance / source-validity filters."""
        raw = row.get("trust_metadata_json")
        if raw and "trust_metadata" not in row:
            try:
                row["trust_metadata"] = json.loads(raw or "{}")
            except Exception:  # noqa: BLE001
                row["trust_metadata"] = {}
        elif "trust_metadata" not in row:
            row["trust_metadata"] = {}
        return row

    def delete_relation_atoms_for_document(self, document_id: str) -> int:
        """Remove relation atoms tied to one knowledge document (rebuild hygiene)."""
        with self.connect() as conn:
            self._ensure_schema(conn)
            cur = conn.execute(
                "DELETE FROM directional_relation_atoms WHERE document_id = ?",
                (document_id,),
            )
            return int(cur.rowcount or 0)

    def upsert_relation_atom(
        self,
        *,
        subject_ref: str,
        object_ref: str,
        relation_class: RelationClass | str,
        comparison_vector: list[float] | None = None,
        supporting_evidence_refs: list[str] | tuple[str, ...] | None = None,
        document_id: str | None = None,
        chunk_id: str | None = None,
        confidence: float = 0.5,
        notes: str = "",
        atom_id: str | None = None,
    ) -> DirectionalRelationAtom:
        """Insert or replace a relation atom by stable ``atom_id`` (idempotent)."""
        if isinstance(relation_class, str):
            relation_class = RelationClass(relation_class)
        atom = DirectionalRelationAtom(
            atom_id=atom_id or str(uuid.uuid4()),
            subject_ref=subject_ref.strip(),
            object_ref=object_ref.strip(),
            relation_class=relation_class,
            comparison_vector=list(comparison_vector or []),
            supporting_evidence_refs=tuple(supporting_evidence_refs or ()),
            document_id=document_id,
            chunk_id=chunk_id,
            confidence=max(0.0, min(1.0, float(confidence))),
            notes=notes,
            created_at=utc_now(),
        )
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO directional_relation_atoms(
                    atom_id, subject_ref, object_ref, relation_class,
                    comparison_vector_json, supporting_evidence_refs_json,
                    document_id, chunk_id, confidence, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(atom_id) DO UPDATE SET
                    subject_ref=excluded.subject_ref,
                    object_ref=excluded.object_ref,
                    relation_class=excluded.relation_class,
                    comparison_vector_json=excluded.comparison_vector_json,
                    supporting_evidence_refs_json=excluded.supporting_evidence_refs_json,
                    document_id=excluded.document_id,
                    chunk_id=excluded.chunk_id,
                    confidence=excluded.confidence,
                    notes=excluded.notes
                """,
                (
                    atom.atom_id,
                    atom.subject_ref,
                    atom.object_ref,
                    atom.relation_class.value,
                    json.dumps(atom.comparison_vector),
                    json.dumps(list(atom.supporting_evidence_refs)),
                    atom.document_id,
                    atom.chunk_id,
                    atom.confidence,
                    atom.notes,
                    atom.created_at,
                ),
            )
        return atom

    def add_relation_atom(
        self,
        *,
        subject_ref: str,
        object_ref: str,
        relation_class: RelationClass | str,
        comparison_vector: list[float] | None = None,
        supporting_evidence_refs: list[str] | tuple[str, ...] | None = None,
        document_id: str | None = None,
        chunk_id: str | None = None,
        confidence: float = 0.5,
        notes: str = "",
        atom_id: str | None = None,
    ) -> DirectionalRelationAtom:
        return self.upsert_relation_atom(
            subject_ref=subject_ref,
            object_ref=object_ref,
            relation_class=relation_class,
            comparison_vector=comparison_vector,
            supporting_evidence_refs=supporting_evidence_refs,
            document_id=document_id,
            chunk_id=chunk_id,
            confidence=confidence,
            notes=notes,
            atom_id=atom_id,
        )

    def list_relation_atoms(
        self,
        *,
        subject_ref: str | None = None,
        relation_class: RelationClass | str | None = None,
        limit: int = 100,
    ) -> list[DirectionalRelationAtom]:
        clauses: list[str] = []
        params: list[Any] = []
        if subject_ref:
            clauses.append("subject_ref = ?")
            params.append(subject_ref)
        if relation_class is not None:
            value = relation_class.value if isinstance(relation_class, RelationClass) else relation_class
            clauses.append("relation_class = ?")
            params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 1000)))
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                f"""
                SELECT * FROM directional_relation_atoms
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_atom(row) for row in rows]

    @staticmethod
    def _row_to_chunk(row: sqlite3.Row) -> ChunkRecord:
        keys = row.keys()
        return ChunkRecord(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            chunk_index=row["chunk_index"],
            content=row["content"],
            content_hash=row["content_hash"],
            token_estimate=row["token_estimate"],
            start_offset=int(row["start_offset"]) if "start_offset" in keys and row["start_offset"] is not None else 0,
            end_offset=int(row["end_offset"]) if "end_offset" in keys and row["end_offset"] is not None else 0,
            confidence=float(row["confidence"]) if "confidence" in keys and row["confidence"] is not None else 1.0,
            uncertainty_notes=row["uncertainty_notes"] if "uncertainty_notes" in keys and row["uncertainty_notes"] else "",
            source_type=row["source_type"] if "source_type" in keys and row["source_type"] else "document",
            provenance=json.loads(row["provenance_json"] or "{}") if "provenance_json" in keys else {},
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    @staticmethod
    def _row_to_atom(row: sqlite3.Row) -> DirectionalRelationAtom:
        return DirectionalRelationAtom(
            atom_id=row["atom_id"],
            subject_ref=row["subject_ref"],
            object_ref=row["object_ref"],
            relation_class=RelationClass(row["relation_class"]),
            comparison_vector=json.loads(row["comparison_vector_json"] or "[]"),
            supporting_evidence_refs=tuple(json.loads(row["supporting_evidence_refs_json"] or "[]")),
            document_id=row["document_id"],
            chunk_id=row["chunk_id"],
            confidence=float(row["confidence"]),
            notes=row["notes"] or "",
            created_at=row["created_at"],
        )

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
