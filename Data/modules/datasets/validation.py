"""Validate canonical dataset records.

Includes scalable, memory-bounded duplicate-ID integrity checks (P0-006).
Same id + different content → FAIL; same id + same content → may dedupe with
provenance; empty id → fail. Spill uses ephemeral SQLite so duplicates separated
by millions of records do not require unbounded RAM.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Iterable, Iterator

from Data.modules.common.hashing import sha256_text

from .scratch import ScratchManager, ScratchSession
from .storage_authority import StorageClass
from .types import CanonicalRecord, DatasetError


def record_content_fingerprint(record: CanonicalRecord) -> str:
    """Content fingerprint for ID-integrity (id excluded)."""
    payload = {
        "text": record.text,
        "messages": record.messages,
        "labels": record.labels,
        "split": record.split,
    }
    return sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def validate_record(record: CanonicalRecord, *, index: int = 0) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not record.id or not str(record.id).strip():
        issues.append({"index": index, "field": "id", "code": "missing_id", "message": "id is required"})
    has_text = bool(record.text and str(record.text).strip())
    has_messages = bool(record.messages)
    if not has_text and not has_messages:
        issues.append(
            {
                "index": index,
                "field": "text",
                "code": "empty_content",
                "message": "record needs text or messages",
            }
        )
    if record.messages is not None:
        if not isinstance(record.messages, list):
            issues.append(
                {
                    "index": index,
                    "field": "messages",
                    "code": "invalid_messages",
                    "message": "messages must be a list",
                }
            )
        else:
            for mi, msg in enumerate(record.messages):
                if not isinstance(msg, dict):
                    issues.append(
                        {
                            "index": index,
                            "field": f"messages[{mi}]",
                            "code": "invalid_message",
                            "message": "each message must be an object",
                        }
                    )
                    continue
                if "content" not in msg and "text" not in msg:
                    issues.append(
                        {
                            "index": index,
                            "field": f"messages[{mi}]",
                            "code": "message_missing_content",
                            "message": "message needs content or text",
                        }
                    )
    if record.split is not None and record.split not in {"train", "validation", "val", "test", "dev"}:
        issues.append(
            {
                "index": index,
                "field": "split",
                "code": "unknown_split",
                "message": f"unexpected split label: {record.split}",
                "severity": "warning",
            }
        )
    return issues


class IdIntegrityTracker:
    """External-memory duplicate-ID detector (EPHEMERAL_SCRATCH SQLite).

    Policy:
      - empty id → caller must already fail via validate_record
      - same id + different content → conflict (FAIL)
      - same id + same content → identical duplicate (may dedupe; does not fail)
    """

    def __init__(
        self,
        db_path: Path,
        *,
        max_conflict_samples: int = 50,
        max_identical_samples: int = 50,
    ) -> None:
        self.db_path = Path(db_path)
        self.max_conflict_samples = int(max_conflict_samples)
        self.max_identical_samples = int(max_identical_samples)
        self.unique_ids = 0
        self.conflict_count = 0
        self.identical_duplicate_count = 0
        self.conflict_samples: list[dict[str, Any]] = []
        self.identical_samples: list[dict[str, Any]] = []
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA journal_mode=OFF")
        self._conn.execute("PRAGMA synchronous=OFF")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS id_seen (
                id TEXT PRIMARY KEY NOT NULL,
                content_fp TEXT NOT NULL,
                first_index INTEGER NOT NULL
            ) WITHOUT ROWID
            """
        )
        self._conn.commit()

    def observe(self, record_id: str, content_fp: str, *, index: int) -> dict[str, Any] | None:
        """Observe one record id. Returns an issue dict on conflict, else None.

        Identical duplicates return a soft issue with severity=warning and
        code=identical_duplicate_id (does not fail validation by itself).
        Conflicts return severity=error / code=duplicate_id_conflict.
        """
        rid = str(record_id or "").strip()
        if not rid:
            return None
        cur = self._conn.execute(
            "SELECT content_fp, first_index FROM id_seen WHERE id = ?",
            (rid,),
        )
        row = cur.fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO id_seen(id, content_fp, first_index) VALUES (?, ?, ?)",
                (rid, content_fp, int(index)),
            )
            self.unique_ids += 1
            return None
        prior_fp, first_index = row[0], int(row[1])
        if prior_fp == content_fp:
            self.identical_duplicate_count += 1
            sample = {
                "index": index,
                "field": "id",
                "code": "identical_duplicate_id",
                "message": f"identical duplicate id {rid!r} (first at {first_index})",
                "severity": "warning",
                "id": rid,
                "firstIndex": first_index,
            }
            if len(self.identical_samples) < self.max_identical_samples:
                self.identical_samples.append(sample)
            return sample
        self.conflict_count += 1
        sample = {
            "index": index,
            "field": "id",
            "code": "duplicate_id_conflict",
            "message": (
                f"duplicate id {rid!r} with different content "
                f"(first at {first_index})"
            ),
            "id": rid,
            "firstIndex": first_index,
        }
        if len(self.conflict_samples) < self.max_conflict_samples:
            self.conflict_samples.append(sample)
        return sample

    def is_first_occurrence(self, record_id: str, content_fp: str) -> bool:
        """True if this id+content is the first seen occurrence (keep); False to skip.

        Conflicts are still recorded via ``observe`` — callers deciding whether
        to write should treat conflicts as fail and identicals as skippable.
        """
        rid = str(record_id or "").strip()
        if not rid:
            return True
        cur = self._conn.execute(
            "SELECT content_fp FROM id_seen WHERE id = ?",
            (rid,),
        )
        row = cur.fetchone()
        if row is None:
            return True
        return False  # already seen (identical or conflict)

    def flush(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.commit()
        finally:
            self._conn.close()

    def spill_bytes(self) -> int:
        try:
            return self.db_path.stat().st_size if self.db_path.exists() else 0
        except OSError:
            return 0

    def summary(self) -> dict[str, Any]:
        return {
            "uniqueIdCount": self.unique_ids,
            "duplicateIdConflictCount": self.conflict_count,
            "identicalDuplicateIdCount": self.identical_duplicate_count,
            "conflictSamples": list(self.conflict_samples),
            "identicalDuplicateSamples": list(self.identical_samples),
            "conflictSamplesTruncated": self.conflict_count > len(self.conflict_samples),
            "identicalSamplesTruncated": self.identical_duplicate_count
            > len(self.identical_samples),
            "memoryMode": "external_sqlite_scratch",
            "storageClass": StorageClass.EPHEMERAL_SCRATCH.value,
            "spillBytes": self.spill_bytes(),
            "truth": {
                "same_id_different_content_fails": True,
                "same_id_same_content_may_dedupe": True,
                "empty_id_fails": True,
                "unbounded_in_memory_id_set_forbidden": True,
            },
        }


def open_id_integrity_tracker(
    *,
    scratch: ScratchSession | None = None,
    scratch_manager: ScratchManager | None = None,
    job_id: str = "id-integrity",
    scratch_dir: Path | None = None,
    db_name: str = "id_integrity.sqlite",
) -> tuple[IdIntegrityTracker, ScratchSession | None, bool, tempfile.TemporaryDirectory[str] | None]:
    """Open a tracker backed by scratch SQLite.

    Returns ``(tracker, session, owns_session, tmp_dir)``. Caller must
    ``tracker.close()`` and cleanup owned session / tmp_dir.
    """
    owns_session = False
    tmp_dir: tempfile.TemporaryDirectory[str] | None = None
    session = scratch
    if session is None and scratch_manager is not None:
        session = scratch_manager.open_session(job_id)
        owns_session = True
    if session is not None:
        db_path = session.path(db_name)
        if db_path.name.lower() in {
            "knowledge.db",
            "trading.db",
            "datasets.db",
            "control.db",
            "simulation.db",
        }:
            raise DatasetError("Forbidden scratch DB name", code="forbidden_scratch_db")
        return IdIntegrityTracker(db_path), session, owns_session, None
    if scratch_dir is not None:
        root = Path(scratch_dir)
        root.mkdir(parents=True, exist_ok=True)
        return IdIntegrityTracker(root / db_name), None, False, None
    tmp_dir = tempfile.TemporaryDirectory(prefix="dataset-id-integrity-")
    return IdIntegrityTracker(Path(tmp_dir.name) / db_name), None, False, tmp_dir


def apply_id_integrity_to_report(
    report: dict[str, Any],
    integrity: dict[str, Any],
) -> dict[str, Any]:
    """Merge ID-integrity summary into a validation report (mutates + returns)."""
    conflicts = int(integrity.get("duplicateIdConflictCount") or 0)
    identical = int(integrity.get("identicalDuplicateIdCount") or 0)
    report["idIntegrity"] = integrity
    report["duplicateIdConflictCount"] = conflicts
    report["identicalDuplicateIdCount"] = identical
    report["uniqueIdCount"] = integrity.get("uniqueIdCount")
    # Conflicts are hard errors.
    if conflicts:
        report["errorCount"] = int(report.get("errorCount") or 0) + conflicts
        report["valid"] = False
        issues = list(report.get("issues") or [])
        max_issues = 200
        for sample in integrity.get("conflictSamples") or []:
            if len(issues) >= max_issues:
                report["issuesTruncated"] = True
                report["truncated"] = True
                break
            issues.append(sample)
        report["issues"] = issues
    # Identical duplicates are warnings + provenance (do not invalidate alone).
    if identical:
        report["warningCount"] = int(report.get("warningCount") or 0) + identical
        issues = list(report.get("issues") or [])
        max_issues = 200
        for sample in integrity.get("identicalDuplicateSamples") or []:
            if len(issues) >= max_issues:
                report["issuesTruncated"] = True
                report["truncated"] = True
                break
            if sample not in issues:
                issues.append(sample)
        report["issues"] = issues
        report.setdefault("provenance", {})
        if isinstance(report["provenance"], dict):
            report["provenance"]["identicalDuplicateIdsDeduped"] = identical
            report["provenance"]["idIntegrity"] = {
                "uniqueIdCount": integrity.get("uniqueIdCount"),
                "identicalDuplicateIdCount": identical,
                "duplicateIdConflictCount": conflicts,
            }
    return report


def validate_records(
    records: Iterable[CanonicalRecord],
    *,
    max_issues: int = 200,
    check_duplicate_ids: bool = True,
    scratch: ScratchSession | None = None,
    scratch_manager: ScratchManager | None = None,
    scratch_dir: Path | None = None,
    job_id: str = "validate-id-integrity",
) -> dict[str, Any]:
    """Validate records incrementally — works for lists or streaming iterables.

    ``errorCount`` / ``warningCount`` are true totals even when the issue sample
    is truncated at ``max_issues``. Duplicate-ID detection uses external SQLite
    spill so it stays memory-bounded for large corpora.
    """
    all_issues: list[dict[str, Any]] = []
    empty = 0
    row_count = 0
    error_count = 0
    warning_count = 0
    tracker: IdIntegrityTracker | None = None
    session: ScratchSession | None = None
    owns_session = False
    tmp_dir: tempfile.TemporaryDirectory[str] | None = None
    scratch_mgr = scratch_manager
    try:
        if check_duplicate_ids:
            tracker, session, owns_session, tmp_dir = open_id_integrity_tracker(
                scratch=scratch,
                scratch_manager=scratch_mgr,
                scratch_dir=scratch_dir,
                job_id=job_id,
            )
        for idx, rec in enumerate(records):
            row_count += 1
            issues = validate_record(rec, index=idx)
            if any(i.get("code") == "empty_content" for i in issues):
                empty += 1
            if tracker is not None and rec.id and str(rec.id).strip():
                id_issue = tracker.observe(
                    str(rec.id),
                    record_content_fingerprint(rec),
                    index=idx,
                )
                if id_issue is not None and id_issue.get("code") == "duplicate_id_conflict":
                    issues.append(id_issue)
                elif id_issue is not None and id_issue.get("code") == "identical_duplicate_id":
                    issues.append(id_issue)
            for issue in issues:
                if issue.get("severity") == "warning":
                    warning_count += 1
                else:
                    error_count += 1
                if len(all_issues) < max_issues:
                    all_issues.append(issue)
        if tracker is not None:
            tracker.flush()
        truncated = (error_count + warning_count) > len(all_issues)
        report: dict[str, Any] = {
            "valid": error_count == 0,
            "rowCount": row_count,
            "errorCount": error_count,
            "warningCount": warning_count,
            "emptyContentCount": empty,
            "issues": all_issues,
            "issuesTruncated": truncated,
            "truncated": truncated,
        }
        if tracker is not None:
            integrity = tracker.summary()
            # Counts already included in error/warning loops for samples observed
            # inline; still attach the integrity block for operators.
            report["idIntegrity"] = integrity
            report["duplicateIdConflictCount"] = integrity["duplicateIdConflictCount"]
            report["identicalDuplicateIdCount"] = integrity["identicalDuplicateIdCount"]
            report["uniqueIdCount"] = integrity["uniqueIdCount"]
            if integrity["identicalDuplicateIdCount"]:
                report.setdefault("provenance", {})
                if isinstance(report["provenance"], dict):
                    report["provenance"]["identicalDuplicateIdsDeduped"] = integrity[
                        "identicalDuplicateIdCount"
                    ]
            if session is not None:
                session.write_manifest(operation="id_integrity", stats=dict(integrity))
                if scratch_mgr is not None:
                    scratch_mgr.assert_within_quota(session)
        return report
    finally:
        if tracker is not None:
            tracker.close()
        if owns_session and scratch_mgr is not None and session is not None:
            scratch_mgr.cleanup_session(session.job_id)
        if tmp_dir is not None:
            tmp_dir.cleanup()


def iter_dedupe_identical_ids(
    records: Iterable[CanonicalRecord],
    tracker: IdIntegrityTracker,
) -> Iterator[tuple[CanonicalRecord, list[dict[str, Any]], bool]]:
    """Yield ``(record, issues, keep)`` while recording ID integrity on ``tracker``.

    ``keep`` is False for identical duplicate ids (same content) so materialize
    can skip writing them. Conflicts still yield keep=True for the first
    occurrence only; subsequent conflicting rows yield keep=False and an error
    issue (caller must fail the batch).
    """
    for idx, rec in enumerate(records):
        issues = validate_record(rec, index=idx)
        keep = True
        if rec.id and str(rec.id).strip():
            fp = record_content_fingerprint(rec)
            already = not tracker.is_first_occurrence(str(rec.id), fp)
            id_issue = tracker.observe(str(rec.id), fp, index=idx)
            if id_issue is not None:
                issues.append(id_issue)
            if already:
                keep = False
        yield rec, issues, keep
