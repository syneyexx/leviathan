"""Exact deduplication of canonical records — external-memory bounded."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Iterator

from Data.modules.common.hashing import sha256_text

from .scratch import ScratchManager, ScratchSession
from .storage_authority import StorageClass
from .types import CanonicalRecord, DatasetError


def record_fingerprint(record: CanonicalRecord) -> str:
    """Exact content fingerprint (id excluded — dedupe by payload)."""
    payload = {
        "text": record.text,
        "messages": record.messages,
        "labels": record.labels,
    }
    return sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def exact_dedupe(records: list[CanonicalRecord]) -> tuple[list[CanonicalRecord], dict[str, Any]]:
    """In-memory exact dedupe — compatibility for small corpora / tests.

    Production large-corpus path: ``iter_exact_dedupe_external``.
    """
    seen: set[str] = set()
    kept: list[CanonicalRecord] = []
    duplicate_ids: list[str] = []
    for rec in records:
        fp = record_fingerprint(rec)
        if fp in seen:
            duplicate_ids.append(rec.id)
            continue
        seen.add(fp)
        kept.append(rec)
    stats = {
        "inputCount": len(records),
        "outputCount": len(kept),
        "removedCount": len(records) - len(kept),
        "duplicateIds": duplicate_ids[:100],
        "duplicateIdsTruncated": len(duplicate_ids) > 100,
        "method": "exact_sha256",
        "memoryMode": "in_memory",
    }
    return kept, stats


def iter_exact_dedupe_external(
    records: Iterable[CanonicalRecord],
    *,
    scratch: ScratchSession | None = None,
    scratch_manager: ScratchManager | None = None,
    job_id: str = "dedupe",
    max_duplicate_ids: int = 100,
) -> tuple[Iterator[CanonicalRecord], dict[str, Any]]:
    """Exact SHA-256 dedupe via ephemeral scratch SQLite (EPHEMERAL_SCRATCH).

    Preserves first-occurrence order. Scratch DB is never a durable authority.
    """
    owns_session = False
    session = scratch
    if session is None:
        if scratch_manager is None:
            raise DatasetError(
                "External-memory dedupe requires scratch session or manager",
                code="scratch_required",
            )
        session = scratch_manager.open_session(job_id)
        owns_session = True

    db_path = session.path("exact_dedupe.sqlite")
    # Ensure name is not a forbidden competing DB
    if db_path.name.lower() in {"knowledge.db", "trading.db", "datasets.db"}:
        raise DatasetError("Forbidden scratch DB name", code="forbidden_scratch_db")

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute(
            "CREATE TABLE seen (fp TEXT PRIMARY KEY NOT NULL) WITHOUT ROWID"
        )
        conn.commit()
    except Exception:
        conn.close()
        if owns_session and scratch_manager is not None:
            scratch_manager.cleanup_session(session.job_id)
        raise

    stats: dict[str, Any] = {
        "inputCount": 0,
        "outputCount": 0,
        "removedCount": 0,
        "duplicateIds": [],
        "duplicateIdsTruncated": False,
        "method": "exact_sha256",
        "memoryMode": "external_sqlite_scratch",
        "storageClass": StorageClass.EPHEMERAL_SCRATCH.value,
        "scratchPath": str(session.root),
        "spillBytes": 0,
    }
    duplicate_ids: list[str] = []

    def _gen() -> Iterator[CanonicalRecord]:
        nonlocal owns_session
        try:
            for rec in records:
                stats["inputCount"] += 1
                fp = record_fingerprint(rec)
                cur = conn.execute(
                    "INSERT OR IGNORE INTO seen(fp) VALUES (?)",
                    (fp,),
                )
                if cur.rowcount == 0:
                    stats["removedCount"] += 1
                    if len(duplicate_ids) < max_duplicate_ids:
                        duplicate_ids.append(rec.id)
                    else:
                        stats["duplicateIdsTruncated"] = True
                    continue
                stats["outputCount"] += 1
                yield rec
            conn.commit()
            stats["duplicateIds"] = list(duplicate_ids)
            try:
                stats["spillBytes"] = db_path.stat().st_size if db_path.exists() else 0
            except OSError:
                stats["spillBytes"] = 0
            session.write_manifest(operation="exact_dedupe", stats=dict(stats))
            if scratch_manager is not None:
                scratch_manager.assert_within_quota(session)
        finally:
            conn.close()
            if owns_session and scratch_manager is not None:
                scratch_manager.cleanup_session(session.job_id)
                owns_session = False

    return _gen(), stats


def exact_dedupe_external_to_list(
    records: Iterable[CanonicalRecord],
    *,
    scratch_dir: Path,
    job_id: str = "dedupe",
) -> tuple[list[CanonicalRecord], dict[str, Any]]:
    """Helper for tests — runs external dedupe and materializes kept list."""
    mgr = ScratchManager(Path(scratch_dir))
    it, stats = iter_exact_dedupe_external(records, scratch_manager=mgr, job_id=job_id)
    return list(it), stats
