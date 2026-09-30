"""Wave 1 — catalog query / overview aggregates for Dataset Management."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Data.backend.routes.datasets import build_datasets_router
from Data.modules.common.corpus import CorpusLayout
from Data.modules.datasets.quality_signals import quality_from_validation
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import (
    DatasetJobStatus,
    DatasetJobType,
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


class DatasetCatalogQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "leviathan.db"
        self.corpus = _layout(self.root / "corpus")
        self.knowledge = KnowledgeStore(self.db, data_root=self.root / "kdata")
        self.knowledge.initialize()
        self.store = DatasetStore(self.db)
        self.store.initialize()
        self.service = DatasetService(
            self.store,
            corpus=self.corpus,
            knowledge=self.knowledge,
            allowed_import_roots=[self.corpus.root],
        )
        app = FastAPI()
        app.include_router(build_datasets_router(self.service))
        self.client = TestClient(app)

        # Seed >100 datasets for pagination truth.
        for i in range(120):
            status = DatasetStatus.READY if i % 7 else DatasetStatus.FAILED
            source = SourceType.HUGGINGFACE if i % 3 == 0 else SourceType.LOCAL
            meta = {
                "displayName": f"Display {i}",
                "primaryCategory": "kennis" if i % 2 == 0 else "code",
                "semanticProfile": {
                    "displayName": f"Display {i}",
                    "primaryCategory": "kennis" if i % 2 == 0 else "code",
                    "tags": ["nl", "wiki"] if i % 2 == 0 else ["code", "py"],
                    "summary": f"Summary for dataset {i}",
                },
                "tags": ["nl", "wiki"] if i % 2 == 0 else ["code", "py"],
            }
            ds = self.store.create_dataset(
                name=f"ds_{i:04d}",
                source_type=source,
                description=f"desc {i}",
                metadata=meta,
                status=status,
            )
            # Partial measurement: only first 90 have row/byte counts.
            if i < 90:
                self.store.update_dataset(
                    ds.dataset_id,
                    row_count=1000 + i,
                    byte_size=10_000 + i * 100,
                )
            ver = self.store.create_version(
                dataset_id=ds.dataset_id,
                version_label=f"v0.{i}.0",
                kind=VersionKind.MATERIALIZED,
                status=VersionStatus.READY,
                metadata={},
            )
            if i % 5 == 0:
                self.store.update_version(
                    ver.version_id,
                    validation={
                        "valid": i % 10 != 0,
                        "rowCount": 1000 + i,
                        "errorCount": 2 if i % 10 == 0 else 0,
                        "warningCount": 1 if i % 10 == 0 else 0,
                        "emptyContentCount": 0,
                    },
                    split={"train": 0.8, "validation": 0.1, "test": 0.1},
                )
            if i == 0:
                self.store.create_version(
                    dataset_id=ds.dataset_id,
                    version_label="export-1",
                    kind=VersionKind.EXPORT,
                    status=VersionStatus.READY,
                )

        # Active import jobs
        self.store.create_job(
            job_type=DatasetJobType.IMPORT_HF,
            status=DatasetJobStatus.RUNNING,
            dataset_id=None,
        )
        self.store.create_job(
            job_type=DatasetJobType.IMPORT_LOCAL,
            status=DatasetJobStatus.QUEUED,
            dataset_id=None,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_list_total_independent_of_page(self) -> None:
        r1 = self.client.get("/api/datasets", params={"limit": 25, "offset": 0})
        self.assertEqual(r1.status_code, 200)
        body = r1.json()
        self.assertEqual(body["total"], 120)
        self.assertEqual(len(body["datasets"]), 25)
        self.assertTrue(body["hasMore"])
        self.assertEqual(body["nextOffset"], 25)

        r2 = self.client.get("/api/datasets", params={"limit": 25, "offset": 25})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["total"], 120)
        self.assertEqual(len(r2.json()["datasets"]), 25)
        # Different page, same total
        ids1 = {d["datasetId"] for d in body["datasets"]}
        ids2 = {d["datasetId"] for d in r2.json()["datasets"]}
        self.assertTrue(ids1.isdisjoint(ids2))

    def test_search_server_side(self) -> None:
        r = self.client.get("/api/datasets", params={"q": "Display 42", "limit": 50})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertGreaterEqual(body["total"], 1)
        self.assertTrue(any("42" in (d.get("displayName") or d["name"]) for d in body["datasets"]))

    def test_combined_filters(self) -> None:
        r = self.client.get(
            "/api/datasets",
            params={
                "source": "huggingface",
                "category": "kennis",
                "status": "ready",
                "limit": 50,
            },
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertGreater(body["total"], 0)
        for d in body["datasets"]:
            self.assertEqual(d["sourceType"], "huggingface")
            self.assertEqual(d["status"], "ready")

    def test_stable_sort(self) -> None:
        r = self.client.get(
            "/api/datasets",
            params={"sort": "name_asc", "limit": 10},
        )
        names = [d["name"] for d in r.json()["datasets"]]
        self.assertEqual(names, sorted(names, key=str.lower))

    def test_overview_partial_samples_and_real_imports(self) -> None:
        r = self.client.get("/api/datasets/overview")
        self.assertEqual(r.status_code, 200)
        ov = r.json()["overview"]
        self.assertEqual(ov["totalDatasets"], 120)
        self.assertEqual(ov["samplesMeasuredDatasets"], 90)
        self.assertEqual(ov["samplesUnmeasuredDatasets"], 30)
        # Partial: sum of measured only — not treating null as 0 in the "complete" sense
        self.assertEqual(ov["measurementStatus"] in {"partial", "complete", "unmeasured_capacity"}, True)
        self.assertEqual(ov["activeImports"], 2)
        self.assertEqual(ov["runningImports"], 1)
        self.assertEqual(ov["queuedImports"], 1)
        self.assertGreaterEqual(ov["validationIssues"], 1)
        self.assertGreaterEqual(ov["criticalValidationIssues"], 1)
        self.assertIn("catalogStatus", ov)
        self.assertTrue(ov["catalogStatus"]["truth"]["notRemoteSyncOnline"])
        self.assertTrue(isinstance(ov["tagCounts"], list))
        self.assertTrue(any(t["tag"] == "nl" for t in ov["tagCounts"]))
        self.assertTrue(isinstance(ov["storageBreakdown"], list))
        self.assertTrue(isinstance(ov["services"], list))
        self.assertEqual(len(ov["services"]), 6)
        # No hardcoded green — each service has measured/state
        for svc in ov["services"]:
            self.assertIn(svc["state"], {
                "running", "ready", "busy", "degraded", "offline", "unavailable", "unmeasured",
            })
            self.assertIn("measured", svc)

    def test_quality_unknown_without_validation(self) -> None:
        q = quality_from_validation(None)
        self.assertFalse(q["measured"])
        self.assertIsNone(q["score"])
        self.assertEqual(q["label"], "Niet gemeten")

        q2 = quality_from_validation({"errorCount": 2, "warningCount": 1, "emptyContentCount": 0})
        self.assertTrue(q2["measured"])
        self.assertEqual(q2["score"], 100 - 16 - 2)
        self.assertEqual(q2["constituents"]["errorCount"], 2)

    def test_quality_on_list_rows(self) -> None:
        r = self.client.get("/api/datasets", params={"q": "ds_0000", "limit": 5})
        body = r.json()
        self.assertGreaterEqual(len(body["datasets"]), 1)
        row = body["datasets"][0]
        self.assertIn("quality", row)
        # ds_0000 has validation with errors
        self.assertTrue(row["quality"]["measured"])

    def test_legacy_limit_only_still_works(self) -> None:
        r = self.client.get("/api/datasets?limit=100")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("datasets", body)
        self.assertEqual(len(body["datasets"]), 100)
        self.assertEqual(body["total"], 120)


if __name__ == "__main__":
    unittest.main()
