"""Wave 1 — dataset jobs query filters, totals, process refusal."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Data.backend.routes.datasets import build_datasets_router
from Data.modules.common.corpus import CorpusLayout
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import (
    DatasetJobStatus,
    DatasetJobType,
    DatasetStatus,
    SourceType,
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


class DatasetJobsQueryTests(unittest.TestCase):
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

        self.ds_a = self.store.create_dataset(
            name="job_ds_a",
            source_type=SourceType.LOCAL,
            status=DatasetStatus.READY,
        )
        self.ds_b = self.store.create_dataset(
            name="job_ds_b",
            source_type=SourceType.LOCAL,
            status=DatasetStatus.READY,
        )
        self.job_old = self.store.create_job(
            job_type=DatasetJobType.INDEX,
            status=DatasetJobStatus.COMPLETED,
            dataset_id=self.ds_a.dataset_id,
        )
        time.sleep(1.1)
        self.job_new = self.store.create_job(
            job_type=DatasetJobType.VALIDATE,
            status=DatasetJobStatus.QUEUED,
            dataset_id=self.ds_a.dataset_id,
        )
        self.job_other = self.store.create_job(
            job_type=DatasetJobType.INDEX,
            status=DatasetJobStatus.RUNNING,
            dataset_id=self.ds_b.dataset_id,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_jobs_dataset_scope(self) -> None:
        r = self.client.get(
            "/api/datasets/jobs",
            params={"datasetId": self.ds_a.dataset_id, "limit": 50},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(len(body["jobs"]), 2)
        for j in body["jobs"]:
            self.assertEqual(j["datasetId"], self.ds_a.dataset_id)

    def test_jobs_status_and_type(self) -> None:
        r = self.client.get(
            "/api/datasets/jobs",
            params={"jobType": "index", "status": "running", "limit": 50},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["jobs"][0]["jobId"], self.job_other.job_id)

    def test_jobs_created_time_range(self) -> None:
        mid = self.job_new.created_at
        r = self.client.get(
            "/api/datasets/jobs",
            params={"createdAfter": mid, "limit": 50},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        ids = {j["jobId"] for j in body["jobs"]}
        self.assertIn(self.job_new.job_id, ids)
        self.assertIn(self.job_other.job_id, ids)
        # Old job created before mid should be excluded when strict >
        # created_after uses >= so equal mid includes job_new.
        self.assertNotIn(self.job_old.job_id, ids)

        r2 = self.client.get(
            "/api/datasets/jobs",
            params={"createdBefore": self.job_old.created_at, "limit": 50},
        )
        self.assertEqual(r2.status_code, 200)
        ids2 = {j["jobId"] for j in r2.json()["jobs"]}
        self.assertIn(self.job_old.job_id, ids2)
        self.assertNotIn(self.job_other.job_id, ids2)

    def test_jobs_limit_offset_total(self) -> None:
        r = self.client.get("/api/datasets/jobs", params={"limit": 1, "offset": 0})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["total"], 3)
        self.assertEqual(len(body["jobs"]), 1)
        self.assertTrue(body["hasMore"])

        r_neg = self.client.get("/api/datasets/jobs", params={"limit": -1})
        self.assertEqual(r_neg.status_code, 400)

    def test_process_jobs_production_refusal(self) -> None:
        # Kernel-backed service refuses in-process drain.
        self.service.bind_job_runtime(SimpleNamespace(store=SimpleNamespace()))
        r = self.client.post("/api/datasets/jobs/process", params={"maxJobs": 5})
        self.assertEqual(r.status_code, 503)
        detail = r.json()["detail"]
        self.assertEqual(detail["code"], "DATASET_EXECUTION_UNAVAILABLE")

    def test_learning_fleet_route_not_shadowed(self) -> None:
        r = self.client.get("/api/datasets/learning/fleet", params={"limit": 10})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("datasets", body)
        self.assertIn("activeJobs", body)
        self.assertIn("truth", body)


if __name__ == "__main__":
    unittest.main()
