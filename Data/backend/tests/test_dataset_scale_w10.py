"""Wave 10 — dataset scale / performance hardening tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.common.corpus import CorpusLayout
from Data.modules.datasets.contamination import scan_contamination
from Data.modules.datasets.indexing import index_records
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.sidecar import SIDECAR_FILENAME, find_sidecars_under_roots, write_sidecar
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import CanonicalRecord, SourceType
from Data.modules.knowledge import KnowledgeStore
from Data.modules.knowledge.embeddings import LocalHashEmbeddingProvider


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


class P1010BoundedDocumentIdsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "k.db"
        self.knowledge = KnowledgeStore(
            self.db,
            data_root=self.root / "data",
            embedding_provider=LocalHashEmbeddingProvider(dimensions=16),
        )
        self.knowledge.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_document_ids_sample_is_bounded(self) -> None:
        records = [
            CanonicalRecord(id=f"r{i}", text=f"row {i} unique content about topic {i}")
            for i in range(40)
        ]
        out = index_records(
            self.knowledge,
            records,
            dataset_id="ds",
            version_id="v1",
            extract_relations=False,
            write_batch_size=8,
        )
        self.assertEqual(out["documentCount"], 40)
        self.assertLessEqual(len(out["documentIdsSample"]), 20)
        self.assertTrue(out["truth"]["document_ids_are_bounded_sample"])


class P1011IndexingBatchLookupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "k.db"
        self.knowledge = KnowledgeStore(
            self.db,
            data_root=self.root / "data",
            embedding_provider=LocalHashEmbeddingProvider(dimensions=16),
        )
        self.knowledge.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_batch_helpers_and_skip_path_avoid_list_chunks(self) -> None:
        records = [
            CanonicalRecord(id="a", text="alpha content for batch"),
            CanonicalRecord(id="b", text="bravo content for batch"),
            CanonicalRecord(id="c", text="charlie content for batch"),
        ]
        first = index_records(
            self.knowledge,
            records,
            dataset_id="ds",
            version_id="v1",
            extract_relations=False,
            write_batch_size=2,
        )
        self.assertEqual(first["indexedCount"], 3)

        ids = [f"dataset:ds:v1:{r.id}" for r in records]
        batch = self.knowledge.get_documents_batch(ids)
        self.assertEqual(len(batch), 3)
        counts = self.knowledge.count_chunks_for_documents(ids)
        self.assertEqual(set(counts), set(ids))
        self.assertTrue(all(v >= 1 for v in counts.values()))

        list_chunks_calls = {"n": 0}
        real_list = self.knowledge.list_chunks

        def wrapped(document_id: str):
            list_chunks_calls["n"] += 1
            return real_list(document_id)

        with mock.patch.object(self.knowledge, "list_chunks", side_effect=wrapped):
            second = index_records(
                self.knowledge,
                records,
                dataset_id="ds",
                version_id="v1",
                extract_relations=False,
                write_batch_size=2,
            )
        self.assertEqual(second["skippedUnchanged"], 3)
        self.assertEqual(list_chunks_calls["n"], 0)
        self.assertTrue(second["truth"]["chunk_counts_avoid_list_chunks"])
        self.assertTrue(second["truth"]["document_lookups_are_batched"])


class P2001SidecarLazyIterationTests(unittest.TestCase):
    def test_stops_at_max_files_without_materializing_all(self) -> None:
        root = Path(tempfile.mkdtemp())
        for i in range(12):
            d = root / f"ds-{i}"
            d.mkdir()
            write_sidecar(
                d,
                {
                    "schemaVersion": 2,
                    "datasetId": f"id-{i}",
                    "name": f"name-{i}",
                },
            )

        # Monkeypatch rglob to ensure callers do not list() the whole iterator.
        real_rglob = Path.rglob
        listed = {"full_list": 0}

        def tracked_rglob(self, pattern):  # noqa: ANN001
            it = real_rglob(self, pattern)
            # If someone does list(it), that consumes everything — detect via wrapper.
            class _Track:
                def __init__(self, inner):
                    self._inner = inner
                    self._seen = 0

                def __iter__(self):
                    return self

                def __next__(self):
                    item = next(self._inner)
                    self._seen += 1
                    return item

            return _Track(it)

        with mock.patch.object(Path, "rglob", tracked_rglob):
            found = find_sidecars_under_roots([("raw", root)], max_files=5)
        self.assertEqual(len(found), 5)
        self.assertTrue(all(Path(item["path"]).name == SIDECAR_FILENAME for item in found))


class P2002SemanticBackfillPaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data_root = self.root / "ModelData"
        self.data_root.mkdir()
        self.db = self.root / "leviathan.db"
        self.corpus = _layout(self.data_root / "leviathan")
        self.knowledge = KnowledgeStore(
            self.db,
            data_root=self.data_root,
            embedding_provider=LocalHashEmbeddingProvider(dimensions=16),
        )
        self.knowledge.initialize()
        self.store = DatasetStore(self.db)
        self.store.initialize()
        self.service = DatasetService(
            self.store,
            corpus=self.corpus,
            knowledge=self.knowledge,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_uses_query_datasets_pagination_not_limit_10000(self) -> None:
        for i in range(3):
            self.store.create_dataset(
                name=f"ds-{i}",
                source_type=SourceType.LOCAL,
                metadata={},
            )

        calls: list[dict] = []
        real = self.store.query_datasets

        def tracked(**kwargs):
            calls.append(dict(kwargs))
            return real(**kwargs)

        with mock.patch.object(self.store, "query_datasets", side_effect=tracked):
            with mock.patch.object(self.store, "list_datasets") as list_mock:
                # Force pick_usable_version to skip (no versions) so we don't enqueue.
                out = self.service.enqueue_missing_semantic_profiles(limit=10)
                list_mock.assert_not_called()
        self.assertTrue(calls)
        self.assertTrue(all(c.get("limit", 0) <= 100 for c in calls))
        self.assertNotIn(10_000, [c.get("limit") for c in calls])
        self.assertTrue(out["truth"]["catalogPaginated"])
        self.assertGreaterEqual(out["scanned"], 3)


class P2003ContaminationScaleTests(unittest.TestCase):
    def test_max_retained_hits_and_total_count(self) -> None:
        sealed = [{"case_id": "c1", "prompt": "overlap phrase one two three four five six"}]
        records = [
            CanonicalRecord(id=f"r{i}", text="overlap phrase one two three four five six")
            for i in range(30)
        ]
        progress_events: list[dict] = []
        report = scan_contamination(
            records,
            sealed,
            max_retained_hits=5,
            progress_cb=lambda info: progress_events.append(dict(info)),
            progress_every=10,
        )
        self.assertEqual(report.hit_count, 30)
        self.assertEqual(len(report.hits), 5)
        self.assertTrue(report.hits_truncated)
        self.assertEqual(report.evidence_class, "EXACT")
        self.assertFalse(report.passed)
        pub = report.public_dict()
        self.assertEqual(pub["hit_count"], 30)
        self.assertEqual(pub["hitsRetained"], 5)
        self.assertTrue(pub["truth"]["truncation_does_not_downgrade_measured_quality"])
        self.assertTrue(progress_events)

    def test_cancellation_does_not_pass_as_clean(self) -> None:
        sealed = [{"case_id": "c1", "prompt": "unique sealed prompt text here"}]
        records = [
            CanonicalRecord(id=f"r{i}", text=f"clean row {i} with no overlap tokens")
            for i in range(20)
        ]
        seen = {"n": 0}

        def cancel() -> bool:
            seen["n"] += 1
            return seen["n"] > 3

        report = scan_contamination(
            records,
            sealed,
            cancel_check=cancel,
            progress_every=1,
        )
        self.assertTrue(report.cancelled)
        self.assertFalse(report.passed)
        self.assertEqual(report.evidence_class, "UNMEASURED")
        self.assertLess(report.scanned_records, 20)


if __name__ == "__main__":
    unittest.main()
