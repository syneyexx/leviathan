"""Wave 1 — latest-only validation aggregates for catalog overview KPIs."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import (
    DatasetStatus,
    SourceType,
    VersionKind,
    VersionStatus,
)


class ValidationAggregateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "leviathan.db"
        self.store = DatasetStore(self.db)
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _ds(self, name: str = "ds"):
        return self.store.create_dataset(
            name=name,
            source_type=SourceType.LOCAL,
            status=DatasetStatus.READY,
        )

    def test_newer_fewer_errors_wins(self) -> None:
        ds = self._ds("fewer")
        v1 = self.store.create_version(
            dataset_id=ds.dataset_id,
            version_label="v1",
            kind=VersionKind.MATERIALIZED,
            status=VersionStatus.READY,
        )
        self.store.update_version(
            v1.version_id,
            validation={"errorCount": 10, "warningCount": 5},
        )
        time.sleep(1.1)  # updated_at is second-resolution ISO
        v2 = self.store.create_version(
            dataset_id=ds.dataset_id,
            version_label="v2",
            kind=VersionKind.MATERIALIZED,
            status=VersionStatus.READY,
        )
        self.store.update_version(
            v2.version_id,
            validation={"errorCount": 1, "warningCount": 0},
        )
        stats = self.store.aggregate_catalog_stats()
        self.assertEqual(stats["datasetsWithValidation"], 1)
        self.assertEqual(stats["versionsWithValidation"], 1)
        self.assertEqual(stats["criticalValidationIssues"], 1)
        self.assertEqual(stats["warningValidationIssues"], 0)
        self.assertEqual(stats["validationIssues"], 1)

    def test_newer_more_errors_wins(self) -> None:
        ds = self._ds("more")
        v1 = self.store.create_version(
            dataset_id=ds.dataset_id,
            version_label="v1",
            kind=VersionKind.MATERIALIZED,
            status=VersionStatus.READY,
        )
        self.store.update_version(
            v1.version_id,
            validation={"errorCount": 1, "warningCount": 0},
        )
        time.sleep(1.1)
        v2 = self.store.create_version(
            dataset_id=ds.dataset_id,
            version_label="v2",
            kind=VersionKind.MATERIALIZED,
            status=VersionStatus.READY,
        )
        self.store.update_version(
            v2.version_id,
            validation={"errorCount": 7, "warningCount": 2},
        )
        stats = self.store.aggregate_catalog_stats()
        self.assertEqual(stats["criticalValidationIssues"], 7)
        self.assertEqual(stats["warningValidationIssues"], 2)
        self.assertEqual(stats["validationIssues"], 9)

    def test_no_validation_and_empty_json(self) -> None:
        ds_a = self._ds("none")
        self.store.create_version(
            dataset_id=ds_a.dataset_id,
            version_label="v0",
            kind=VersionKind.MATERIALIZED,
            status=VersionStatus.READY,
        )
        ds_b = self._ds("empty")
        vb = self.store.create_version(
            dataset_id=ds_b.dataset_id,
            version_label="v0",
            kind=VersionKind.MATERIALIZED,
            status=VersionStatus.READY,
        )
        self.store.update_version(vb.version_id, validation={})
        stats = self.store.aggregate_catalog_stats()
        self.assertEqual(stats["datasetsWithValidation"], 0)
        self.assertEqual(stats["datasetsWithoutValidation"], 2)
        self.assertEqual(stats["validationIssues"], 0)
        self.assertEqual(stats["readyDatasets"], 2)

    def test_error_count_zero_does_not_fallthrough_to_errors_list(self) -> None:
        ds = self._ds("zero")
        v = self.store.create_version(
            dataset_id=ds.dataset_id,
            version_label="v0",
            kind=VersionKind.MATERIALIZED,
            status=VersionStatus.READY,
        )
        self.store.update_version(
            v.version_id,
            validation={
                "errorCount": 0,
                "errors": [{"msg": "legacy"}, {"msg": "legacy2"}],
                "warningCount": 0,
                "warnings": [{"msg": "w"}],
            },
        )
        stats = self.store.aggregate_catalog_stats()
        self.assertEqual(stats["criticalValidationIssues"], 0)
        self.assertEqual(stats["warningValidationIssues"], 0)

    def test_errors_list_length_when_no_count(self) -> None:
        ds = self._ds("list")
        v = self.store.create_version(
            dataset_id=ds.dataset_id,
            version_label="v0",
            kind=VersionKind.MATERIALIZED,
            status=VersionStatus.READY,
        )
        self.store.update_version(
            v.version_id,
            validation={"errors": [{"a": 1}, {"b": 2}, {"c": 3}], "warnings": [{"w": 1}]},
        )
        stats = self.store.aggregate_catalog_stats()
        self.assertEqual(stats["criticalValidationIssues"], 3)
        self.assertEqual(stats["warningValidationIssues"], 1)

    def test_malformed_validation_safe(self) -> None:
        ds = self._ds("bad")
        v = self.store.create_version(
            dataset_id=ds.dataset_id,
            version_label="v0",
            kind=VersionKind.MATERIALIZED,
            status=VersionStatus.READY,
        )
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE dataset_versions SET validation_json = ?, updated_at = updated_at WHERE version_id = ?",
                ("{not-json", v.version_id),
            )
        stats = self.store.aggregate_catalog_stats()
        self.assertEqual(stats["datasetsWithValidation"], 0)
        self.assertEqual(stats["validationIssues"], 0)

    def test_tie_break_version_id_desc(self) -> None:
        ds = self._ds("tie")
        # Force identical updated_at via direct SQL after both validations written.
        v1 = self.store.create_version(
            dataset_id=ds.dataset_id,
            version_label="v1",
            kind=VersionKind.MATERIALIZED,
            status=VersionStatus.READY,
        )
        v2 = self.store.create_version(
            dataset_id=ds.dataset_id,
            version_label="v2",
            kind=VersionKind.MATERIALIZED,
            status=VersionStatus.READY,
        )
        stamp = "2020-01-01T00:00:00+00:00"
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE dataset_versions SET validation_json = ?, updated_at = ? WHERE version_id = ?",
                ('{"errorCount": 9, "warningCount": 0}', stamp, v1.version_id),
            )
            conn.execute(
                "UPDATE dataset_versions SET validation_json = ?, updated_at = ? WHERE version_id = ?",
                ('{"errorCount": 2, "warningCount": 1}', stamp, v2.version_id),
            )
        # Higher version_id wins when updated_at ties.
        winner_id = max(v1.version_id, v2.version_id)
        expected_errors = 2 if winner_id == v2.version_id else 9
        expected_warnings = 1 if winner_id == v2.version_id else 0
        stats = self.store.aggregate_catalog_stats()
        self.assertEqual(stats["criticalValidationIssues"], expected_errors)
        self.assertEqual(stats["warningValidationIssues"], expected_warnings)
        latest = self.store.latest_version_validation_map([ds.dataset_id])
        self.assertEqual(latest[ds.dataset_id]["errorCount"], expected_errors)


if __name__ == "__main__":
    unittest.main()
