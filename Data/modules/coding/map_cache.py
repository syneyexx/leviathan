"""Semantic map CONTROL cache + ArtifactStore spill for large payloads."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Keep CONTROL payload bounded; spill full map above this.
_CONTROL_PAYLOAD_SOFT_LIMIT = 256_000


@dataclass
class SemanticMapCacheRecord:
    workspace_root: str
    generated_at: str
    content_hash: str
    status: str  # ready | stale | building | failed
    generation_fingerprint: str | None
    summary: dict[str, Any]
    artifact_id: str | None
    payload: dict[str, Any] | None

    def public_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "workspace_root": self.workspace_root,
            "generated_at": self.generated_at,
            "content_hash": self.content_hash,
            "status": self.status,
            "generation_fingerprint": self.generation_fingerprint,
            "summary": dict(self.summary),
            "artifact_id": self.artifact_id,
        }
        if self.payload is not None:
            out["map"] = self.payload
        return out


def _connect(db_path: Path) -> sqlite3.Connection:
    from Data.modules.common.sqlite_policy import open_sqlite_connection

    return open_sqlite_connection(db_path, set_wal=False)


def ensure_cache_schema(conn: sqlite3.Connection) -> None:
    """Idempotent column ensure for semantic map cache (compatible with m29)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS coding_semantic_map_cache (
            workspace_root TEXT PRIMARY KEY,
            generated_at TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(coding_semantic_map_cache)").fetchall()}
    alters = [
        ("status", "TEXT NOT NULL DEFAULT 'ready'"),
        ("generation_fingerprint", "TEXT"),
        ("artifact_id", "TEXT"),
        ("summary_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("indexed_files", "INTEGER NOT NULL DEFAULT 0"),
        ("discovered_files", "INTEGER NOT NULL DEFAULT 0"),
        ("truncated", "INTEGER NOT NULL DEFAULT 0"),
    ]
    for name, decl in alters:
        if name not in cols:
            conn.execute(f"ALTER TABLE coding_semantic_map_cache ADD COLUMN {name} {decl}")


def map_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "workspace_root": payload.get("workspace_root"),
        "generated_at": payload.get("generated_at"),
        "file_count": payload.get("file_count"),
        "symbol_count": payload.get("symbol_count"),
        "test_files": list(payload.get("test_files") or [])[:50],
        "build_metadata": payload.get("build_metadata") or {},
        "incremental": bool(payload.get("incremental")),
        "truncated": bool((payload.get("limits") or {}).get("truncated")),
        "discovered_files": (payload.get("limits") or {}).get("discovered_files"),
        "indexed_files": (payload.get("limits") or {}).get("indexed_files"),
        "skipped_files": (payload.get("limits") or {}).get("skipped_files"),
        "generation": payload.get("generation"),
        "language_support": payload.get("language_support"),
        "truth": payload.get("truth") or {},
    }


def get_cached_map(db_path: Path, workspace_root: str) -> SemanticMapCacheRecord | None:
    conn = _connect(db_path)
    try:
        ensure_cache_schema(conn)
        row = conn.execute(
            "SELECT * FROM coding_semantic_map_cache WHERE workspace_root = ?",
            (workspace_root,),
        ).fetchone()
        conn.commit()
    finally:
        conn.close()
    if row is None:
        return None
    keys = row.keys() if hasattr(row, "keys") else []
    data = {k: row[k] for k in keys} if keys else dict(row)
    payload_raw = data.get("payload_json") or "{}"
    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError:
        payload = {}
    summary_raw = data.get("summary_json") or "{}"
    try:
        summary = json.loads(summary_raw) if summary_raw else {}
    except json.JSONDecodeError:
        summary = {}
    if not summary and isinstance(payload, dict):
        # Legacy rows stored full map in payload_json.
        if "files" in payload:
            summary = map_summary(payload)
        else:
            summary = dict(payload)
    artifact_id = data.get("artifact_id")
    full_payload = None
    if artifact_id:
        # Caller may load artifact separately; keep CONTROL row light.
        full_payload = None
    elif isinstance(payload, dict) and "files" in payload:
        full_payload = payload
    elif isinstance(payload, dict) and payload.get("map"):
        full_payload = payload.get("map")
    return SemanticMapCacheRecord(
        workspace_root=str(data.get("workspace_root") or workspace_root),
        generated_at=str(data.get("generated_at") or ""),
        content_hash=str(data.get("content_hash") or ""),
        status=str(data.get("status") or "ready"),
        generation_fingerprint=data.get("generation_fingerprint"),
        summary=summary if isinstance(summary, dict) else {},
        artifact_id=str(artifact_id) if artifact_id else None,
        payload=full_payload if isinstance(full_payload, dict) else None,
    )


def put_cached_map(
    db_path: Path,
    *,
    workspace_root: str,
    generated_at: str,
    content_hash: str,
    payload: dict[str, Any],
    generation_fingerprint: str | None,
    status: str = "ready",
    artifact_store: Any | None = None,
    producer: str = "coding.semantic_map",
) -> SemanticMapCacheRecord:
    """Atomically replace cache entry. Spills large payloads to ArtifactStore."""
    summary = map_summary(payload)
    blob = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    artifact_id: str | None = None
    control_payload: dict[str, Any]
    if len(blob) > _CONTROL_PAYLOAD_SOFT_LIMIT and artifact_store is not None:
        record = artifact_store.create_from_bytes(
            data=blob,
            artifact_type="coding.semantic_map",
            producer=producer,
            filename="semantic_map.json",
            metadata={
                "workspace_root": workspace_root,
                "content_hash": content_hash,
                "generation_fingerprint": generation_fingerprint,
            },
        )
        artifact_id = record.artifact_id
        control_payload = {"summary_only": True, "artifact_id": artifact_id, **summary}
    else:
        control_payload = payload if len(blob) <= _CONTROL_PAYLOAD_SOFT_LIMIT else summary

    limits = payload.get("limits") or {}
    conn = _connect(db_path)
    try:
        ensure_cache_schema(conn)
        conn.execute(
            """
            INSERT INTO coding_semantic_map_cache(
                workspace_root, generated_at, content_hash, payload_json,
                status, generation_fingerprint, artifact_id, summary_json,
                indexed_files, discovered_files, truncated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_root) DO UPDATE SET
                generated_at=excluded.generated_at,
                content_hash=excluded.content_hash,
                payload_json=excluded.payload_json,
                status=excluded.status,
                generation_fingerprint=excluded.generation_fingerprint,
                artifact_id=excluded.artifact_id,
                summary_json=excluded.summary_json,
                indexed_files=excluded.indexed_files,
                discovered_files=excluded.discovered_files,
                truncated=excluded.truncated
            """,
            (
                workspace_root,
                generated_at,
                content_hash,
                json.dumps(control_payload, separators=(",", ":")),
                status,
                generation_fingerprint,
                artifact_id,
                json.dumps(summary, separators=(",", ":")),
                int(limits.get("indexed_files") or payload.get("file_count") or 0),
                int(limits.get("discovered_files") or payload.get("file_count") or 0),
                1 if limits.get("truncated") else 0,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return SemanticMapCacheRecord(
        workspace_root=workspace_root,
        generated_at=generated_at,
        content_hash=content_hash,
        status=status,
        generation_fingerprint=generation_fingerprint,
        summary=summary,
        artifact_id=artifact_id,
        payload=None if artifact_id else (payload if len(blob) <= _CONTROL_PAYLOAD_SOFT_LIMIT else None),
    )


def mark_cache_status(db_path: Path, workspace_root: str, status: str) -> None:
    conn = _connect(db_path)
    try:
        ensure_cache_schema(conn)
        conn.execute(
            "UPDATE coding_semantic_map_cache SET status = ? WHERE workspace_root = ?",
            (status, workspace_root),
        )
        conn.commit()
    finally:
        conn.close()
