"""Targeted tests for datasets inventory scope/indexed filters + bulk enqueue."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Data.backend.routes.datasets import build_datasets_router
from Data.modules.common.corpus import CorpusLayout
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import (
    DatasetStatus,
    IndexStatus,
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


class DatasetsBulkAndIndexedTests(unittest.TestCase):
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

        local = self.store.create_dataset(
            name="local-a",
            source_type=SourceType.LOCAL,
            status=DatasetStatus.READY,
            description="local",
        )
        hf = self.store.create_dataset(
            name="hf-b",
            source_type=SourceType.HUGGINGFACE,
            status=DatasetStatus.READY,
            description="hf",
        )
        self.local_id = local.dataset_id
        self.hf_id = hf.dataset_id
        ver = self.store.create_version(
            dataset_id=self.local_id,
            version_label="v1",
            kind=VersionKind.MATERIALIZED,
            status=VersionStatus.READY,
        )
        self.store.create_index(
            dataset_id=self.local_id,
            version_id=ver.version_id,
            status=IndexStatus.READY,
            storage_path=str(self.root / "idx"),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_overview_includes_indexed_and_local_counts(self) -> None:
        r = self.client.get("/api/datasets/overview")
        self.assertEqual(r.status_code, 200)
        ov = r.json()["overview"]
        self.assertEqual(ov["totalDatasets"], 2)
        self.assertEqual(ov["localDatasets"], 1)
        self.assertEqual(ov["externalDatasets"], 1)
        self.assertEqual(ov["indexedDatasets"], 1)
        self.assertEqual(ov["notIndexedDatasets"], 1)

    def test_source_scope_and_indexed_filters(self) -> None:
        local = self.client.get("/api/datasets", params={"sourceScope": "local", "limit": 10})
        self.assertEqual(local.status_code, 200)
        self.assertEqual(local.json()["total"], 1)
        self.assertEqual(local.json()["datasets"][0]["datasetId"], self.local_id)

        indexed = self.client.get("/api/datasets", params={"indexed": "true", "limit": 10})
        self.assertEqual(indexed.status_code, 200)
        self.assertEqual(indexed.json()["total"], 1)
        self.assertEqual(indexed.json()["datasets"][0]["datasetId"], self.local_id)

        not_indexed = self.client.get("/api/datasets", params={"indexed": "false", "limit": 10})
        self.assertEqual(not_indexed.status_code, 200)
        self.assertEqual(not_indexed.json()["total"], 1)
        self.assertEqual(not_indexed.json()["datasets"][0]["datasetId"], self.hf_id)

    def test_bulk_materialize_reports_partial_failure(self) -> None:
        r = self.client.post(
            "/api/datasets/bulk/materialize",
            json={"datasetIds": [self.local_id, "missing-id"]},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["requested"], 2)
        self.assertEqual(body["succeeded"] + body["failed"], 2)
        self.assertTrue(body["truth"]["partialFailureReported"])


if __name__ == "__main__":
    unittest.main()
