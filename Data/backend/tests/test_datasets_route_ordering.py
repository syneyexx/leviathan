"""Regression tests: static dataset routes must not be shadowed by {dataset_id}."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Data.backend.routes.datasets import DATASETS_STATIC_SEGMENTS, build_datasets_router
from Data.modules.common.corpus import CorpusLayout
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import DatasetJobStatus, DatasetJobType
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


class DatasetRouteOrderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "leviathan.db"
        self.corpus = _layout(self.root / "corpus")
        self.import_root = self.root / "imports"
        self.import_root.mkdir()
        self.knowledge = KnowledgeStore(self.db, data_root=self.root / "kdata")
        self.knowledge.initialize()
        self.store = DatasetStore(self.db)
        self.store.initialize()
        self.service = DatasetService(
            self.store,
            corpus=self.corpus,
            knowledge=self.knowledge,
            allowed_import_roots=[self.import_root, self.corpus.root],
        )
        app = FastAPI()
        app.include_router(build_datasets_router(self.service))
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_static_segments_include_jobs_and_mixtures(self) -> None:
        self.assertIn("jobs", DATASETS_STATIC_SEGMENTS)
        self.assertIn("mixtures", DATASETS_STATIC_SEGMENTS)
        self.assertIn("offline", DATASETS_STATIC_SEGMENTS)
        self.assertIn("library", DATASETS_STATIC_SEGMENTS)
        self.assertIn("learned", DATASETS_STATIC_SEGMENTS)
        self.assertIn("versions", DATASETS_STATIC_SEGMENTS)

    def test_list_jobs_not_shadowed_by_dataset_id(self) -> None:
        response = self.client.get("/api/datasets/jobs")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn("jobs", body)
        self.assertIsInstance(body["jobs"], list)
        # Must NOT look like get_dataset payload
        self.assertNotIn("dataset", body)

    def test_list_jobs_with_limit_query(self) -> None:
        response = self.client.get("/api/datasets/jobs?limit=50")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("jobs", response.json())

    def test_list_mixtures_not_shadowed(self) -> None:
        response = self.client.get("/api/datasets/mixtures")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn("mixtures", body)
        self.assertNotIn("dataset", body)

    def test_offline_discover_not_shadowed(self) -> None:
        response = self.client.get("/api/datasets/offline/discover")
        self.assertEqual(response.status_code, 200, response.text)

    def test_get_real_dataset_still_works(self) -> None:
        ds = self.service.create_dataset(name="route-real")
        response = self.client.get(f"/api/datasets/{ds.dataset_id}")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["dataset"]["datasetId"], ds.dataset_id)
        self.assertIn("versions", body)

    def test_nonexistent_dataset_returns_404(self) -> None:
        response = self.client.get("/api/datasets/does-not-exist-xyz")
        self.assertEqual(response.status_code, 404)

    def test_job_lifecycle_list_get_cancel(self) -> None:
        path = self.import_root / "queued.jsonl"
        path.write_text('{"id":"1","text":"hello"}\n', encoding="utf-8")
        job = self.service.enqueue_import_local(path=str(path), name="queued", materialize=False)
        listed = self.client.get("/api/datasets/jobs?limit=50")
        self.assertEqual(listed.status_code, 200)
        ids = [j["jobId"] for j in listed.json()["jobs"]]
        self.assertIn(job.job_id, ids)

        got = self.client.get(f"/api/datasets/jobs/{job.job_id}")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.json()["job"]["jobId"], job.job_id)
        self.assertEqual(got.json()["job"]["status"], DatasetJobStatus.QUEUED.value)

        cancelled = self.client.post(f"/api/datasets/jobs/{job.job_id}/cancel")
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["job"]["status"], DatasetJobStatus.CANCELLED.value)

    def test_public_job_includes_download_summary_for_hf_checkpoint(self) -> None:
        job = self.store.create_job(
            job_type=DatasetJobType.IMPORT_HF,
            dataset_id=None,
            config={"repositoryId": "org/ds", "filename": "train.parquet", "revision": "main"},
        )
        self.store.update_job(
            job.job_id,
            status=DatasetJobStatus.RUNNING,
            phase="downloading",
            checkpoint={
                "repositoryId": "org/ds",
                "revision": "main",
                "filename": "train.parquet",
                "bytesDownloaded": 1024,
                "totalBytes": 4096,
                "attempts": 2,
                "lastStatus": 429,
                "rateLimitEvents": 1,
            },
        )
        refreshed = self.service.get_job(job.job_id)
        public = self.service.public_job(refreshed)
        self.assertEqual(public["phase"], "downloading")
        self.assertIsNotNone(public.get("download"))
        self.assertEqual(public["download"]["bytesDownloaded"], 1024)
        self.assertEqual(public["download"]["bytesTotal"], 4096)
        self.assertEqual(public["download"]["lastHttpStatus"], 429)
        self.assertEqual(public["download"]["rateLimitEvents"], 1)
        # Secrets must not appear
        self.assertNotIn("token", str(public["config"]).lower().replace("[redacted]", ""))


if __name__ == "__main__":
    unittest.main()
