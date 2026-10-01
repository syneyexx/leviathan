"""Wave 4 / P0-006 — Duplicate record ID validation (memory-bounded)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.datasets.materialize import write_canonical_jsonl_stream
from Data.modules.datasets.scratch import ScratchManager
from Data.modules.datasets.types import CanonicalRecord, VersionStatus
from Data.modules.datasets.validation import (
    IdIntegrityTracker,
    open_id_integrity_tracker,
    validate_records,
)


def _rec(rid: str, text: str) -> CanonicalRecord:
    return CanonicalRecord(id=rid, text=text)


class DuplicateIdValidationW4Tests(unittest.TestCase):
    def test_empty_id_fails(self) -> None:
        report = validate_records([_rec("", "hello"), _rec("  ", "world")])
        self.assertFalse(report["valid"])
        codes = {i["code"] for i in report["issues"]}
        self.assertIn("missing_id", codes)

    def test_same_id_different_content_fails(self) -> None:
        records = [
            _rec("a", "alpha"),
            _rec("b", "beta"),
            _rec("a", "ALPHA-DIFFERENT"),
        ]
        report = validate_records(records)
        self.assertFalse(report["valid"])
        self.assertGreaterEqual(report["duplicateIdConflictCount"], 1)
        codes = {i["code"] for i in report["issues"]}
        self.assertIn("duplicate_id_conflict", codes)

    def test_same_id_same_content_dedupes_with_provenance(self) -> None:
        records = [
            _rec("a", "same"),
            _rec("b", "other"),
            _rec("a", "same"),
        ]
        report = validate_records(records)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["identicalDuplicateIdCount"], 1)
        self.assertEqual(report["duplicateIdConflictCount"], 0)
        self.assertIn("provenance", report)
        self.assertEqual(report["provenance"]["identicalDuplicateIdsDeduped"], 1)

    def test_duplicates_far_apart_use_sqlite_spill(self) -> None:
        """Simulate distant duplicates without unbounded RAM (external SQLite)."""
        with tempfile.TemporaryDirectory() as tmp:
            mgr = ScratchManager(Path(tmp) / "scratch")

            def _gen():
                yield _rec("far-id", "payload-v1")
                for i in range(5000):
                    yield _rec(f"unique-{i}", f"text-{i}")
                yield _rec("far-id", "payload-CONFLICT")

            report = validate_records(
                _gen(),
                scratch_manager=mgr,
                job_id="w4-far",
            )
            self.assertFalse(report["valid"])
            self.assertEqual(report["duplicateIdConflictCount"], 1)
            integrity = report["idIntegrity"]
            self.assertEqual(integrity["memoryMode"], "external_sqlite_scratch")
            self.assertGreaterEqual(integrity["spillBytes"], 0)
            self.assertGreaterEqual(integrity["uniqueIdCount"], 5000)

    def test_materialize_conflict_cannot_be_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out.jsonl"
            records = [
                _rec("x", "one"),
                _rec("x", "two"),
            ]
            outcome = write_canonical_jsonl_stream(records, dest)
            validation = outcome["validation"]
            self.assertFalse(validation["valid"])
            self.assertGreaterEqual(validation["duplicateIdConflictCount"], 1)
            # Publishing gate uses validation.valid — FAILED, not READY.
            status = (
                VersionStatus.READY if validation.get("valid") else VersionStatus.FAILED
            )
            self.assertEqual(status, VersionStatus.FAILED)

    def test_materialize_identical_dedupes_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "dedupe.jsonl"
            records = [
                _rec("x", "same"),
                _rec("y", "keep"),
                _rec("x", "same"),
            ]
            outcome = write_canonical_jsonl_stream(records, dest)
            validation = outcome["validation"]
            self.assertTrue(validation["valid"], validation)
            self.assertEqual(outcome["rowCount"], 2)  # written unique
            self.assertEqual(outcome["inputRowCount"], 3)
            self.assertEqual(validation["identicalDuplicateIdCount"], 1)
            lines = [ln for ln in dest.read_text(encoding="utf-8").splitlines() if ln.strip()]
            self.assertEqual(len(lines), 2)

    def test_tracker_is_memory_bounded_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker, _session, _owns, tmp_dir = open_id_integrity_tracker(
                scratch_dir=Path(tmp)
            )
            try:
                self.assertIsInstance(tracker, IdIntegrityTracker)
                for i in range(100):
                    tracker.observe(f"id-{i}", f"fp-{i}", index=i)
                # conflict far from first
                tracker.observe("id-0", "fp-OTHER", index=10_000)
                summary = tracker.summary()
                self.assertEqual(summary["duplicateIdConflictCount"], 1)
                self.assertEqual(summary["uniqueIdCount"], 100)
            finally:
                tracker.close()
                if tmp_dir is not None:
                    tmp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
