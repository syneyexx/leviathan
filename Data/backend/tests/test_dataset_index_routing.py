"""Regression tests: dataset index routing must never open RAW directories as JSONL."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.common.corpus import CorpusLayout
from Data.modules.datasets.indexing import index_version_file
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import (
    DatasetError,
    DatasetJobStatus,
    DatasetStatus,
    SourceType,
    VersionKind,
    VersionStatus,
)
from Data.modules.knowledge import KnowledgeStore


def _layout(root: Path) -> CorpusLayout:
    layout = CorpusLayout(
        root=root,
        datasets=root / "datasets",
        datasets_raw=root / "datasets" / "raw",
        datasets_materialized=root / "datasets" / "materialized",
        datasets_processed=root / "datasets" / "processed",
        datasets_exports=root / "datasets" / "exports",
        datasets_manifests=root / "datasets" / "manifests",
        training=root / "training",
        training_jobs=root / "training" / "jobs",
        training_runs=root / "training" / "runs",
        training_checkpoints=root / "training" / "checkpoints",
        training_adapters=root / "training" / "adapters",
        training_exports=root / "training" / "exports",
        training_logs=root / "training" / "logs",
        research=root / "research",
        research_projects=root / "research" / "projects",
        research_sources=root / "research" / "sources",
        research_snapshots=root / "research" / "snapshots",
        research_reports=root / "research" / "reports",
        research_exports=root / "research" / "exports",
        models_artifacts=root / "models" / "artifacts",
        models_cache=root / "models" / "cache",
        hf_cache=root / "hf_cache",
    )
    return layout.ensure()


class DatasetIndexRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "db.sqlite"
        self.corpus = _layout(self.root / "corpus")
        self.import_root = self.root / "imports"
        self.import_root.mkdir()
        self.knowledge = KnowledgeStore(self.db, data_root=self.root / "k")
        self.knowledge.initialize()
        self.store = DatasetStore(self.db)
        self.store.initialize()
        self.service = DatasetService(
            self.store,
            corpus=self.corpus,
            knowledge=self.knowledge,
            allowed_import_roots=[self.import_root, self.corpus.root],
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _create_dataset(self, name: str = "ds") -> str:
        ds = self.store.create_dataset(
            name=name,
            source_type=SourceType.HUGGINGFACE,
            status=DatasetStatus.READY,
        )
        return ds.dataset_id

    def _write_canonical(self, dataset_id: str, rows: list[dict] | None = None) -> Path:
        rows = rows or [
            {"id": "1", "text": "alpha leviathan knowledge"},
            {"id": "2", "text": "beta dataset indexing"},
        ]
        dest = self.corpus.datasets_materialized / dataset_id / "canonical.jsonl"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n",
            encoding="utf-8",
        )
        return dest

    def _add_version(
        self,
        dataset_id: str,
        *,
        kind: VersionKind,
        storage_path: str | None,
        label: str,
        status: VersionStatus = VersionStatus.READY,
        content_hash: str | None = "hash-test",
    ):
        ver = self.store.create_version(
            dataset_id=dataset_id,
            version_label=label,
            kind=kind,
            status=status,
            storage_path=storage_path,
        )
        if content_hash is not None or storage_path:
            path = Path(storage_path) if storage_path else None
            byte_size = path.stat().st_size if path and path.is_file() else (0 if path and path.is_dir() else None)
            self.store.update_version(
                ver.version_id,
                content_hash=content_hash,
                byte_size=byte_size,
                row_count=2 if path and path.is_file() else None,
            )
        return self.service.get_version(ver.version_id)

    def test_materialized_version_indexes_directly(self) -> None:
        dataset_id = self._create_dataset("mat-direct")
        path = self._write_canonical(dataset_id)
        mat = self._add_version(
            dataset_id,
            kind=VersionKind.MATERIALIZED,
            storage_path=str(path),
            label="materialized-v1",
        )

        resolved = self.service._resolve_indexable_version(dataset_id, mat.version_id)
        self.assertEqual(resolved.version_id, mat.version_id)

        job = self.service.enqueue_index(dataset_id, mat.version_id)
        self.assertEqual(job.version_id, mat.version_id)
        self.assertEqual(job.config.get("requestedVersionId"), mat.version_id)
        self.assertEqual(job.config.get("resolvedVersionId"), mat.version_id)

        done = self.service.process_jobs(max_jobs=1)[0]
        self.assertEqual(done.status, DatasetJobStatus.COMPLETED, done.error)
        self.assertEqual(done.result["versionId"], mat.version_id)
        self.assertEqual(done.result["resolvedVersionId"], mat.version_id)
        self.assertGreater(done.result["documentCount"], 0)

        indexes = self.store.list_indexes(dataset_id)
        self.assertEqual(len(indexes), 1)
        self.assertEqual(indexes[0].version_id, mat.version_id)

    def test_raw_hf_directory_resolves_to_materialized(self) -> None:
        dataset_id = self._create_dataset("hf-raw")
        hf_dir = self.corpus.datasets_raw / dataset_id / "hf"
        hf_dir.mkdir(parents=True, exist_ok=True)
        (hf_dir / "train.jsonl").write_text('{"id":"x","text":"raw shard"}\n', encoding="utf-8")
        raw = self._add_version(
            dataset_id,
            kind=VersionKind.RAW,
            storage_path=str(hf_dir),
            label="raw-v1",
        )
        mat_path = self._write_canonical(dataset_id)
        mat = self._add_version(
            dataset_id,
            kind=VersionKind.MATERIALIZED,
            storage_path=str(mat_path),
            label="materialized-v1",
        )

        resolved = self.service._resolve_indexable_version(dataset_id, raw.version_id)
        self.assertEqual(resolved.version_id, mat.version_id)
        self.assertEqual(resolved.kind, VersionKind.MATERIALIZED)

        with mock.patch(
            "Data.modules.datasets.service.index_version_file",
            wraps=index_version_file,
        ) as mocked:
            job = self.service.enqueue_index(dataset_id, raw.version_id)
            self.assertEqual(job.version_id, mat.version_id)
            self.assertEqual(job.config["requestedVersionId"], raw.version_id)
            self.assertEqual(job.config["resolvedVersionId"], mat.version_id)

            done = self.service.process_jobs(max_jobs=1)[0]
            self.assertEqual(done.status, DatasetJobStatus.COMPLETED, done.error)
            self.assertEqual(done.result["resolvedVersionId"], mat.version_id)
            self.assertEqual(done.result["requestedVersionId"], raw.version_id)
            mocked.assert_called_once()
            call_path = Path(mocked.call_args.args[1])
            self.assertEqual(call_path, mat_path)
            self.assertTrue(call_path.is_file())
            self.assertEqual(mocked.call_args.kwargs["version_id"], mat.version_id)

        indexes = self.store.list_indexes(dataset_id)
        self.assertEqual(indexes[0].version_id, mat.version_id)
        self.assertEqual(indexes[0].provenance.get("requestedVersionId"), raw.version_id)
        self.assertEqual(indexes[0].provenance.get("resolvedVersionId"), mat.version_id)

    def test_raw_without_materialized_raises_no_indexable_version(self) -> None:
        dataset_id = self._create_dataset("raw-only")
        hf_dir = self.corpus.datasets_raw / dataset_id / "hf"
        hf_dir.mkdir(parents=True, exist_ok=True)
        raw = self._add_version(
            dataset_id,
            kind=VersionKind.RAW,
            storage_path=str(hf_dir),
            label="raw-v1",
        )

        with self.assertRaises(DatasetError) as ctx:
            self.service._resolve_indexable_version(dataset_id, raw.version_id)
        self.assertEqual(ctx.exception.code, "no_indexable_version")
        self.assertEqual(ctx.exception.http_status, 409)

        with self.assertRaises(DatasetError) as ctx2:
            self.service.enqueue_index(dataset_id, raw.version_id)
        self.assertEqual(ctx2.exception.code, "no_indexable_version")
        self.assertNotIn("Permission", str(ctx2.exception))
        self.assertNotIn("Errno 13", str(ctx2.exception))

    def test_version_belongs_to_another_dataset(self) -> None:
        a = self._create_dataset("ds-a")
        b = self._create_dataset("ds-b")
        path = self._write_canonical(b)
        ver_b = self._add_version(
            b,
            kind=VersionKind.MATERIALIZED,
            storage_path=str(path),
            label="materialized-v1",
        )

        with self.assertRaises(DatasetError) as ctx:
            self.service._resolve_indexable_version(a, ver_b.version_id)
        self.assertEqual(ctx.exception.code, "version_mismatch")

        with self.assertRaises(DatasetError) as ctx2:
            self.service.enqueue_index(a, ver_b.version_id)
        self.assertEqual(ctx2.exception.code, "version_mismatch")

    def test_canonical_kind_pointing_at_directory_resolves_or_fails_cleanly(self) -> None:
        dataset_id = self._create_dataset("mat-dir")
        bad_dir = self.corpus.datasets_materialized / dataset_id / "not-a-file"
        bad_dir.mkdir(parents=True, exist_ok=True)
        bad_mat = self._add_version(
            dataset_id,
            kind=VersionKind.MATERIALIZED,
            storage_path=str(bad_dir),
            label="materialized-bad",
        )

        # No sibling → clean domain error, never PermissionError / JSONL open.
        with self.assertRaises(DatasetError) as ctx:
            self.service._resolve_indexable_version(dataset_id, bad_mat.version_id)
        self.assertEqual(ctx.exception.code, "no_indexable_version")
        self.assertNotIsInstance(ctx.exception, PermissionError)

        # Sibling present → resolve to the valid file-backed version.
        good_path = self._write_canonical(dataset_id)
        good = self._add_version(
            dataset_id,
            kind=VersionKind.TRANSFORMED,
            storage_path=str(good_path),
            label="transformed-v1",
        )
        resolved = self.service._resolve_indexable_version(dataset_id, bad_mat.version_id)
        self.assertEqual(resolved.version_id, good.version_id)

        with mock.patch(
            "Data.modules.datasets.service.index_version_file",
            wraps=index_version_file,
        ) as mocked:
            job = self.service.enqueue_index(dataset_id, bad_mat.version_id)
            done = self.service.process_jobs(max_jobs=1)[0]
            self.assertEqual(done.status, DatasetJobStatus.COMPLETED, done.error)
            self.assertEqual(Path(mocked.call_args.args[1]), good_path)

    def test_missing_storage_path(self) -> None:
        dataset_id = self._create_dataset("no-path")
        ver = self._add_version(
            dataset_id,
            kind=VersionKind.MATERIALIZED,
            storage_path=None,
            label="materialized-empty",
            content_hash=None,
        )
        with self.assertRaises(DatasetError) as ctx:
            self.service._resolve_indexable_version(dataset_id, ver.version_id)
        self.assertIn(ctx.exception.code, {"no_storage", "no_indexable_version"})

    def test_nonexistent_file(self) -> None:
        dataset_id = self._create_dataset("missing-file")
        missing = self.corpus.datasets_materialized / dataset_id / "gone.jsonl"
        missing.parent.mkdir(parents=True, exist_ok=True)
        ver = self._add_version(
            dataset_id,
            kind=VersionKind.MATERIALIZED,
            storage_path=str(missing),
            label="materialized-missing",
            content_hash="abc",
        )
        with self.assertRaises(DatasetError) as ctx:
            self.service._resolve_indexable_version(dataset_id, ver.version_id)
        self.assertEqual(ctx.exception.code, "storage_missing")
        self.assertNotIsInstance(ctx.exception.__cause__, FileNotFoundError)

        with self.assertRaises(DatasetError) as ctx2:
            self.service.enqueue_index(dataset_id, ver.version_id)
        self.assertEqual(ctx2.exception.code, "storage_missing")

    def test_index_version_file_rejects_directory(self) -> None:
        dataset_id = self._create_dataset("defensive")
        hf_dir = self.corpus.datasets_raw / dataset_id / "hf"
        hf_dir.mkdir(parents=True, exist_ok=True)
        with self.assertRaises(DatasetError) as ctx:
            index_version_file(
                self.knowledge,
                hf_dir,
                dataset_id=dataset_id,
                version_id="v-raw",
            )
        self.assertEqual(ctx.exception.code, "storage_not_file")

    def test_prefer_materialized_over_transformed_when_resolving_raw(self) -> None:
        dataset_id = self._create_dataset("prefer-mat")
        hf_dir = self.corpus.datasets_raw / dataset_id / "hf"
        hf_dir.mkdir(parents=True, exist_ok=True)
        raw = self._add_version(
            dataset_id,
            kind=VersionKind.RAW,
            storage_path=str(hf_dir),
            label="raw-v1",
        )
        xform_path = self.corpus.datasets_processed / dataset_id / "xform.jsonl"
        xform_path.parent.mkdir(parents=True, exist_ok=True)
        xform_path.write_text('{"id":"t","text":"transformed"}\n', encoding="utf-8")
        self._add_version(
            dataset_id,
            kind=VersionKind.TRANSFORMED,
            storage_path=str(xform_path),
            label="transformed-v1",
        )
        mat_path = self._write_canonical(dataset_id)
        mat = self._add_version(
            dataset_id,
            kind=VersionKind.MATERIALIZED,
            storage_path=str(mat_path),
            label="materialized-v1",
        )
        resolved = self.service._resolve_indexable_version(dataset_id, raw.version_id)
        self.assertEqual(resolved.version_id, mat.version_id)


if __name__ == "__main__":
    unittest.main()
