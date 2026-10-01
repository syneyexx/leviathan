"""P0-001 / I-001 — Dataset Knowledge source ↔ Research retrieval contract.

Proves LEARNED means Research can retrieve expected dataset evidence from the
canonical KnowledgeStore (no mocked Knowledge rows, no manually inserted docs).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.common.corpus import CorpusLayout
from Data.modules.datasets.knowledge_identity import (
    knowledge_source_for_version,
    research_scopes_for_dataset,
    resolve_index_scope,
)
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import DatasetJobStatus, IndexStatus
from Data.modules.knowledge import KnowledgeStore
from Data.modules.knowledge.embeddings import LocalHashEmbeddingProvider
from Data.modules.research.local_retrieval import LocalResearchRetriever, build_default_local_retriever
from Data.modules.research.service import ResearchService
from Data.modules.research.store import ResearchStore


UNIQUE_MARKER = "LEVIATHAN_UNIQUE_EVIDENCE_TOKEN_ZX9Q7_WAV3"


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


def _settings(root: Path):
    class _RI:
        datasets_auto_index_ready_to_knowledge = False
        dataset_jobs_runner = "inprocess_test"
        dataset_index_batch_size = 10
        dataset_max_relations_per_doc = 4
        dataset_extract_relations = False

    class _K:
        data_root = str(root / "knowledge")
        embedding_provider = "hash"
        hash_dimensions = 32
        embedding_model = "hash"

    class _S:
        knowledge = _K()
        research_integration = _RI()

    Path(_K.data_root).mkdir(parents=True, exist_ok=True)
    return _S()


class KnowledgeIdentityContractTests(unittest.TestCase):
    def test_resolve_replaces_legacy_default(self) -> None:
        src = resolve_index_scope(
            dataset_id="ds1", version_id="ver1", requested_scope="dataset"
        )
        self.assertEqual(src, "dataset:ds1:ver1")
        self.assertEqual(
            research_scopes_for_dataset("ds1", version_id="ver1"),
            ["dataset:ds1:ver1", "dataset:ds1"],
        )


class DatasetResearchRetrievalE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "lev.db"
        self.corpus = _layout(self.root / "corpus")
        self.store = DatasetStore(self.db)
        self.store.initialize()
        self.knowledge = KnowledgeStore(
            self.db,
            data_root=self.root / "knowledge",
            embedding_provider=LocalHashEmbeddingProvider(dimensions=32),
        )
        self.knowledge.initialize()
        self.ds_service = DatasetService(
            self.store,
            corpus=self.corpus,
            knowledge=self.knowledge,
            settings=_settings(self.root),  # type: ignore[arg-type]
            allowed_import_roots=[self.corpus.root],
            job_runtime=None,  # domain drain for tests
        )
        self.research_store = ResearchStore(self.db)
        self.research_store.initialize()
        self.research = ResearchService(
            self.research_store,
            knowledge=self.knowledge,
            corpus=self.corpus,
            dataset_service=self.ds_service,
            local=build_default_local_retriever(self.knowledge),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _force_knowledge_index(self, dataset_id: str) -> None:
        ds = self.ds_service.get_dataset(dataset_id)
        meta = dict(ds.metadata or {})
        meta["forceKnowledgeIndex"] = True
        self.store.update_dataset(dataset_id, metadata=meta)

    def _create_and_learn(self, *, name: str, marker: str) -> tuple[str, str]:
        raw = self.corpus.datasets_raw / f"{name}.jsonl"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(
            "\n".join(
                [
                    '{"id":"r1","text":"alpha context about widgets"}',
                    f'{{"id":"r2","text":"beta {marker} retrieval proof"}}',
                    '{"id":"r3","text":"gamma unrelated filler"}',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        imported = self.ds_service.import_local_sync(
            str(raw), name=name, materialize=True
        )
        ds_id = imported["dataset"]["datasetId"]
        self._force_knowledge_index(ds_id)
        learn = self.ds_service.enqueue_learn_to_brain(ds_id)
        done_list = self.ds_service.process_jobs(max_jobs=40)
        self.assertTrue(done_list)
        learn = self.store.get_job(learn.job_id)
        self.assertEqual(
            learn.status,
            DatasetJobStatus.COMPLETED,
            msg=learn.error,
        )
        learning = self.ds_service.learning_state_for_dataset(ds_id)
        self.assertEqual(learning.get("canonicalState"), "LEARNED")
        version_id = str(learning.get("versionId") or learn.version_id)
        # Prove Knowledge source is canonical
        expected_source = knowledge_source_for_version(ds_id, version_id)
        docs = self.knowledge.list_documents(limit=50)
        dataset_docs = [d for d in docs if d.source.startswith("dataset:")]
        self.assertTrue(dataset_docs)
        for d in dataset_docs:
            if (d.trust_metadata or {}).get("datasetId") == ds_id:
                self.assertEqual(d.source, expected_source)
                self.assertNotEqual(d.source, "dataset:dataset")
        indexes = self.store.list_indexes(ds_id)
        ready = [i for i in indexes if i.status == IndexStatus.READY]
        self.assertTrue(ready)
        self.assertEqual(ready[0].knowledge_scope, expected_source)
        return ds_id, version_id

    def test_learned_dataset_retrievable_by_research(self) -> None:
        dataset_id, version_id = self._create_and_learn(
            name="proof-ds", marker=UNIQUE_MARKER
        )
        project = self.research.create_project(
            topic="wave3-proof", objective="retrieve marker"
        )
        connected = self.research.connect_dataset(
            project.project_id, dataset_id=dataset_id, version_id=version_id
        )
        self.assertIn(
            knowledge_source_for_version(dataset_id, version_id),
            connected.local_scopes,
        )
        self.assertNotIn("dataset", connected.local_scopes)
        self.assertNotIn("dataset:dataset", connected.local_scopes)

        from Data.modules.knowledge.retrieval import HybridRetriever

        retriever = LocalResearchRetriever(HybridRetriever(self.knowledge))
        hits = retriever.search(
            UNIQUE_MARKER,
            limit=8,
            local_scopes=connected.local_scopes,
        )
        self.assertTrue(hits, msg="Research retrieval returned zero dataset evidence")
        joined = " ".join(h.content for h in hits)
        self.assertIn(UNIQUE_MARKER, joined)
        for h in hits:
            self.assertTrue(
                h.source.startswith(f"dataset:{dataset_id}"),
                msg=f"unexpected source {h.source}",
            )

    def test_multiple_datasets_do_not_cross_leak(self) -> None:
        marker_a = "UNIQUE_MARKER_AAA_WAV3"
        marker_b = "UNIQUE_MARKER_BBB_WAV3"
        id_a, ver_a = self._create_and_learn(name="ds-a", marker=marker_a)
        id_b, ver_b = self._create_and_learn(name="ds-b", marker=marker_b)
        project = self.research.create_project(topic="multi", objective="isolate")
        self.research.connect_dataset(project.project_id, dataset_id=id_a, version_id=ver_a)
        project = self.research.get_project(project.project_id)
        retriever = build_default_local_retriever(self.knowledge)
        hits_a = retriever.search(marker_a, limit=5, local_scopes=project.local_scopes)
        hits_b = retriever.search(marker_b, limit=5, local_scopes=project.local_scopes)
        self.assertTrue(hits_a)
        self.assertFalse(hits_b, msg="disconnected dataset B must not appear")
        self.research.connect_dataset(project.project_id, dataset_id=id_b, version_id=ver_b)
        project = self.research.get_project(project.project_id)
        hits_b2 = retriever.search(marker_b, limit=5, local_scopes=project.local_scopes)
        self.assertTrue(hits_b2)
        self.assertTrue(any(marker_b in h.content for h in hits_b2))

    def test_generic_knowledge_does_not_leak_into_dataset_scope(self) -> None:
        dataset_id, version_id = self._create_and_learn(
            name="scoped", marker="SCOPED_MARKER_WAV3"
        )
        self.knowledge.upsert_document(
            title="generic",
            content="SCOPED_MARKER_WAV3 lives in generic knowledge too",
            source="manual",
            document_id="generic-leak-doc",
        )
        project = self.research.create_project(topic="noleak", objective="scope")
        connected = self.research.connect_dataset(
            project.project_id, dataset_id=dataset_id, version_id=version_id
        )
        retriever = build_default_local_retriever(self.knowledge)
        hits = retriever.search(
            "SCOPED_MARKER_WAV3", limit=10, local_scopes=connected.local_scopes
        )
        self.assertTrue(hits)
        for h in hits:
            self.assertNotEqual(h.source, "manual")
            self.assertTrue(h.source.startswith(f"dataset:{dataset_id}"))

    def test_legacy_source_migration(self) -> None:
        dataset_id, version_id = self._create_and_learn(
            name="legacy-mig", marker="LEGACY_MIG_MARKER"
        )
        canonical = knowledge_source_for_version(dataset_id, version_id)
        docs = [
            d
            for d in self.knowledge.list_documents(limit=50)
            if (d.trust_metadata or {}).get("datasetId") == dataset_id
        ]
        self.assertTrue(docs)
        with self.knowledge.connect() as conn:
            for d in docs:
                conn.execute(
                    "UPDATE knowledge_documents SET source = ? WHERE id = ?",
                    ("dataset:dataset", d.document_id),
                )
            conn.commit()
        scopes = research_scopes_for_dataset(dataset_id, version_id=version_id)
        retriever = build_default_local_retriever(self.knowledge)
        pre = retriever.search("LEGACY_MIG_MARKER", limit=5, local_scopes=scopes)
        self.assertFalse(pre)
        result = self.ds_service.migrate_legacy_knowledge_sources(dataset_id=dataset_id)
        self.assertGreater(result["migrated"], 0)
        post = retriever.search("LEGACY_MIG_MARKER", limit=5, local_scopes=scopes)
        self.assertTrue(post)
        for h in post:
            self.assertEqual(h.source, canonical)


if __name__ == "__main__":
    unittest.main()
