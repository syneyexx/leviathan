"""Invalidate Dataset Brain retrieval projections when dataset semantics change."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from dataset_brain import read_manifest, utc_now, write_manifest


def invalidate_mapping_projection(
    training_root: str | Path,
    database_path: str | Path,
    dataset_id: str,
) -> dict[str, Any]:
    """Hide a stale mapping projection without deleting the durable raw snapshot.

    The existing HADES knowledge search reads FTS rows directly and does not filter on
    ``knowledge_sources.status``. Therefore changing the dataset mapping must remove
    the old FTS publication immediately; changing only a status flag would still let
    stale chunks influence Chat/Tasks/agents.
    """

    root = Path(training_root).expanduser().resolve()
    manifest = read_manifest(root, dataset_id)
    if manifest is None:
        return {"invalidated": False, "reason": "not_indexed"}

    db_path = Path(database_path).expanduser().resolve()
    source_id = str(manifest.get("source_id") or "").strip() or None
    with sqlite3.connect(db_path, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        if source_id is None:
            row = conn.execute(
                "SELECT id FROM knowledge_sources WHERE source_type=? AND uri=? LIMIT 1",
                ("dataset", f"dataset://{dataset_id}"),
            ).fetchone()
            source_id = str(row["id"]) if row else None
        if source_id:
            conn.execute("DELETE FROM knowledge_fts WHERE source_id=?", (source_id,))
            conn.execute(
                "UPDATE knowledge_sources SET status=?, updated_at=? WHERE id=?",
                ("stale", utc_now(), source_id),
            )
        conn.commit()

    updated = write_manifest(
        root,
        dataset_id,
        {
            "status": "stale_mapping",
            "phase": "stale_mapping",
            "active_job_id": None,
            "error": "mapping_changed_reindex_required",
        },
    )
    return {
        "invalidated": True,
        "source_id": source_id,
        "status": updated.get("status"),
        "snapshot_path": updated.get("snapshot_path"),
        "materialized_complete": bool(updated.get("materialized_complete")),
    }
