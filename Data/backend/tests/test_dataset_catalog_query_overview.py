"""Wave 1 — server-side catalog query, pagination, and overview aggregates."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.common.corpus import CorpusLayout
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import (
    DatasetStatus,
    SourceType,
    VersionKind,
    VersionStatus,
)


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


class CatalogQueryOverviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "knowledge.db"
        self.store = DatasetStore(self.db)
        self.store.initialize()
        self.service = DatasetService(
            store=self.store,
            corpus=_layout(self.root / "corpus"),
            knowledge=None,
            job_runtime=None,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _seed(self, n: int = 120) -> None:
        for i in range(n):
            meta = {}
            if i % 3 == 0:
                meta = {
                    "displayName": f"Wiki Dataset {i}",
                    "primaryCategory": "GENERAL",
                    "semanticProfile": {
                        "displayName": f"Wiki Dataset {i}",
                        "primaryCategory": "GENERAL",
                        "tags": ["nl", "wiki"],
                        "summary": "Nederlandse wiki samples",
                    },
                }
            elif i % 3 == 1:
                meta = {
                    "primaryCategory": "TECHNOLOGY_SOFTWARE",
                    "semanticProfile": {
                        "primaryCategory": "TECHNOLOGY_SOFTWARE",
                        "tags": ["code", "instruct"],
                    },
                }
            ds = self.store.create_dataset(
                name=f"ds_{i:04d}",
                source_type=SourceType.HUGGINGFACE if i % 2 == 0 else SourceType.LOCAL,
                description=f"desc {i}",
                metadata=meta,
                status=DatasetStatus.READY if i % 5 else DatasetStatus.CREATED,
            )
            # Partial measurement: only some have row/byte counts
            if i < 100:
                self.store.update_dataset(
                    ds.dataset_id,
                    row_count=1000 + i,
                    byte_size=1_000_000 * (i + 1),
                )
            if i % 7 == 0:
                ver = self.store.create_version(
                    dataset_id=ds.dataset_id,
                    version_label="v1",
                    kind=VersionKind.MATERIALIZED,
                    status=VersionStatus.READY,
                )
                self.store.update_version(
                    ver.version_id,
                    validation={"errorCount": 2 if i % 14 == 0 else 0, "warningCount": 1},
                    byte_size=500_000,
                    split={"train": 0.8, "validation": 0.1, "test": 0.1},
                )

    def test_query_past_100_with_total(self) -> None:
        self._seed(120)
        page1 = self.store.query_datasets(limit=50, offset=0)
        page2 = self.store.query_datasets(limit=50, offset=50)
        page3 = self.store.query_datasets(limit=50, offset=100)
        self.assertEqual(page1["total"], 120)
        self.assertEqual(len(page1["datasets"]), 50)
        self.assertEqual(len(page2["datasets"]), 50)
        self.assertEqual(len(page3["datasets"]), 20)
        self.assertTrue(page1["hasMore"])
        self.assertFalse(page3["hasMore"])
        ids = {d.dataset_id for d in page1["datasets"] + page2["datasets"] + page3["datasets"]}
        self.assertEqual(len(ids), 120)

    def test_search_server_side(self) -> None:
        self._seed(30)
        page = self.store.query_datasets(q="Wiki Dataset", limit=50)
        self.assertGreater(page["total"], 0)
        for ds in page["datasets"]:
            blob = str(ds.metadata)
            self.assertTrue("Wiki" in blob or "wiki" in blob.lower() or "Wiki" in ds.name)

    def test_combined_filters(self) -> None:
        self._seed(40)
        page = self.store.query_datasets(
            source_type="huggingface",
            category="GENERAL",
            tag="nl",
            limit=100,
        )
        self.assertGreaterEqual(page["total"], 1)
        for ds in page["datasets"]:
            self.assertEqual(ds.source_type, SourceType.HUGGINGFACE)

    def test_stable_sort_name(self) -> None:
        self._seed(10)
        page = self.store.query_datasets(sort="name", limit=10)
        names = [d.name for d in page["datasets"]]
        self.assertEqual(names, sorted(names, key=str.lower))

    def test_overview_partial_samples_and_real_total(self) -> None:
        self._seed(120)
        overview = self.service.overview()
        self.assertEqual(overview["totalDatasets"], 120)
        self.assertEqual(overview["samplesMeasuredDatasets"], 100)
        self.assertEqual(overview["samplesUnmeasuredDatasets"], 20)
        self.assertEqual(overview["samplesMeasurementStatus"], "PARTIAL")
        # Sum of measured row counts only (not treating null as 0)
        expected = sum(1000 + i for i in range(100))
        self.assertEqual(overview["totalSamples"], expected)
        self.assertIsInstance(overview["storage"]["capacityBytes"], int)
        self.assertGreater(overview["storage"]["capacityBytes"], 0)
        self.assertEqual(overview["storage"]["usedBytes"], overview["totalKnownBytes"])
        self.assertIn(overview["catalogStatus"]["state"], {"HEALTHY", "UNMEASURED"})
        self.assertTrue(overview["truth"]["kpis_are_not_page_length"])
        self.assertTrue(overview["truth"]["null_row_count_is_not_zero_samples"])

    def test_quality_unknown_without_validation(self) -> None:
        ds = self.store.create_dataset(
            name="no_validation",
            source_type=SourceType.LOCAL,
            status=DatasetStatus.READY,
        )
        quality = self.service.quality_projection_for_dataset(ds.dataset_id)
        self.assertFalse(quality["measured"])
        self.assertIsNone(quality["score"])
        self.assertEqual(quality["label"], "Niet gemeten")

    def test_quality_measured_from_validation(self) -> None:
        ds = self.store.create_dataset(
            name="validated",
            source_type=SourceType.LOCAL,
            status=DatasetStatus.READY,
        )
        ver = self.store.create_version(
            dataset_id=ds.dataset_id,
            version_label="v1",
            kind=VersionKind.MATERIALIZED,
            status=VersionStatus.READY,
        )
        self.store.update_version(
            ver.version_id,
            validation={"errorCount": 0, "warningCount": 0},
        )
        quality = self.service.quality_projection_for_dataset(ds.dataset_id)
        self.assertTrue(quality["measured"])
        self.assertEqual(quality["score"], 100)
        self.assertEqual(quality["bars"], 5)

    def test_validation_aggregates_not_failed_jobs(self) -> None:
        self._seed(20)
        overview = self.service.overview()
        self.assertGreaterEqual(overview["validationIssues"], 0)
        self.assertGreaterEqual(overview["criticalValidationIssues"], 0)
        self.assertTrue(overview["truth"]["failed_jobs_are_not_validation_issues"])

    def test_list_datasets_backward_compat(self) -> None:
        self._seed(5)
        items = self.service.list_datasets(limit=3)
        self.assertEqual(len(items), 3)


if __name__ == "__main__":
    unittest.main()
