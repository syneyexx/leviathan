"""Schema migration foundation for LEVIATHAN SQLite stores."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


def _m1_baseline_marker(conn: sqlite3.Connection) -> None:
    """Version 1 marks the pre-migration schema as acknowledged.

    Conversations/knowledge/runs tables may already exist from CREATE TABLE IF NOT EXISTS.
    This migration is intentionally a no-op body so existing DBs can adopt versioning safely.
    """
    conn.execute("SELECT 1")


def _m2_artifacts_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS artifacts (
            artifact_id TEXT PRIMARY KEY,
            run_id TEXT,
            job_id TEXT,
            artifact_type TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            content_hash TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            producer TEXT NOT NULL,
            verification_status TEXT NOT NULL DEFAULT 'unverified',
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )


def _m3_knowledge_v2(conn: sqlite3.Connection) -> None:
    """Add Knowledge V2 columns/tables. Safe on existing Step-1 knowledge_documents."""

    def columns(table: str) -> set[str]:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}

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
    existing = columns("knowledge_documents")
    for name, ddl in {
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
    }.items():
        if name not in existing:
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
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunk_fts
            USING fts5(chunk_id UNINDEXED, document_id UNINDEXED, title, content)
            """
        )
    except sqlite3.OperationalError:
        pass


MIGRATIONS: Sequence[Migration] = (
    Migration(version=1, name="baseline_schema_versioning", apply=_m1_baseline_marker),
    Migration(version=2, name="artifacts_table", apply=_m2_artifacts_table),
    Migration(version=3, name="knowledge_v2", apply=_m3_knowledge_v2),
)


class MigrationRunner:
    def __init__(self, path: Path, migrations: Sequence[Migration] = MIGRATIONS) -> None:
        self.path = path
        self.migrations = sorted(migrations, key=lambda item: item.version)
        self._validate_sequence()

    def _validate_sequence(self) -> None:
        expected = 1
        seen: set[int] = set()
        for migration in self.migrations:
            if migration.version in seen:
                raise MigrationError(f"Duplicate migration version: {migration.version}")
            if migration.version != expected:
                raise MigrationError(
                    f"Migration versions must be contiguous starting at 1; expected {expected}, got {migration.version}"
                )
            seen.add(migration.version)
            expected += 1

    def ensure_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )

    def current_version(self, conn: sqlite3.Connection) -> int:
        self.ensure_table(conn)
        row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_migrations").fetchone()
        return int(row[0] if not isinstance(row, sqlite3.Row) else row["v"])

    def apply_all(self) -> list[int]:
        applied: list[int] = []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            self.ensure_table(conn)
            current = self.current_version(conn)
            for migration in self.migrations:
                if migration.version <= current:
                    continue
                migration.apply(conn)
                conn.execute(
                    "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, datetime('now'))",
                    (migration.version, migration.name),
                )
                applied.append(migration.version)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return applied
