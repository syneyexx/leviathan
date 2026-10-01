"""Exact deduplication of canonical records — external-memory bounded.

P1-009 contracts:
- Deterministic winner: first occurrence (``winnerPolicy=first_occurrence``).
- Content fingerprint ignores id; same payload collapses with an explicit reason.
- Collapsed occurrences are recorded on the winner's ``metadata.lineage``.
- Cross-split / different-source collapses are detected and never silent.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Iterator

from Data.modules.common.hashing import sha256_text

from .scratch import ScratchManager, ScratchSession
from .storage_authority import StorageClass
from .types import CanonicalRecord, DatasetError

DEDUPE_REASON_EXACT_CONTENT = "exact_content_sha256"
WINNER_POLICY_FIRST = "first_occurrence"


def record_fingerprint(record: CanonicalRecord) -> str:
    """Exact content fingerprint (id excluded — dedupe by payload)."""
    payload = {
        "text": record.text,
        "messages": record.messages,
        "labels": record.labels,
    }
    return sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def _provenance_snapshot(record: CanonicalRecord) -> dict[str, Any]:
    meta = record.metadata or {}
    return {
        "id": record.id,
        "split": record.split,
        "source": meta.get("source"),
        "sourcePath": meta.get("sourcePath"),
        "sourceHash": meta.get("sourceHash"),
        "datasetId": meta.get("datasetId"),
        "versionId": meta.get("versionId"),
    }


def _source_identity(record: CanonicalRecord) -> str:
    meta = record.metadata or {}
    parts = [
        str(meta.get("sourceHash") or ""),
        str(meta.get("sourcePath") or ""),
        str(meta.get("source") or ""),
        str(meta.get("datasetId") or ""),
        str(meta.get("versionId") or ""),
    ]
    return "|".join(parts)


def _collapse_lineage_entry(
    *,
    winner: CanonicalRecord,
    collapsed: CanonicalRecord,
    reason: str,
) -> dict[str, Any]:
    cross_split = (winner.split or None) != (collapsed.split or None)
    cross_source = _source_identity(winner) != _source_identity(collapsed)
    return {
        "type": "dedupe_collapse",
        "reason": reason,
        "winnerPolicy": WINNER_POLICY_FIRST,
        "winnerId": winner.id,
        "winnerSplit": winner.split,
        "collapsedId": collapsed.id,
        "collapsedSplit": collapsed.split,
        "crossSplit": cross_split,
        "crossSource": cross_source,
        "collapsed": _provenance_snapshot(collapsed),
    }


def _append_lineage(record: CanonicalRecord, entry: dict[str, Any]) -> CanonicalRecord:
    meta = dict(record.metadata or {})
    lineage = list(meta.get("lineage") or []) if isinstance(meta.get("lineage"), list) else []
    lineage.append(entry)
    meta["lineage"] = lineage
    # Surface last dedupe reason for operators without scanning lineage.
    meta["dedupeReason"] = entry.get("reason")
    if entry.get("crossSplit"):
        meta["crossSplitDedupe"] = True
    if entry.get("crossSource"):
        meta["crossSourceDedupe"] = True
    return CanonicalRecord(
        id=record.id,
        text=record.text,
        messages=record.messages,
        labels=record.labels,
        metadata=meta,
        split=record.split,
    )


def _empty_stats(*, memory_mode: str, scratch_path: str | None = None) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "inputCount": 0,
        "outputCount": 0,
        "removedCount": 0,
        "duplicateIds": [],
        "duplicateIdsTruncated": False,
        "method": "exact_sha256",
        "memoryMode": memory_mode,
        "winnerPolicy": WINNER_POLICY_FIRST,
        "lineagePreserved": True,
        "reasons": {DEDUPE_REASON_EXACT_CONTENT: 0},
        "crossSplitDuplicateCount": 0,
        "crossSourceDuplicateCount": 0,
        "collapseEvents": [],
        "collapseEventsTruncated": False,
    }
    if scratch_path is not None:
        stats["scratchPath"] = scratch_path
        stats["storageClass"] = StorageClass.EPHEMERAL_SCRATCH.value
        stats["spillBytes"] = 0
    return stats


def exact_dedupe(records: list[CanonicalRecord]) -> tuple[list[CanonicalRecord], dict[str, Any]]:
    """In-memory exact dedupe — retained for small corpora / unit tests (Wave 12).

    Proof of retention: called by ``test_dataset_provenance_w8`` and
    ``test_native_data_plane_streaming_w142`` (parity vs external spill).
    Production large-corpus path: ``iter_exact_dedupe_external``.
    DatasetService must not import this list wrapper.
    """
    seen: dict[str, int] = {}
    kept: list[CanonicalRecord] = []
    duplicate_ids: list[str] = []
    stats = _empty_stats(memory_mode="in_memory")
    collapse_cap = 100

    for rec in records:
        stats["inputCount"] += 1
        fp = record_fingerprint(rec)
        if fp in seen:
            stats["removedCount"] += 1
            stats["reasons"][DEDUPE_REASON_EXACT_CONTENT] = (
                int(stats["reasons"].get(DEDUPE_REASON_EXACT_CONTENT) or 0) + 1
            )
            if len(duplicate_ids) < 100:
                duplicate_ids.append(rec.id)
            else:
                stats["duplicateIdsTruncated"] = True
            winner = kept[seen[fp]]
            entry = _collapse_lineage_entry(
                winner=winner, collapsed=rec, reason=DEDUPE_REASON_EXACT_CONTENT
            )
            if entry["crossSplit"]:
                stats["crossSplitDuplicateCount"] += 1
            if entry["crossSource"]:
                stats["crossSourceDuplicateCount"] += 1
            kept[seen[fp]] = _append_lineage(winner, entry)
            if len(stats["collapseEvents"]) < collapse_cap:
                stats["collapseEvents"].append(
                    {
                        "reason": entry["reason"],
                        "winnerId": entry["winnerId"],
                        "collapsedId": entry["collapsedId"],
                        "crossSplit": entry["crossSplit"],
                        "crossSource": entry["crossSource"],
                        "winnerSplit": entry["winnerSplit"],
                        "collapsedSplit": entry["collapsedSplit"],
                    }
                )
            else:
                stats["collapseEventsTruncated"] = True
            continue
        seen[fp] = len(kept)
        kept.append(rec)

    stats["outputCount"] = len(kept)
    stats["duplicateIds"] = duplicate_ids
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

    Two-phase: ingest into scratch (updating winner lineage on collapses), then
    emit winners in first-occurrence order. Scratch DB is never a durable authority.
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
            """
            CREATE TABLE seen (
                fp TEXT PRIMARY KEY NOT NULL,
                seq INTEGER NOT NULL,
                record_json TEXT NOT NULL
            ) WITHOUT ROWID
            """
        )
        conn.commit()
    except Exception:
        conn.close()
        if owns_session and scratch_manager is not None:
            scratch_manager.cleanup_session(session.job_id)
        raise

    stats = _empty_stats(
        memory_mode="external_sqlite_scratch",
        scratch_path=str(session.root),
    )
    duplicate_ids: list[str] = []
    collapse_cap = 100
    seq = 0

    def _gen() -> Iterator[CanonicalRecord]:
        nonlocal owns_session, seq
        try:
            for rec in records:
                stats["inputCount"] += 1
                fp = record_fingerprint(rec)
                existing = conn.execute(
                    "SELECT seq, record_json FROM seen WHERE fp=?",
                    (fp,),
                ).fetchone()
                if existing is not None:
                    stats["removedCount"] += 1
                    stats["reasons"][DEDUPE_REASON_EXACT_CONTENT] = (
                        int(stats["reasons"].get(DEDUPE_REASON_EXACT_CONTENT) or 0) + 1
                    )
                    if len(duplicate_ids) < max_duplicate_ids:
                        duplicate_ids.append(rec.id)
                    else:
                        stats["duplicateIdsTruncated"] = True
                    winner = CanonicalRecord.from_dict(json.loads(existing[1]))
                    entry = _collapse_lineage_entry(
                        winner=winner,
                        collapsed=rec,
                        reason=DEDUPE_REASON_EXACT_CONTENT,
                    )
                    if entry["crossSplit"]:
                        stats["crossSplitDuplicateCount"] += 1
                    if entry["crossSource"]:
                        stats["crossSourceDuplicateCount"] += 1
                    updated = _append_lineage(winner, entry)
                    conn.execute(
                        "UPDATE seen SET record_json=? WHERE fp=?",
                        (
                            json.dumps(updated.to_dict(), ensure_ascii=False, default=str),
                            fp,
                        ),
                    )
                    if len(stats["collapseEvents"]) < collapse_cap:
                        stats["collapseEvents"].append(
                            {
                                "reason": entry["reason"],
                                "winnerId": entry["winnerId"],
                                "collapsedId": entry["collapsedId"],
                                "crossSplit": entry["crossSplit"],
                                "crossSource": entry["crossSource"],
                                "winnerSplit": entry["winnerSplit"],
                                "collapsedSplit": entry["collapsedSplit"],
                            }
                        )
                    else:
                        stats["collapseEventsTruncated"] = True
                    continue
                conn.execute(
                    "INSERT INTO seen(fp, seq, record_json) VALUES (?, ?, ?)",
                    (
                        fp,
                        seq,
                        json.dumps(rec.to_dict(), ensure_ascii=False, default=str),
                    ),
                )
                seq += 1

            conn.commit()
            rows = conn.execute(
                "SELECT record_json FROM seen ORDER BY seq ASC"
            ).fetchall()
            for (blob,) in rows:
                stats["outputCount"] += 1
                yield CanonicalRecord.from_dict(json.loads(blob))

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
