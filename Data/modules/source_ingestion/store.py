"""Durable ingestion manifest / checkpoint store (same SQLite DB as LEVIATHAN)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .types import (
    ArchiveManifest,
    IngestionPhase,
    ManifestMember,
    MemberOutcome,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dumps(data: Any) -> str:
    return json.dumps(data if data is not None else {}, ensure_ascii=False, sort_keys=True)


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


class IngestionStore:
    """Persists archive manifests and per-member checkpoints for resume/idempotency."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        from Data.modules.common.sqlite_policy import open_sqlite_connection

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

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS source_ingestion_containers (
                container_source_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                job_id TEXT,
                filename TEXT,
                archive_type TEXT,
                phase TEXT NOT NULL,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                compressed_bytes INTEGER NOT NULL DEFAULT 0,
                uncompressed_bytes INTEGER NOT NULL DEFAULT 0,
                progress_json TEXT NOT NULL DEFAULT '{}',
                manifest_json TEXT NOT NULL DEFAULT '{}',
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS source_ingestion_members (
                member_id TEXT PRIMARY KEY,
                container_source_id TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                original_filename TEXT,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                compressed_size_bytes INTEGER,
                content_hash TEXT,
                mime_type TEXT,
                detected_kind TEXT,
                detection_json TEXT NOT NULL DEFAULT '{}',
                outcome TEXT NOT NULL DEFAULT 'pending',
                skip_reason TEXT,
                error_code TEXT,
                parse_status TEXT NOT NULL DEFAULT 'pending',
                brain_status TEXT NOT NULL DEFAULT 'not_applicable',
                child_source_id TEXT,
                brain_document_id TEXT,
                parser TEXT,
                is_encrypted INTEGER NOT NULL DEFAULT 0,
                is_symlink INTEGER NOT NULL DEFAULT 0,
                is_directory INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(container_source_id, relative_path),
                FOREIGN KEY(container_source_id)
                    REFERENCES source_ingestion_containers(container_source_id)
                    ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sim_container_outcome "
            "ON source_ingestion_members(container_source_id, outcome)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sim_child "
            "ON source_ingestion_members(child_source_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sic_project "
            "ON source_ingestion_containers(project_id, updated_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sic_job ON source_ingestion_containers(job_id)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS source_ingestion_parse_cache (
                content_hash TEXT NOT NULL,
                parser_version TEXT NOT NULL,
                parser TEXT,
                snapshot_path TEXT,
                brain_document_id TEXT,
                parse_status TEXT NOT NULL DEFAULT 'ok',
                text_hash TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (content_hash, parser_version)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sipc_hash "
            "ON source_ingestion_parse_cache(content_hash)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sim_content_hash "
            "ON source_ingestion_members(content_hash)"
        )

    def upsert_container(
        self,
        *,
        container_source_id: str,
        project_id: str,
        job_id: str | None = None,
        filename: str | None = None,
        archive_type: str | None = None,
        phase: IngestionPhase = IngestionPhase.STORED,
        compressed_bytes: int = 0,
        uncompressed_bytes: int = 0,
        progress: dict[str, Any] | None = None,
        manifest_meta: dict[str, Any] | None = None,
        error: str | None = None,
        cancel_requested: bool | None = None,
    ) -> None:
        now = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            existing = conn.execute(
                "SELECT container_source_id, cancel_requested, progress_json, manifest_json "
                "FROM source_ingestion_containers "
                "WHERE container_source_id = ?",
                (container_source_id,),
            ).fetchone()
            if existing:
                cancel = (
                    int(bool(cancel_requested))
                    if cancel_requested is not None
                    else int(existing["cancel_requested"] or 0)
                )
                # Preserve prior progress/manifest unless explicitly provided.
                if progress is None:
                    progress_payload = _loads(existing["progress_json"], {})
                else:
                    progress_payload = progress
                if manifest_meta is None:
                    manifest_payload = _loads(existing["manifest_json"], {})
                else:
                    manifest_payload = manifest_meta
                conn.execute(
                    """
                    UPDATE source_ingestion_containers SET
                        job_id=COALESCE(?, job_id),
                        filename=COALESCE(?, filename),
                        archive_type=COALESCE(?, archive_type),
                        phase=?,
                        cancel_requested=?,
                        compressed_bytes=?,
                        uncompressed_bytes=?,
                        progress_json=?,
                        manifest_json=?,
                        error=?,
                        updated_at=?
                    WHERE container_source_id=?
                    """,
                    (
                        job_id,
                        filename,
                        archive_type,
                        phase.value,
                        cancel,
                        compressed_bytes,
                        uncompressed_bytes,
                        _dumps(progress_payload or {}),
                        _dumps(manifest_payload or {}),
                        error,
                        now,
                        container_source_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO source_ingestion_containers(
                        container_source_id, project_id, job_id, filename, archive_type,
                        phase, cancel_requested, compressed_bytes, uncompressed_bytes,
                        progress_json, manifest_json, error, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        container_source_id,
                        project_id,
                        job_id,
                        filename,
                        archive_type,
                        phase.value,
                        int(bool(cancel_requested)),
                        compressed_bytes,
                        uncompressed_bytes,
                        _dumps(progress or {}),
                        _dumps(manifest_meta or {}),
                        error,
                        now,
                        now,
                    ),
                )

    def merge_progress(
        self,
        container_source_id: str,
        *,
        project_id: str | None = None,
        phase: IngestionPhase | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        """Merge measurable progress fields into container progress_json.

        Unknown totals should be written as the sentinel ``\"UNMEASURED\"`` rather
        than inventing percentages. Numeric fields overwrite; callers decide honesty.
        """
        now = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM source_ingestion_containers WHERE container_source_id=?",
                (container_source_id,),
            ).fetchone()
            if row is None:
                if not project_id:
                    raise ValueError("merge_progress requires project_id for new container")
                progress = dict(fields)
                progress["updated_at"] = now
                conn.execute(
                    """
                    INSERT INTO source_ingestion_containers(
                        container_source_id, project_id, job_id, filename, archive_type,
                        phase, cancel_requested, compressed_bytes, uncompressed_bytes,
                        progress_json, manifest_json, error, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        container_source_id,
                        project_id,
                        None,
                        None,
                        None,
                        (phase or IngestionPhase.STORED).value,
                        0,
                        0,
                        0,
                        _dumps(progress),
                        "{}",
                        None,
                        now,
                        now,
                    ),
                )
                return progress
            progress = _loads(row["progress_json"], {})
            progress.update(fields)
            progress["updated_at"] = now
            conn.execute(
                """
                UPDATE source_ingestion_containers SET
                    phase=COALESCE(?, phase),
                    progress_json=?,
                    updated_at=?
                WHERE container_source_id=?
                """,
                (
                    phase.value if phase is not None else None,
                    _dumps(progress),
                    now,
                    container_source_id,
                ),
            )
            return progress

    def get_parse_cache(
        self,
        content_hash: str,
        *,
        parser_version: str | None = None,
    ) -> dict[str, Any] | None:
        """Return prior parse/brain result for content_hash if present."""
        if not content_hash:
            return None
        with self.connect() as conn:
            self._ensure_schema(conn)
            if parser_version:
                row = conn.execute(
                    """
                    SELECT * FROM source_ingestion_parse_cache
                    WHERE content_hash=? AND parser_version=?
                    """,
                    (content_hash, parser_version),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM source_ingestion_parse_cache
                    WHERE content_hash=?
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (content_hash,),
                ).fetchone()
        if row is None:
            return None
        return {
            "content_hash": row["content_hash"],
            "parser_version": row["parser_version"],
            "parser": row["parser"],
            "snapshot_path": row["snapshot_path"],
            "brain_document_id": row["brain_document_id"],
            "parse_status": row["parse_status"],
            "text_hash": row["text_hash"],
            "metadata": _loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def put_parse_cache(
        self,
        *,
        content_hash: str,
        parser_version: str,
        parser: str | None = None,
        snapshot_path: str | None = None,
        brain_document_id: str | None = None,
        parse_status: str = "ok",
        text_hash: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not content_hash:
            return
        now = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO source_ingestion_parse_cache(
                    content_hash, parser_version, parser, snapshot_path,
                    brain_document_id, parse_status, text_hash, metadata_json,
                    created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(content_hash, parser_version) DO UPDATE SET
                    parser=excluded.parser,
                    snapshot_path=COALESCE(excluded.snapshot_path, source_ingestion_parse_cache.snapshot_path),
                    brain_document_id=COALESCE(
                        excluded.brain_document_id,
                        source_ingestion_parse_cache.brain_document_id
                    ),
                    parse_status=excluded.parse_status,
                    text_hash=COALESCE(excluded.text_hash, source_ingestion_parse_cache.text_hash),
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    content_hash,
                    parser_version,
                    parser,
                    snapshot_path,
                    brain_document_id,
                    parse_status,
                    text_hash,
                    _dumps(metadata or {}),
                    now,
                    now,
                ),
            )

    def find_processed_member_by_hash(
        self,
        content_hash: str,
        *,
        exclude_container_id: str | None = None,
    ) -> ManifestMember | None:
        """Early-dedupe helper: locate a successfully parsed member with same hash."""
        if not content_hash:
            return None
        with self.connect() as conn:
            self._ensure_schema(conn)
            if exclude_container_id:
                row = conn.execute(
                    """
                    SELECT * FROM source_ingestion_members
                    WHERE content_hash=? AND outcome IN ('success', 'duplicate')
                      AND parse_status='ok'
                      AND container_source_id != ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (content_hash, exclude_container_id),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM source_ingestion_members
                    WHERE content_hash=? AND outcome IN ('success', 'duplicate')
                      AND parse_status='ok'
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (content_hash,),
                ).fetchone()
        if row is None:
            return None
        return self._member_from_row(row)

    def request_cancel(self, container_source_id: str) -> None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                "UPDATE source_ingestion_containers SET cancel_requested=1, updated_at=? "
                "WHERE container_source_id=?",
                (utc_now(), container_source_id),
            )

    def is_cancel_requested(self, container_source_id: str) -> bool:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT cancel_requested FROM source_ingestion_containers WHERE container_source_id=?",
                (container_source_id,),
            ).fetchone()
        return bool(row and row["cancel_requested"])

    def get_member(
        self,
        container_source_id: str,
        relative_path: str,
    ) -> ManifestMember | None:
        """Indexed lookup by canonical (container, relative_path) key."""
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                """
                SELECT * FROM source_ingestion_members
                WHERE container_source_id=? AND relative_path=?
                """,
                (container_source_id, relative_path),
            ).fetchone()
        if row is None:
            return None
        return self._member_from_row(row)

    def get_child_source_id(self, container_source_id: str, relative_path: str) -> str | None:
        member = self.get_member(container_source_id, relative_path)
        if member is None:
            return None
        return member.child_source_id

    def bind_child_source(
        self,
        container_source_id: str,
        relative_path: str,
        child_source_id: str,
        *,
        content_hash: str | None = None,
    ) -> None:
        now = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                UPDATE source_ingestion_members
                SET child_source_id=?, content_hash=COALESCE(?, content_hash), updated_at=?
                WHERE container_source_id=? AND relative_path=?
                """,
                (child_source_id, content_hash, now, container_source_id, relative_path),
            )

    def get_container(self, container_source_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM source_ingestion_containers WHERE container_source_id=?",
                (container_source_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "container_source_id": row["container_source_id"],
            "project_id": row["project_id"],
            "job_id": row["job_id"],
            "filename": row["filename"],
            "archive_type": row["archive_type"],
            "phase": row["phase"],
            "cancel_requested": bool(row["cancel_requested"]),
            "compressed_bytes": row["compressed_bytes"],
            "uncompressed_bytes": row["uncompressed_bytes"],
            "progress": _loads(row["progress_json"], {}),
            "manifest": _loads(row["manifest_json"], {}),
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def upsert_member(self, member: ManifestMember) -> ManifestMember:
        now = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            existing = conn.execute(
                """
                SELECT member_id FROM source_ingestion_members
                WHERE container_source_id=? AND relative_path=?
                """,
                (member.container_source_id, member.relative_path),
            ).fetchone()
            if existing:
                member_id = existing["member_id"]
                conn.execute(
                    """
                    UPDATE source_ingestion_members SET
                        original_filename=?, size_bytes=?, compressed_size_bytes=?,
                        content_hash=?, mime_type=?, detected_kind=?, detection_json=?,
                        outcome=?, skip_reason=?, error_code=?, parse_status=?, brain_status=?,
                        child_source_id=?, brain_document_id=?, parser=?,
                        is_encrypted=?, is_symlink=?, is_directory=?, metadata_json=?,
                        updated_at=?
                    WHERE member_id=?
                    """,
                    (
                        member.original_filename,
                        member.size_bytes,
                        member.compressed_size_bytes,
                        member.content_hash,
                        member.mime_type,
                        member.detected_kind,
                        _dumps(member.detection),
                        member.outcome.value,
                        member.skip_reason,
                        member.error_code,
                        member.parse_status,
                        member.brain_status,
                        member.child_source_id,
                        member.brain_document_id,
                        member.parser,
                        int(member.is_encrypted),
                        int(member.is_symlink),
                        int(member.is_directory),
                        _dumps(member.metadata),
                        now,
                        member_id,
                    ),
                )
                member.member_id = member_id
            else:
                mid = member.member_id or str(uuid.uuid4())
                member.member_id = mid
                conn.execute(
                    """
                    INSERT INTO source_ingestion_members(
                        member_id, container_source_id, relative_path, original_filename,
                        size_bytes, compressed_size_bytes, content_hash, mime_type,
                        detected_kind, detection_json, outcome, skip_reason, error_code,
                        parse_status, brain_status, child_source_id, brain_document_id,
                        parser, is_encrypted, is_symlink, is_directory, metadata_json,
                        created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        mid,
                        member.container_source_id,
                        member.relative_path,
                        member.original_filename,
                        member.size_bytes,
                        member.compressed_size_bytes,
                        member.content_hash,
                        member.mime_type,
                        member.detected_kind,
                        _dumps(member.detection),
                        member.outcome.value,
                        member.skip_reason,
                        member.error_code,
                        member.parse_status,
                        member.brain_status,
                        member.child_source_id,
                        member.brain_document_id,
                        member.parser,
                        int(member.is_encrypted),
                        int(member.is_symlink),
                        int(member.is_directory),
                        _dumps(member.metadata),
                        now,
                        now,
                    ),
                )
        return member

    def list_members(
        self,
        container_source_id: str,
        *,
        offset: int = 0,
        limit: int = 200,
        outcome: str | None = None,
    ) -> list[ManifestMember]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            if outcome:
                rows = conn.execute(
                    """
                    SELECT * FROM source_ingestion_members
                    WHERE container_source_id=? AND outcome=?
                    ORDER BY relative_path ASC
                    LIMIT ? OFFSET ?
                    """,
                    (container_source_id, outcome, max(1, min(limit, 2000)), max(0, offset)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM source_ingestion_members
                    WHERE container_source_id=?
                    ORDER BY relative_path ASC
                    LIMIT ? OFFSET ?
                    """,
                    (container_source_id, max(1, min(limit, 2000)), max(0, offset)),
                ).fetchall()
        return [self._member_from_row(r) for r in rows]

    def count_members(self, container_source_id: str) -> dict[str, int]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT outcome, COUNT(*) AS n FROM source_ingestion_members
                WHERE container_source_id=? AND is_directory=0
                GROUP BY outcome
                """,
                (container_source_id,),
            ).fetchall()
            brain = conn.execute(
                """
                SELECT brain_status, COUNT(*) AS n FROM source_ingestion_members
                WHERE container_source_id=? AND is_directory=0
                GROUP BY brain_status
                """,
                (container_source_id,),
            ).fetchall()
        counts = {r["outcome"]: int(r["n"]) for r in rows}
        brain_counts = {r["brain_status"]: int(r["n"]) for r in brain}
        return {
            "by_outcome": counts,  # type: ignore[dict-item]
            "by_brain": brain_counts,  # type: ignore[dict-item]
            "total": sum(counts.values()),
            "pending": int(counts.get("pending", 0)),
            "success": int(counts.get("success", 0)),
            "skipped": int(counts.get("skipped", 0)),
            "failed": int(counts.get("failed", 0)),
            "quarantined": int(counts.get("quarantined", 0)),
            "duplicate": int(counts.get("duplicate", 0)),
            "routed": int(counts.get("routed", 0)),
            "brain_synced": int(brain_counts.get("synced", 0)),
            "brain_failed": int(brain_counts.get("failed", 0)),
        }

    def list_pending_members(self, container_source_id: str, *, limit: int = 100) -> list[ManifestMember]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT * FROM source_ingestion_members
                WHERE container_source_id=? AND outcome='pending' AND is_directory=0
                ORDER BY relative_path ASC
                LIMIT ?
                """,
                (container_source_id, max(1, min(limit, 500))),
            ).fetchall()
        return [self._member_from_row(r) for r in rows]

    def list_brain_retry_members(self, container_source_id: str, *, limit: int = 100) -> list[ManifestMember]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT * FROM source_ingestion_members
                WHERE container_source_id=? AND parse_status='ok'
                  AND brain_status IN ('failed', 'pending')
                ORDER BY relative_path ASC
                LIMIT ?
                """,
                (container_source_id, max(1, min(limit, 500))),
            ).fetchall()
        return [self._member_from_row(r) for r in rows]

    def build_manifest(self, container_source_id: str) -> ArchiveManifest:
        container = self.get_container(container_source_id) or {}
        members = self.list_members(container_source_id, limit=2000)
        # For large archives, aggregates come from counts; members list is paginated externally.
        counts = self.count_members(container_source_id)
        meta = dict(container.get("manifest") or {})
        manifest = ArchiveManifest(
            container_source_id=container_source_id,
            archive_type=str(container.get("archive_type") or meta.get("archive_type") or "unknown"),
            total_uncompressed_bytes=int(container.get("uncompressed_bytes") or 0),
            compressed_bytes=int(container.get("compressed_bytes") or 0),
            project_kind=meta.get("project_kind"),
            languages_detected=list(meta.get("languages_detected") or []),
            root_files=list(meta.get("root_files") or []),
            manifest_files=list(meta.get("manifest_files") or []),
            members=members,
            metadata=meta,
        )
        # Prefer SQL aggregates for accuracy when paginated
        manifest.member_count = int(counts.get("total") or 0)
        manifest.files_ingested = int(counts.get("success") or 0)
        manifest.files_skipped = int(counts.get("skipped") or 0)
        manifest.files_failed = int(counts.get("failed") or 0)
        manifest.files_quarantined = int(counts.get("quarantined") or 0)
        manifest.files_duplicate = int(counts.get("duplicate") or 0)
        manifest.files_routed = int(counts.get("routed") or 0)
        manifest.files_pending = int(counts.get("pending") or 0)
        manifest.brain_synced = int(counts.get("brain_synced") or 0)
        manifest.brain_failed = int(counts.get("brain_failed") or 0)
        return manifest

    def _member_from_row(self, row: sqlite3.Row) -> ManifestMember:
        try:
            outcome = MemberOutcome(str(row["outcome"]))
        except ValueError:
            outcome = MemberOutcome.PENDING
        return ManifestMember(
            member_id=row["member_id"],
            container_source_id=row["container_source_id"],
            relative_path=row["relative_path"],
            original_filename=row["original_filename"] or Path(row["relative_path"]).name,
            size_bytes=int(row["size_bytes"] or 0),
            compressed_size_bytes=row["compressed_size_bytes"],
            content_hash=row["content_hash"],
            mime_type=row["mime_type"],
            detected_kind=row["detected_kind"],
            detection=_loads(row["detection_json"], {}),
            outcome=outcome,
            skip_reason=row["skip_reason"],
            error_code=row["error_code"],
            parse_status=row["parse_status"] or "pending",
            brain_status=row["brain_status"] or "not_applicable",
            child_source_id=row["child_source_id"],
            brain_document_id=row["brain_document_id"],
            parser=row["parser"],
            is_encrypted=bool(row["is_encrypted"]),
            is_symlink=bool(row["is_symlink"]),
            is_directory=bool(row["is_directory"]),
            metadata=_loads(row["metadata_json"], {}),
        )
