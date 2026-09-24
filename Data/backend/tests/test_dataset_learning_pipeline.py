"""End-to-end Dataset Learning pipeline: import → index → search → relations → Brain → Agents."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Data.backend.routes.agents import build_agents_router
from Data.backend.routes.brain import build_brain_router
from Data.backend.routes.datasets import build_datasets_router
from Data.modules.agents.fleet import DATASET_LEARNING_SYSTEM_KEY, AgentFleetService
from Data.modules.agents.runtime import AgentRuntime
from Data.modules.agents.store import AgentFleetStore
from Data.modules.brain import BrainQueryFacade
from Data.modules.common.corpus import CorpusLayout
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.sidecar import SIDECAR_FILENAME, read_sidecar, write_tombstone
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import DatasetJobStatus, DatasetJobType, IndexStatus
from Data.modules.knowledge import KnowledgeStore
from Data.modules.knowledge.embeddings import LocalHashEmbeddingProvider, NullEmbeddingProvider
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


class _FakeRuntime(AgentRuntime):
    def __init__(self) -> None:
        # Minimal stub — fleet only needs agents_enabled for health.
        self.agents_enabled = True  # type: ignore[assignment]


class DatasetLearningPipelineTests(unittest.TestCase):
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

        self.settings = _S()
        self.service = DatasetService(
            self.store,
            corpus=self.corpus,
            knowledge=self.knowledge,
            settings=self.settings,  # type: ignore[arg-type]
            allowed_import_roots=[self.data_root, self.corpus.root],
        )
        self.service.datasets_auto_index_ready_to_knowledge = False

        fleet_store = AgentFleetStore(self.db)
        # AgentRuntime is heavy; use a lightweight stand-in via subclassing if needed.
        from Data.modules.execution.gateway import ExecutionGateway
        from Data.modules.jobs.runtime import JobRuntime
        from Data.modules.jobs.store import JobStore

        # Prefer constructing a real lightweight runtime when possible.
        try:
            job_store = JobStore(self.db)
            job_store.initialize()
            # Many installs wire ExecutionGateway with many deps — use fleet with stub.
            self.fleet = AgentFleetService(
                fleet_store,
                runtime=_FakeRuntime(),  # type: ignore[arg-type]
                dataset_activity_provider=lambda: self.service.learning_activity(limit=40),
            )
        except Exception:
            self.fleet = AgentFleetService(
                fleet_store,
                runtime=_FakeRuntime(),  # type: ignore[arg-type]
                dataset_activity_provider=lambda: self.service.learning_activity(limit=40),
            )
        self.fleet.initialize(seed_defaults=True)

        self.brain = BrainQueryFacade(
            knowledge_list=lambda: self.knowledge.list_documents(limit=100),
            dataset_list=lambda: self.service.list_library_datasets(limit=100),
            relation_list=lambda: self.knowledge.list_relation_atoms(limit=100),
            max_nodes=100,
            max_edges=200,
        )

        app = FastAPI()
        app.include_router(build_datasets_router(self.service))
        app.include_router(build_agents_router(self.fleet))
        app.include_router(build_brain_router(self.brain))
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_fixture(self, name: str, rows: list[dict]) -> Path:
        path = self.data_root / name
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        return path

    def test_e2e_import_index_search_relation_brain_agents(self) -> None:
        path = self._write_fixture(
            "learn_e2e.jsonl",
            [
                {
                    "id": "r1",
                    "text": "Alpha entity connects to Beta entity in the leviathan corpus.",
                    "labels": {
                        "subject": "Alpha",
                        "object": "Beta",
                        "relations": [
                            {
                                "subject": "Alpha",
                                "object": "Beta",
                                "relation": "like",
                                "confidence": 0.9,
                                "evidence": "Alpha entity connects to Beta entity",
                            }
                        ],
                    },
                },
                {
                    "id": "r2",
                    "text": "Gamma topic discusses leviathan signal uniquely.",
                    "labels": {"topic": "Gamma", "tag": "leviathan"},
                },
            ],
        )
        imported = self.service.import_local_sync(str(path), name="e2e-learn", materialize=True)
        ds_id = imported["dataset"]["datasetId"]

        # Sidecar written next to corpus raw folder
        sidecar = read_sidecar(self.corpus.datasets_raw / ds_id / SIDECAR_FILENAME)
        self.assertIsNotNone(sidecar)
        self.assertEqual(sidecar["datasetId"], ds_id)

        t0 = time.perf_counter()
        job = self.service.enqueue_learn_to_brain(ds_id, offline_only=False)
        done = self.service.process_jobs(max_jobs=1)[0]
        elapsed = time.perf_counter() - t0
        self.assertEqual(done.status, DatasetJobStatus.COMPLETED, done.error)
        self.assertGreaterEqual(int((done.result or {}).get("relationsAccepted") or 0), 1)
        self.assertIn((done.result or {}).get("embeddingMode"), {"non_semantic_fallback", "semantic_embeddings"})
        self.assertFalse((done.result or {}).get("embeddingsSemantic"))

        brain = self.service.brain_status_for_dataset(ds_id)
        self.assertTrue(brain["learned"])
        ladder = brain["learning"]
        self.assertTrue(ladder["indexed"])
        self.assertTrue(ladder["brainSearchable"])
        self.assertTrue(ladder["relationsVerified"])
        self.assertFalse(ladder["embeddingsSemantic"])

        # Search
        retriever = HybridRetriever(self.knowledge)
        hits = retriever.search(RetrievalQuery(text="leviathan signal", limit=5))
        self.assertTrue(hits)

        # Relations stored
        atoms = self.knowledge.list_relation_atoms(limit=50)
        self.assertTrue(any(a.document_id and "dataset:" in (a.document_id or "") for a in atoms))

        # Brain graph includes dataset + relation edges
        graph = self.client.get("/api/brain/graph?limit=80").json()
        node_types = {n["type"] for n in graph["nodes"]}
        self.assertIn("dataset", node_types)
        self.assertTrue(graph["edges"])

        # Agents page activity
        activity = self.client.get("/api/agents/dataset-learning").json()
        self.assertIsNotNone(activity["agent"])
        self.assertEqual(activity["agent"]["metadata"]["systemKey"], DATASET_LEARNING_SYSTEM_KEY)
        self.assertEqual(activity["activity"]["activeCount"], 0)
        self.assertGreaterEqual(len(activity["activity"]["recent"]), 1)
        recent = activity["activity"]["recent"][0]
        self.assertEqual(recent["jobId"], done.job_id)
        self.assertIn("activity", recent)

        # Idempotent second index of same content does not duplicate docs
        doc_count_1 = len(self.knowledge.list_documents(limit=500))
        job2 = self.service.enqueue_index(
            ds_id,
            self.service.list_versions(ds_id)[-1].version_id,
            rebuild=True,
        )
        # pick materialized version
        mat = next(
            v
            for v in self.service.list_versions(ds_id)
            if v.kind.value == "materialized"
        )
        job2 = self.service.enqueue_index(ds_id, mat.version_id, rebuild=True)
        done2 = self.service.process_jobs(max_jobs=1)[0]
        self.assertEqual(done2.status, DatasetJobStatus.COMPLETED, done2.error)
        self.assertGreaterEqual(int((done2.result or {}).get("skippedUnchanged") or 0), 1)
        doc_count_2 = len(self.knowledge.list_documents(limit=500))
        self.assertEqual(doc_count_1, doc_count_2)

        # Timing note (no speedup claim)
        self.assertGreater(elapsed, 0.0)

    def test_streaming_large_fixture_and_cancel(self) -> None:
        rows = [
            {
                "id": f"row-{i}",
                "text": f"streaming fixture row {i} with unique token tok{i}",
                "labels": {"subject": f"S{i}", "object": f"O{i}"},
            }
            for i in range(120)
        ]
        path = self._write_fixture("large.jsonl", rows)
        imported = self.service.import_local_sync(str(path), materialize=True)
        ds_id = imported["dataset"]["datasetId"]
        mat = next(v for v in self.service.list_versions(ds_id) if v.kind.value == "materialized")
        job = self.service.enqueue_index(ds_id, mat.version_id, max_records=40)
        # Cancel while queued — store marks CANCELLED before a worker claims it.
        cancelled = self.service.cancel_job(job.job_id)
        self.assertEqual(cancelled.status, DatasetJobStatus.CANCELLED)
        # Nothing left to process for that job.
        self.assertEqual(self.service.process_jobs(max_jobs=1), [])

        # Fresh run processes bounded batch without loading entire corpus into memory
        job2 = self.service.enqueue_index(ds_id, mat.version_id, max_records=80)
        done2 = self.service.process_jobs(max_jobs=1)[0]
        self.assertEqual(done2.status, DatasetJobStatus.COMPLETED, done2.error)
        self.assertLessEqual(int((done2.result or {}).get("processedCount") or 0), 80)

    def test_null_embedding_provider_honest(self) -> None:
        self.knowledge.embedding_provider = NullEmbeddingProvider()
        path = self._write_fixture(
            "null_emb.jsonl",
            [{"id": "1", "text": "lexical only content about orca whales"}],
        )
        imported = self.service.import_local_sync(str(path), materialize=True)
        ds_id = imported["dataset"]["datasetId"]
        job = self.service.enqueue_learn_to_brain(ds_id, offline_only=False)
        done = self.service.process_jobs(max_jobs=1)[0]
        self.assertEqual(done.status, DatasetJobStatus.COMPLETED, done.error)
        self.assertEqual((done.result or {}).get("embeddingMode"), "lexical_only")
        self.assertFalse((done.result or {}).get("embeddingsSemantic"))
        self.assertFalse((done.result or {}).get("embeddingsAvailable"))

    def test_missing_source_fails_index(self) -> None:
        path = self._write_fixture("gone.jsonl", [{"id": "1", "text": "temp"}])
        imported = self.service.import_local_sync(str(path), materialize=True)
        ds_id = imported["dataset"]["datasetId"]
        mat = next(v for v in self.service.list_versions(ds_id) if v.kind.value == "materialized")
        Path(mat.storage_path).unlink()
        # Early routing refuses missing storage; create job directly and run handler.
        from Data.modules.datasets.types import DatasetError

        with self.assertRaises(DatasetError) as ctx:
            self.service.enqueue_index(ds_id, mat.version_id)
        self.assertIn(ctx.exception.code, {"storage_missing", "storage_not_file", "no_indexable_version"})
        job = self.store.create_job(
            job_type=DatasetJobType.INDEX,
            dataset_id=ds_id,
            version_id=mat.version_id,
            config={"requestedVersionId": mat.version_id, "scope": "dataset"},
        )
        done = self.service.process_jobs(max_jobs=1)[0]
        self.assertEqual(done.job_id, job.job_id)
        self.assertEqual(done.status, DatasetJobStatus.FAILED)

    def test_sidecar_reconcile_and_tombstone(self) -> None:
        path = self._write_fixture("side.jsonl", [{"id": "1", "text": "sidecar restore me"}])
        imported = self.service.import_local_sync(str(path), materialize=True)
        ds_id = imported["dataset"]["datasetId"]
        self.service.write_dataset_sidecar(ds_id)
        raw_dir = self.corpus.datasets_raw / ds_id
        sidecar = read_sidecar(raw_dir / SIDECAR_FILENAME)
        self.assertIsNotNone(sidecar)

        # Simulate clean install: wipe catalog, keep files + sidecar
        self.store.delete_dataset(ds_id)
        self.assertIsNone(self.store.get_dataset(ds_id))
        result = self.service.reconcile_sidecars()
        self.assertGreaterEqual(result["created"], 1)
        self.assertIn(ds_id, result["restoredDatasetIds"])
        restored = self.service.get_dataset(ds_id)
        self.assertEqual(restored.name, sidecar["name"])

        # Tombstone blocks auto-restore
        self.service.delete_dataset(ds_id, write_tombstone_file=True)
        # Ensure sidecar still present but tombstoned
        write_tombstone(raw_dir, dataset_id=ds_id, reason="deleted")
        result2 = self.service.reconcile_sidecars()
        self.assertGreaterEqual(result2["skippedTombstone"], 1)
        self.assertIsNone(self.store.get_dataset(ds_id))

    def test_system_agent_ensured_on_existing_db(self) -> None:
        # Seed without Dataset Learning, then ensure
        store2 = AgentFleetStore(self.root / "fleet2.db")
        fleet2 = AgentFleetService(store2, runtime=_FakeRuntime())  # type: ignore[arg-type]
        store2.initialize()
        # Create only Research
        fleet2.create_agent(
            {
                "name": "Research",
                "kind": "research",
                "metadata": {"systemKey": "research"},
            }
        )
        self.assertIsNone(fleet2.get_system_agent(DATASET_LEARNING_SYSTEM_KEY))
        created = fleet2.ensure_system_agents()
        self.assertTrue(any(a.name == "Dataset Learning" for a in created) or fleet2.get_system_agent(DATASET_LEARNING_SYSTEM_KEY))
        agent = fleet2.get_system_agent(DATASET_LEARNING_SYSTEM_KEY)
        self.assertIsNotNone(agent)
        self.assertEqual(agent.metadata.get("systemKey"), DATASET_LEARNING_SYSTEM_KEY)

    def test_duplicate_learn_no_duplicate_relations(self) -> None:
        path = self._write_fixture(
            "dup.jsonl",
            [
                {
                    "id": "a",
                    "text": "North links South with evidence North links South.",
                    "labels": {
                        "relations": [
                            {
                                "subject": "North",
                                "object": "South",
                                "confidence": 0.9,
                                "evidence": "North links South",
                            }
                        ]
                    },
                }
            ],
        )
        imported = self.service.import_local_sync(str(path), materialize=True)
        ds_id = imported["dataset"]["datasetId"]
        self.service.enqueue_learn_to_brain(ds_id, offline_only=False)
        self.service.process_jobs(max_jobs=1)
        count1 = len(self.knowledge.list_relation_atoms(limit=500))
        mat = next(v for v in self.service.list_versions(ds_id) if v.kind.value == "materialized")
        self.service.enqueue_index(ds_id, mat.version_id, rebuild=True)
        self.service.process_jobs(max_jobs=1)
        count2 = len(self.knowledge.list_relation_atoms(limit=500))
        self.assertEqual(count1, count2)


if __name__ == "__main__":
    unittest.main()
