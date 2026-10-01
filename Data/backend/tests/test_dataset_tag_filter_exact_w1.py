"""Wave 1 — exact JSON-array tag membership (no summary false positives)."""

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
from Data.modules.datasets.types import DatasetStatus, SourceType
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


class ExactTagFilterTests(unittest.TestCase):
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

        self.store.create_dataset(
            name="tagged_nl",
            source_type=SourceType.LOCAL,
            status=DatasetStatus.READY,
            metadata={
                "displayName": "NL corpus",
                "semanticProfile": {
                    "tags": ["nl", "wiki"],
                    "summary": "This mentions code in the summary only",
                },
                "tags": ["nl", "wiki"],
            },
        )
        self.store.create_dataset(
            name="tagged_code",
            source_type=SourceType.LOCAL,
            status=DatasetStatus.READY,
            metadata={
                "displayName": "Code pack",
                "semanticProfile": {"tags": ["Code", "py"], "summary": "python sources"},
                "semanticTags": ["Code", "py"],
            },
        )
        self.store.create_dataset(
            name="summary_only_code_word",
            source_type=SourceType.LOCAL,
            status=DatasetStatus.READY,
            metadata={
                "displayName": "About code practices",
                "semanticProfile": {
                    "tags": ["docs"],
                    "summary": "Mentions code repeatedly but tag is docs",
                },
                "tags": ["docs"],
            },
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_tag_in_summary_does_not_match(self) -> None:
        r = self.client.get("/api/datasets", params={"tags": "code", "limit": 50})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        names = {d["name"] for d in body["datasets"]}
        self.assertIn("tagged_code", names)
        self.assertNotIn("summary_only_code_word", names)
        self.assertNotIn("tagged_nl", names)

    def test_exact_array_membership(self) -> None:
        r = self.client.get("/api/datasets", params={"tags": "wiki", "limit": 50})
        self.assertEqual(r.status_code, 200)
        names = {d["name"] for d in r.json()["datasets"]}
        self.assertEqual(names, {"tagged_nl"})

    def test_case_insensitive(self) -> None:
        r = self.client.get("/api/datasets", params={"tags": "CODE", "limit": 50})
        self.assertEqual(r.status_code, 200)
        names = {d["name"] for d in r.json()["datasets"]}
        self.assertEqual(names, {"tagged_code"})

    def test_and_multi_tag(self) -> None:
        r = self.client.get("/api/datasets", params={"tags": "nl,wiki", "limit": 50})
        self.assertEqual(r.status_code, 200)
        names = {d["name"] for d in r.json()["datasets"]}
        self.assertEqual(names, {"tagged_nl"})

        r2 = self.client.get("/api/datasets", params={"tags": "nl,code", "limit": 50})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["total"], 0)


if __name__ == "__main__":
    unittest.main()
