"""Wave 6 / P1-002 — RAW must not become false READY_FOR_INDEX."""

from __future__ import annotations

import unittest

from Data.modules.datasets.learning_state import (
    DatasetLearningCanonicalState,
    _INDEXABLE_VERSION_KINDS,
    _pick_indexable_version,
    compute_dataset_learning_state,
)
from Data.modules.datasets.types import (
    DatasetRecord,
    DatasetStatus,
    SourceType,
    VersionKind,
    VersionStatus,
    DatasetVersion,
)


def _ds(
    *,
    dataset_id: str = "ds1",
    status: DatasetStatus = DatasetStatus.READY,
    raw_path: str | None = "/tmp/raw.jsonl",
    source_missing: bool = False,
) -> DatasetRecord:
    return DatasetRecord(
        dataset_id=dataset_id,
        name="n",
        source_type=SourceType.LOCAL,
        status=status,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        raw_path=raw_path,
        metadata={"sourceMissing": True} if source_missing else {},
    )


def _ver(
    *,
    version_id: str,
    kind: VersionKind,
    status: VersionStatus = VersionStatus.READY,
    updated_at: str = "2026-01-01T00:00:00Z",
    validation: dict | None = None,
) -> DatasetVersion:
    return DatasetVersion(
        version_id=version_id,
        dataset_id="ds1",
        version_label=version_id,
        kind=kind,
        status=status,
        created_at=updated_at,
        updated_at=updated_at,
        validation=validation if validation is not None else {"valid": True},
    )


class LearningRawW6Tests(unittest.TestCase):
    def test_indexable_kinds_exclude_raw(self) -> None:
        self.assertNotIn(VersionKind.RAW, _INDEXABLE_VERSION_KINDS)
        self.assertEqual(
            _INDEXABLE_VERSION_KINDS,
            {
                VersionKind.MATERIALIZED,
                VersionKind.TRANSFORMED,
                VersionKind.SPLIT,
                VersionKind.EXPORT,
            },
        )

    def test_raw_only_is_source_ready_not_ready_for_index(self) -> None:
        state = compute_dataset_learning_state(
            dataset=_ds(),
            versions=[_ver(version_id="raw1", kind=VersionKind.RAW)],
            indexes=[],
            jobs=[],
        )
        self.assertEqual(
            state.canonical_state, DatasetLearningCanonicalState.SOURCE_READY
        )
        self.assertNotEqual(
            state.canonical_state, DatasetLearningCanonicalState.READY_FOR_INDEX
        )

    def test_materialized_failed_not_ready_for_index(self) -> None:
        versions = [
            _ver(version_id="raw1", kind=VersionKind.RAW),
            _ver(
                version_id="mat1",
                kind=VersionKind.MATERIALIZED,
                status=VersionStatus.FAILED,
                validation={"valid": False},
            ),
        ]
        state = compute_dataset_learning_state(
            dataset=_ds(),
            versions=versions,
            indexes=[],
            jobs=[],
        )
        self.assertEqual(
            state.canonical_state, DatasetLearningCanonicalState.SOURCE_READY
        )
        self.assertIsNone(_pick_indexable_version(versions))

    def test_materialized_ready_is_ready_for_index(self) -> None:
        versions = [
            _ver(version_id="raw1", kind=VersionKind.RAW),
            _ver(version_id="mat1", kind=VersionKind.MATERIALIZED),
        ]
        state = compute_dataset_learning_state(
            dataset=_ds(),
            versions=versions,
            indexes=[],
            jobs=[],
        )
        self.assertEqual(
            state.canonical_state, DatasetLearningCanonicalState.READY_FOR_INDEX
        )
        picked = _pick_indexable_version(versions)
        assert picked is not None
        self.assertEqual(picked.kind, VersionKind.MATERIALIZED)

    def test_transformed_and_split_ready(self) -> None:
        for kind in (VersionKind.TRANSFORMED, VersionKind.SPLIT, VersionKind.EXPORT):
            state = compute_dataset_learning_state(
                dataset=_ds(),
                versions=[_ver(version_id=f"v-{kind.value}", kind=kind)],
                indexes=[],
                jobs=[],
            )
            self.assertEqual(
                state.canonical_state,
                DatasetLearningCanonicalState.READY_FOR_INDEX,
                kind,
            )

    def test_current_raw_with_older_materialized_prefers_materialized(self) -> None:
        versions = [
            _ver(
                version_id="mat-old",
                kind=VersionKind.MATERIALIZED,
                updated_at="2026-01-01T00:00:00Z",
            ),
            _ver(
                version_id="raw-new",
                kind=VersionKind.RAW,
                updated_at="2026-06-01T00:00:00Z",
            ),
        ]
        picked = _pick_indexable_version(versions)
        assert picked is not None
        self.assertEqual(picked.version_id, "mat-old")
        state = compute_dataset_learning_state(
            dataset=_ds(),
            versions=versions,
            indexes=[],
            jobs=[],
        )
        self.assertEqual(
            state.canonical_state, DatasetLearningCanonicalState.READY_FOR_INDEX
        )
        self.assertEqual(state.version_id, "mat-old")

    def test_source_missing(self) -> None:
        state = compute_dataset_learning_state(
            dataset=_ds(source_missing=True, raw_path=None),
            versions=[_ver(version_id="raw1", kind=VersionKind.RAW)],
            indexes=[],
            jobs=[],
        )
        self.assertEqual(
            state.canonical_state, DatasetLearningCanonicalState.SOURCE_MISSING
        )


if __name__ == "__main__":
    unittest.main()
