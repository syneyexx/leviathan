"""WAVE 01 — Canonical DatasetLearningState consistency.

READY Brain index dominates stale jobs. Frontend helpers must not invent
INDEXING from job lists when learningState says LEARNED.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Data.backend.routes.datasets import build_datasets_router
from Data.modules.common.corpus import CorpusLayout
from Data.modules.datasets.learning_state import (
    DatasetLearningCanonicalState,
    compute_dataset_learning_state,
)
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import (
    DatasetIndex,
    DatasetJob,
    DatasetJobStatus,
    DatasetJobType,
    DatasetRecord,
    DatasetStatus,
    IndexStatus,
    SourceType,
)
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


class DatasetLearningStateTests(unittest.TestCase):
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
            embedding_provider=LocalHashEmbeddingProvider(dimensions=32),
        )
        self.knowledge.initialize()
        self.store = DatasetStore(self.db)
        self.store.initialize()

        class _K:
            data_root = self.data_root
            embedding_provider = "hash"
            hash_dimensions = 32

        class _RI:
            datasets_auto_index_ready_to_knowledge = False
            dataset_jobs_runner = "none"
            dataset_index_batch_size = 5
            dataset_max_relations_per_doc = 12
            dataset_extract_relations = True

        class _S:
            knowledge = _K()
            research_integration = _RI()

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

    def _import_jsonl(self, name: str = "ds.jsonl") -> str:
        path = self.data_root / name
        path.write_text(
            "\n".join(json.dumps({"id": str(i), "text": f"alpha signal {i}"}) for i in range(1, 4))
            + "\n",
            encoding="utf-8",
        )
        result = self.service.import_local_sync(str(path), name=name, materialize=True)
        return result["dataset"]["datasetId"]

    def _learn(self, dataset_id: str) -> None:
        job = self.service.enqueue_learn_to_brain(dataset_id)
        done_list = self.service.process_jobs(max_jobs=5)
        done = next((j for j in done_list if j.job_id == job.job_id), done_list[-1] if done_list else None)
        self.assertIsNotNone(done)
        assert done is not None
        self.assertEqual(done.status, DatasetJobStatus.COMPLETED, done.error)

    def test_ready_plus_stale_queued_job_is_learned(self) -> None:
        ds_id = self._import_jsonl()
        self._learn(ds_id)
        ver = self.service.list_versions(ds_id)[0]
        stale = self.store.create_job(
            job_type=DatasetJobType.INDEX,
            dataset_id=ds_id,
            version_id=ver.version_id,
            status=DatasetJobStatus.QUEUED,
            config={"autoIndex": True},
        )
        self.store.update_job(stale.job_id, phase="queued", progress=0.35)
        brain = self.service.brain_status_for_dataset(ds_id)
        learning = self.service.learning_state_for_dataset(ds_id)
        self.assertEqual(learning["canonicalState"], "LEARNED")
        self.assertTrue(learning["learned"])
        self.assertTrue(learning["stale"])
        self.assertEqual(brain["brainStatus"], "learned")
        self.assertTrue(brain["learned"])
        updated = self.service.reconcile_stale_learning_jobs(dataset_id=ds_id)
        self.assertTrue(any(j.job_id == stale.job_id for j in updated))
        refreshed = self.store.get_job(stale.job_id)
        assert refreshed is not None
        self.assertEqual(refreshed.status, DatasetJobStatus.CANCELLED)
        learning2 = self.service.learning_state_for_dataset(ds_id)
        self.assertEqual(learning2["canonicalState"], "LEARNED")
        self.assertFalse(learning2["stale"])

    def test_ready_plus_active_rebuild_is_rebuilding_prior_usable(self) -> None:
        ds_id = self._import_jsonl("rebuild.jsonl")
        self._learn(ds_id)
        ready = self.service.brain_status_for_dataset(ds_id)
        self.assertTrue(ready["learned"])
        prior_index = ready["indexId"]
        ver = self.service.list_versions(ds_id)[0]
        job = self.store.create_job(
            job_type=DatasetJobType.INDEX,
            dataset_id=ds_id,
            version_id=ver.version_id,
            status=DatasetJobStatus.RUNNING,
            config={"rebuild": True, "learnToBrain": True},
        )
        self.store.update_job(job.job_id, phase="indexing", progress=0.2)
        learning = self.service.learning_state_for_dataset(ds_id)
        self.assertEqual(learning["canonicalState"], "REBUILDING")
        self.assertTrue(learning["learned"])
        self.assertTrue(learning["priorReadyPreserved"])
        self.assertEqual(learning["usableIndexId"], prior_index)
        brain = self.service.brain_status_for_dataset(ds_id)
        self.assertEqual(brain["brainStatus"], "indexing")
        self.assertTrue(brain["learned"])
        self.assertEqual(brain["usableIndexId"], prior_index)

    def test_dead_index_worker_reconciled(self) -> None:
        ds_id = self._import_jsonl("dead.jsonl")
        ver = self.service.list_versions(ds_id)[0]
        job = self.store.create_job(
            job_type=DatasetJobType.INDEX,
            dataset_id=ds_id,
            version_id=ver.version_id,
            status=DatasetJobStatus.RUNNING,
            config={"learnToBrain": True},
        )
        self.store.update_job(job.job_id, phase="indexing", progress=0.4, worker_pid=9_999_999)
        updated = self.service.runner.reconcile_interrupted()
        self.assertTrue(any(j.job_id == job.job_id for j in updated))
        got = self.store.get_job(job.job_id)
        assert got is not None
        self.assertEqual(got.status, DatasetJobStatus.INTERRUPTED)
        learning = self.service.learning_state_for_dataset(ds_id)
        self.assertNotEqual(learning["canonicalState"], "INDEXING")

    def test_duplicate_auto_index_requests_do_not_stack(self) -> None:
        ds_id = self._import_jsonl("dup.jsonl")
        self._learn(ds_id)
        # Re-enable auto-index for this assertion.
        self.service.datasets_auto_index_ready_to_knowledge = True
        ver = self.service.pick_usable_version(ds_id)
        assert ver is not None
        first = self.service._maybe_auto_index_ready_version(ds_id, ver.version_id)
        self.assertIsNotNone(first)
        self.assertFalse(first.get("enqueued"))
        self.assertEqual(first.get("reason"), "already_indexed")
        second = self.service._maybe_auto_index_ready_version(ds_id, ver.version_id)
        self.assertFalse(second.get("enqueued"))
        active = [
            j
            for j in self.store.list_jobs(dataset_id=ds_id, limit=50)
            if j.job_type == DatasetJobType.INDEX
            and j.status in {DatasetJobStatus.QUEUED, DatasetJobStatus.RUNNING}
        ]
        self.assertEqual(active, [])

    def test_failed_rebuild_preserves_previous_ready(self) -> None:
        ds_id = self._import_jsonl("fail_rebuild.jsonl")
        self._learn(ds_id)
        ver = self.service.list_versions(ds_id)[0]
        prior = self.service.brain_status_for_dataset(ds_id)["indexId"]
        self.store.create_index(
            dataset_id=ds_id,
            version_id=ver.version_id,
            status=IndexStatus.FAILED,
            provenance={"error": "rebuild boom", "rebuild": True},
        )
        learning = self.service.learning_state_for_dataset(ds_id)
        self.assertEqual(learning["canonicalState"], "LEARNED")
        self.assertTrue(learning["learned"])
        self.assertEqual(learning["usableIndexId"], prior)
        self.assertEqual(learning["indexId"], prior)

    def test_api_consistency_across_endpoints(self) -> None:
        ds_id = self._import_jsonl("api.jsonl")
        self._learn(ds_id)
        ver = self.service.list_versions(ds_id)[0]
        stale = self.store.create_job(
            job_type=DatasetJobType.INDEX,
            dataset_id=ds_id,
            version_id=ver.version_id,
            status=DatasetJobStatus.QUEUED,
            config={"autoIndex": True},
        )
        self.store.update_job(stale.job_id, progress=0.35)
        detail = self.client.get(f"/api/datasets/{ds_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        body = detail.json()
        self.assertEqual(body["canonicalState"], "LEARNED")
        self.assertEqual(body["brainStatus"], "learned")
        self.assertTrue(body["learned"])
        self.assertEqual(body["learningState"]["canonicalState"], "LEARNED")

        ls = self.client.get(f"/api/datasets/{ds_id}/learning-state")
        self.assertEqual(ls.status_code, 200, ls.text)
        self.assertEqual(ls.json()["learningState"]["canonicalState"], "LEARNED")

        lib = self.client.get("/api/datasets?includeBrain=true")
        self.assertEqual(lib.status_code, 200)
        row = next(d for d in lib.json()["datasets"] if d["datasetId"] == ds_id)
        self.assertEqual(row["canonicalState"], "LEARNED")
        self.assertEqual(row["brainStatus"], "learned")
        self.assertTrue(row["learned"])

        learned = self.client.get("/api/datasets/learned")
        self.assertEqual(learned.status_code, 200)
        ids = {d["datasetId"] for d in learned.json()["datasets"]}
        self.assertIn(ds_id, ids)

    def test_no_fake_progress_when_indeterminate(self) -> None:
        ds_id = self._import_jsonl("prog.jsonl")
        ver = self.service.list_versions(ds_id)[0]
        job = self.store.create_job(
            job_type=DatasetJobType.INDEX,
            dataset_id=ds_id,
            version_id=ver.version_id,
            status=DatasetJobStatus.RUNNING,
            config={"learnToBrain": True},
        )
        self.store.update_job(job.job_id, phase="indexing", progress=None)
        learning = self.service.learning_state_for_dataset(ds_id)
        self.assertEqual(learning["canonicalState"], "INDEXING")
        self.assertIsNone(learning["progress"])

    def test_pure_compute_ready_dominates_stale(self) -> None:
        now = "2026-09-26T00:00:00+00:00"
        ds = DatasetRecord(
            dataset_id="d1",
            name="t",
            source_type=SourceType.LOCAL,
            status=DatasetStatus.READY,
            created_at=now,
            updated_at=now,
            raw_path="/x",
        )
        idx = DatasetIndex(
            index_id="i1",
            dataset_id="d1",
            version_id="v1",
            status=IndexStatus.READY,
            created_at=now,
            updated_at=now,
            chunk_count=5,
            provenance={"documentCount": 2},
        )
        job = DatasetJob(
            job_id="j1",
            job_type=DatasetJobType.INDEX,
            status=DatasetJobStatus.QUEUED,
            created_at=now,
            updated_at=now,
            dataset_id="d1",
            version_id="v1",
            config={},
            progress=0.35,
        )
        state = compute_dataset_learning_state(
            dataset=ds, versions=[], indexes=[idx], jobs=[job]
        )
        self.assertEqual(state.canonical_state, DatasetLearningCanonicalState.LEARNED)
        self.assertTrue(state.stale)
        self.assertEqual(state.progress, 1.0)


if __name__ == "__main__":
    unittest.main()
