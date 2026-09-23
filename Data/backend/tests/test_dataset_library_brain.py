"""Dataset library discovery + Kennis leren (Brain ingestion) integration."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Data.backend.routes.datasets import build_datasets_router
from Data.modules.common.corpus import CorpusLayout
from Data.modules.common.paths import normalize_path_key
from Data.modules.datasets.offline import ALLOWED_EXTENSIONS, discover_under_roots
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import (
    DatasetJobStatus,
    DatasetJobType,
    IndexStatus,
)
from Data.modules.knowledge import KnowledgeStore
from Data.modules.knowledge.retrieval import HybridRetriever, RetrievalQuery


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


class PathNormalizeTests(unittest.TestCase):
    def test_windows_path_casing_and_separators(self) -> None:
        a = normalize_path_key(r"D:\ModelData\foo")
        b = normalize_path_key("d:/ModelData/foo/")
        c = normalize_path_key(r"D:/ModelData/foo")
        self.assertEqual(a, b)
        self.assertEqual(b, c)


class DatasetLibraryBrainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data_root = self.root / "ModelData"
        self.data_root.mkdir()
        self.db = self.root / "leviathan.db"
        self.corpus = _layout(self.data_root / "leviathan")
        self.knowledge = KnowledgeStore(self.db, data_root=self.data_root)
        self.knowledge.initialize()
        self.store = DatasetStore(self.db)
        self.store.initialize()

        # Minimal settings stub with knowledge.data_root
        class _K:
            data_root = self.data_root

        class _S:
            knowledge = _K()
            research_integration = None

        self.service = DatasetService(
            self.store,
            corpus=self.corpus,
            knowledge=self.knowledge,
            settings=_S(),  # type: ignore[arg-type]
            allowed_import_roots=[self.data_root, self.corpus.root],
        )
        self.service.datasets_auto_index_ready_to_knowledge = False
        app = FastAPI()
        app.include_router(build_datasets_router(self.service))
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_parquet_in_allowed_extensions(self) -> None:
        self.assertIn(".parquet", ALLOWED_EXTENSIONS)
        self.assertIn(".jsonl", ALLOWED_EXTENSIONS)

    def test_discover_legacy_and_corpus_without_duplicates(self) -> None:
        legacy = self.data_root / "legacy_dataset.jsonl"
        legacy.write_text('{"id":"1","text":"alpha legacy knowledge"}\n', encoding="utf-8")
        under = self.corpus.datasets_raw / "keep.jsonl"
        under.write_text('{"id":"2","text":"corpus raw"}\n', encoding="utf-8")
        # Derived tree must be skipped when scanning data_root
        derived = self.corpus.datasets_materialized / "skip.jsonl"
        derived.parent.mkdir(parents=True, exist_ok=True)
        derived.write_text('{"id":"3","text":"derived"}\n', encoding="utf-8")

        disc = self.service.discover_offline_sources(max_files=200)
        paths = {s["path"] for s in disc["sources"]}
        self.assertTrue(any(str(legacy.resolve()) == p or legacy.name in p for p in paths))
        # materialize file should not appear as a separate discovery when under skip paths
        self.assertFalse(any("skip.jsonl" in p for p in paths))

        first = self.service.refresh_dataset_library(max_files=200)
        self.assertGreaterEqual(first["created"], 1)
        second = self.service.refresh_dataset_library(max_files=200)
        self.assertEqual(second["created"], 0)
        names = {d["name"] for d in second["datasets"]}
        self.assertTrue(any("legacy" in n for n in names))

    def test_same_path_casing_does_not_duplicate(self) -> None:
        path = self.data_root / "casing.jsonl"
        path.write_text('{"id":"1","text":"x"}\n', encoding="utf-8")
        self.service.refresh_dataset_library()
        # Re-register with alternate path spelling via direct call
        src = {
            "path": str(path),
            "pathKey": normalize_path_key(str(path).upper() if False else path),
            "kind": "file",
            "displayName": "casing",
            "format": "jsonl",
            "sizeBytes": path.stat().st_size,
            "readable": True,
            "rootId": "data_root",
            "fingerprint": "x",
        }
        _, created = self.service._register_discovered_source(src)
        self.assertFalse(created)
        self.assertEqual(len(self.service.list_datasets()), 1)

    def test_kennis_leren_indexes_into_knowledge_and_retrieval(self) -> None:
        path = self.data_root / "learn_me.jsonl"
        path.write_text(
            "\n".join(json.dumps({"id": str(i), "text": f"leviathan signal {i} unique"}) for i in range(1, 4))
            + "\n",
            encoding="utf-8",
        )
        self.service.refresh_dataset_library()
        ds = self.service.list_datasets()[0]
        job = self.service.enqueue_learn_to_brain(ds.dataset_id)
        self.assertEqual(job.job_type, DatasetJobType.INDEX)
        self.assertTrue(job.config.get("learnToBrain"))
        done = self.service.process_jobs(max_jobs=1)[0]
        self.assertEqual(done.status, DatasetJobStatus.COMPLETED, done.error)
        brain = self.service.brain_status_for_dataset(ds.dataset_id)
        self.assertTrue(brain["learned"])
        self.assertEqual(brain["brainStatus"], "learned")

        learned = self.service.list_learned_datasets()
        self.assertEqual(len(learned), 1)
        self.assertEqual(learned[0]["datasetId"], ds.dataset_id)

        # Idempotent — second learn without rebuild is refused
        with self.assertRaises(Exception) as ctx:
            self.service.enqueue_learn_to_brain(ds.dataset_id)
        self.assertEqual(getattr(ctx.exception, "code", None), "already_learned")

        # Knowledge is queryable through the shared KnowledgeStore retriever
        retriever = HybridRetriever(self.knowledge)
        hits = retriever.search(RetrievalQuery(text="leviathan signal", limit=5))
        self.assertTrue(hits)
        self.assertTrue(any(str(h.source).startswith("dataset:") for h in hits))

    def test_failed_index_not_listed_as_learned(self) -> None:
        path = self.data_root / "fail.jsonl"
        path.write_text('{"id":"1","text":"ok"}\n', encoding="utf-8")
        self.service.refresh_dataset_library()
        ds = self.service.list_datasets()[0]
        # Create a FAILED index without READY
        ver = self.service.list_versions(ds.dataset_id)[0]
        self.store.create_index(
            dataset_id=ds.dataset_id,
            version_id=ver.version_id,
            status=IndexStatus.FAILED,
            provenance={"error": "boom"},
        )
        self.assertEqual(self.service.list_learned_datasets(), [])
        brain = self.service.brain_status_for_dataset(ds.dataset_id)
        self.assertEqual(brain["brainStatus"], "failed")
        self.assertFalse(brain["learned"])

    def test_missing_source_flag_non_destructive(self) -> None:
        path = self.data_root / "gone.jsonl"
        path.write_text('{"id":"1","text":"temp"}\n', encoding="utf-8")
        self.service.refresh_dataset_library()
        ds = self.service.list_datasets()[0]
        path.unlink()
        result = self.service.refresh_dataset_library()
        self.assertGreaterEqual(result["missingSources"], 1)
        still = self.service.get_dataset(ds.dataset_id)
        self.assertTrue((still.metadata or {}).get("sourceMissing"))
        # Record still present
        self.assertEqual(len(self.service.list_datasets()), 1)

    def test_api_library_refresh_and_learn(self) -> None:
        path = self.data_root / "api_ds.jsonl"
        path.write_text('{"id":"1","text":"api learnable content"}\n', encoding="utf-8")
        res = self.client.post("/api/datasets/library/refresh")
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertGreaterEqual(body["created"], 1)
        ds_id = body["datasets"][0]["datasetId"]

        learn = self.client.post(f"/api/datasets/{ds_id}/learn", json={})
        self.assertEqual(learn.status_code, 200, learn.text)
        job = learn.json()["job"]
        self.assertEqual(job["jobType"], "index")
        done = self.service.process_jobs(max_jobs=1)[0]
        self.assertEqual(done.status, DatasetJobStatus.COMPLETED, done.error)

        learned = self.client.get("/api/datasets/learned")
        self.assertEqual(learned.status_code, 200)
        ids = {d["datasetId"] for d in learned.json()["datasets"]}
        self.assertIn(ds_id, ids)

    def test_hf_cache_discovers_repo_not_shards(self) -> None:
        repo = self.corpus.hf_cache / "datasets--org--demo"
        snap = repo / "snapshots" / "abc123"
        snap.mkdir(parents=True)
        (snap / "train.parquet").write_bytes(b"PAR1" + b"\x00" * 8)
        (snap / "README.md").write_text("# demo\n", encoding="utf-8")
        # Extra shard-looking files should not each become datasets
        (snap / "data-00001-of-00002.jsonl").write_text('{"id":"1","text":"a"}\n', encoding="utf-8")
        sources = discover_under_roots(
            [("hf_cache", self.corpus.hf_cache)],
            max_files=50,
        )
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].kind, "hf_cache")
        self.assertEqual(sources[0].hf_repo_id, "org/demo")


if __name__ == "__main__":
    unittest.main()
