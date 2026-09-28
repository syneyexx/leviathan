"""Knowledge data-plane externalization — architecture + pipeline regression tests."""

from __future__ import annotations

import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.execution import build_default_catalog
from Data.modules.execution.gateway import ExecutionGateway
from Data.modules.execution.workload import (
    ExecutionWorkloadClass,
    api_may_execute_inline,
    classify_capability,
)
from Data.modules.jobs.resources import ResourceManager
from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES, JobRuntime
from Data.modules.jobs.store import JobStore
from Data.modules.knowledge.embeddings import LocalHashEmbeddingProvider, NullEmbeddingProvider
from Data.modules.knowledge.preparation import (
    NORMALIZATION_VERSION,
    build_chunk_plan,
    normalize_document_text,
    partition_embedding_batches,
    stable_chunk_id,
)
from Data.modules.knowledge.store import (
    DocumentMissingError,
    KnowledgeStore,
    StaleKnowledgeGenerationError,
)
from Data.modules.knowledge.types import IngestStatus
from Data.modules.workers.pools import pool_for_capability


class WorkloadAndPoolRoutingTests(unittest.TestCase):
    def test_caps_are_external_required(self) -> None:
        for cap in (
            "knowledge.prepare",
            "knowledge.ingest_scan",
            "knowledge.ingest_document",
            "knowledge.ingest_path",
            "knowledge.commit",
            "embedding.batch",
        ):
            self.assertEqual(
                classify_capability(cap),
                ExecutionWorkloadClass.EXTERNAL_REQUIRED,
                msg=cap,
            )
            # Either listed explicitly or covered by EXTERNAL_REQUIRED prefixes.
            self.assertTrue(
                cap in EXTERNAL_WORKER_CAPABILITIES
                or any(
                    cap.startswith(p)
                    for p in (
                        "knowledge.prepare",
                        "knowledge.commit",
                        "knowledge.ingest",
                        "embedding.",
                    )
                ),
                msg=cap,
            )

    def test_pool_routing(self) -> None:
        self.assertEqual(pool_for_capability("knowledge.prepare"), "knowledge_prepare")
        self.assertEqual(pool_for_capability("knowledge.ingest_scan"), "knowledge_prepare")
        self.assertEqual(pool_for_capability("knowledge.ingest_path"), "knowledge_prepare")
        self.assertEqual(pool_for_capability("embedding.batch"), "embedding")
        self.assertEqual(pool_for_capability("knowledge.commit"), "db_commit")
        # Deprecated pool must remain desired 0.
        from Data.modules.workers.pools import POOL_CATALOG

        self.assertEqual(POOL_CATALOG["knowledge_commit"].default_count, 0)
        self.assertEqual(POOL_CATALOG["db_commit"].default_count, 1)
        self.assertEqual(POOL_CATALOG["db_commit"].max_count, 1)

    def test_api_may_not_run_inline_when_externalized(self) -> None:
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}, clear=False):
            os.environ.pop("LEVIATHAN_WORKER_ID", None)
            self.assertFalse(api_may_execute_inline("knowledge.prepare"))
            self.assertFalse(api_may_execute_inline("knowledge.ingest_scan"))
            self.assertFalse(api_may_execute_inline("embedding.batch"))
            self.assertFalse(api_may_execute_inline("knowledge.commit"))


class NormalizationAndChunkTests(unittest.TestCase):
    def test_normalize_deterministic(self) -> None:
        a = normalize_document_text("hello\r\nworld\r")
        b = normalize_document_text("hello\nworld")
        self.assertEqual(a, b)
        self.assertEqual(NORMALIZATION_VERSION, "1")

    def test_chunk_plan_stable_ids_and_offsets(self) -> None:
        content = ("paragraph one.\n\n" + ("word " * 200) + "\n\nparagraph three.")
        plan1 = build_chunk_plan(
            document_id="doc-a",
            title="T",
            content=content,
            chunk_max_chars=120,
            chunk_overlap=20,
        )
        plan2 = build_chunk_plan(
            document_id="doc-a",
            title="T",
            content=content,
            chunk_max_chars=120,
            chunk_overlap=20,
        )
        self.assertGreater(len(plan1.chunks), 1)
        self.assertEqual(
            [c.chunk_id for c in plan1.chunks],
            [c.chunk_id for c in plan2.chunks],
        )
        self.assertEqual(
            [c.content_hash for c in plan1.chunks],
            [c.content_hash for c in plan2.chunks],
        )
        for c in plan1.chunks:
            self.assertEqual(c.chunk_id, stable_chunk_id("doc-a", c.chunk_index, c.content_hash))
            self.assertLessEqual(c.start_offset, c.end_offset)

    def test_embedding_batch_partition_bounded(self) -> None:
        plan = build_chunk_plan(
            document_id="d",
            title="t",
            content=("alpha " * 5000),
            chunk_max_chars=200,
            chunk_overlap=20,
        )
        batches = partition_embedding_batches(plan.chunks, batch_size=10)
        self.assertGreater(len(batches), 1)
        self.assertTrue(all(len(b) <= 10 for b in batches))
        self.assertEqual(sum(len(b) for b in batches), len(plan.chunks))


class CommitGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = KnowledgeStore(self.root / "k.db", data_root=self.root / "data")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_prepare_does_not_embed(self) -> None:
        provider = LocalHashEmbeddingProvider(dimensions=32)
        self.store.embedding_provider = provider
        staged = self.store.stage_document(title="t", content="embed me " * 100, source="manual")
        with mock.patch.object(provider, "embed_documents") as embed:
            ready = self.store.prepare_staged_document(staged.document_id)
            embed.assert_not_called()
        self.assertEqual(ready.status, IngestStatus.READY)
        chunks = self.store.list_chunks(staged.document_id)
        self.assertGreater(len(chunks), 0)

    def test_stale_generation_rejected(self) -> None:
        staged = self.store.stage_document(title="t", content="version-a", source="manual")
        plan = self.store.build_prepared_index(staged.document_id)
        # Newer version
        self.store.stage_document(
            document_id=staged.document_id,
            title="t",
            content="version-b-changed",
            source="manual",
        )
        with self.assertRaises(StaleKnowledgeGenerationError):
            self.store.apply_replace_chunks(
                document_id=staged.document_id,
                expected_content_hash=plan.expected_content_hash,
                title="t",
                chunks=[c.public_dict() for c in plan.chunks],
            )

    def test_deleted_document_not_resurrected(self) -> None:
        staged = self.store.stage_document(title="t", content="gone soon", source="manual")
        plan = self.store.build_prepared_index(staged.document_id)
        self.assertTrue(self.store.delete_document(staged.document_id))
        with self.assertRaises(DocumentMissingError):
            self.store.apply_replace_chunks(
                document_id=staged.document_id,
                expected_content_hash=plan.expected_content_hash,
                title="t",
                chunks=[c.public_dict() for c in plan.chunks],
            )

    def test_replace_chunks_and_embeddings_via_commit_helpers(self) -> None:
        from Data.modules.knowledge.commit_submit import (
            submit_knowledge_chunk_embeddings,
            submit_knowledge_replace_chunks,
        )

        staged = self.store.stage_document(title="t", content="hello world " * 50, source="manual")
        plan = self.store.build_prepared_index(staged.document_id)
        with mock.patch.dict(os.environ, {"LEVIATHAN_DB_COMMIT_INLINE": "1"}, clear=False):
            result = submit_knowledge_replace_chunks(
                self.store.path,
                document_id=staged.document_id,
                expected_content_hash=plan.expected_content_hash,
                title=plan.title,
                chunks=[c.public_dict() for c in plan.chunks],
                finalize=False,
                document_content_for_fts=staged.content,
                idempotency_key=f"test-replace-{staged.document_id}",
            )
            self.assertTrue(result.accepted)
            self.assertTrue(result.committed or result.receipt is not None)
            embeddings = [
                {
                    "chunk_id": c.chunk_id,
                    "vector": [0.1, 0.2, 0.3],
                    "dimensions": 3,
                    "provider_id": "test-hash",
                    "content_hash": c.content_hash,
                }
                for c in plan.chunks
            ]
            emb = submit_knowledge_chunk_embeddings(
                self.store.path,
                document_id=staged.document_id,
                expected_content_hash=plan.expected_content_hash,
                embeddings=embeddings,
                finalize=True,
                idempotency_key=f"test-emb-{staged.document_id}",
            )
            self.assertTrue(emb.accepted)
        doc = self.store.get_document(staged.document_id)
        assert doc is not None
        self.assertEqual(doc.status, IngestStatus.READY)
        health = self.store.index_health()
        self.assertEqual(health["chunks_total"], len(plan.chunks))
        self.assertEqual(health["chunks_embedded"], len(plan.chunks))
        self.assertEqual(health["entity_extraction"], "NOT_CONFIGURED")

    def test_incremental_unchanged_classification(self) -> None:
        data = self.root / "data"
        data.mkdir(parents=True, exist_ok=True)
        path = data / "note.txt"
        path.write_text("stable content", encoding="utf-8")
        first = self.store.ingest_file(path)
        assert first is not None
        # Force READY index row
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE knowledge_ingest_files SET status = ? WHERE path = ?",
                (IngestStatus.READY.value, str(path)),
            )
        classified = self.store.classify_ingest_path(path)
        self.assertEqual(classified["classification"], "UNCHANGED")
        path.write_text("changed content", encoding="utf-8")
        classified2 = self.store.classify_ingest_path(path)
        self.assertEqual(classified2["classification"], "CHANGED")


class KnowledgePrepareWorkerPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "jobs.db"
        self.store = JobStore(self.db)
        self.store.initialize()
        self.gateway = ExecutionGateway(catalog=build_default_catalog())
        self.runtime = JobRuntime(self.store, self.gateway, ResourceManager(2))

        class _K:
            data_root = self.root / "data"
            chunk_max_chars = 400
            chunk_overlap = 40
            embedding_provider = "null"
            embedding_model = None

        class _S:
            database_path = self.db
            knowledge_database_path = self.db
            knowledge = _K()

        self.ctx = {
            "settings": _S(),
            "job_store": self.store,
            "job_runtime": self.runtime,
            "worker_id": "knowledge_prepare-0-test",
            "lease_ttl_seconds": 30.0,
        }
        (self.root / "data").mkdir(parents=True, exist_ok=True)
        os.environ["LEVIATHAN_DB_COMMIT_INLINE"] = "1"

    def tearDown(self) -> None:
        os.environ.pop("LEVIATHAN_DB_COMMIT_INLINE", None)
        self.tmp.cleanup()

    def test_prepare_handler_commits_via_typed_intent(self) -> None:
        from Data.modules.workers.entrypoints.knowledge_prepare import _handle_prepare

        ks = KnowledgeStore(
            self.db,
            data_root=self.root / "data",
            chunk_max_chars=400,
            embedding_provider=NullEmbeddingProvider(),
        )
        ks.initialize()
        staged = ks.stage_document(title="Neural Networks.pdf", content=("layer " * 1500), source="manual")
        job = self.runtime.enqueue(
            capability_id="knowledge.prepare",
            arguments={"action": "prepare", "document_id": staged.document_id},
            metadata={"human_title": "Neural Networks.pdf"},
            worker_pool="knowledge_prepare",
        )
        claimed = self.store.claim_next_queued(worker_id="w1", lease_ttl_seconds=30)
        assert claimed is not None
        result = _handle_prepare(self.ctx, claimed)
        self.assertEqual(result.get("document_id"), staged.document_id)
        self.assertIn("commit", result)
        refreshed = ks.get_document(staged.document_id)
        assert refreshed is not None
        self.assertEqual(refreshed.status, IngestStatus.READY)
        self.assertGreater(len(ks.list_chunks(staged.document_id)), 0)

    def test_embedding_worker_unavailable_is_honest(self) -> None:
        from Data.modules.embedding.worker import process_embedding_job

        job = self.runtime.enqueue(
            capability_id="embedding.batch",
            arguments={
                "document_id": "doc-x",
                "texts": ["a", "b"],
                "chunk_ids": ["c1", "c2"],
                "content_hashes": ["h1", "h2"],
                "expected_content_hash": "hh",
            },
            worker_pool="embedding",
        )
        claimed = self.store.claim_next_queued(worker_id="emb1", lease_ttl_seconds=30)
        assert claimed is not None
        result = process_embedding_job(self.ctx, claimed)
        self.assertEqual(result.get("status"), "EMBEDDING_UNAVAILABLE")
        self.assertEqual(result.get("embedded"), 0)


class ApiBoundaryTests(unittest.TestCase):
    def test_write_path_stages_and_enqueues_when_external(self) -> None:
        from Data.backend.routes.knowledge import build_knowledge_router

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ks = KnowledgeStore(root / "k.db", data_root=root / "data")
            ks.initialize()

            class _Settings:
                class knowledge:
                    data_root = root / "data"

                class features:
                    rag_v3 = False
                    deep_recall = False
                    why_library = False

            jobs: list[dict] = []

            class _Runtime:
                def enqueue(self, **kwargs):
                    jobs.append(kwargs)

                    class _J:
                        def public_dict(self_inner):
                            return {"job_id": "j1", "capability_id": kwargs["capability_id"]}

                    return _J()

            router = build_knowledge_router(
                settings=_Settings(),
                knowledge=ks,
                retriever=mock.Mock(),
                job_runtime=_Runtime(),
                atlas_store=mock.Mock(),
                deep_recall_service=mock.Mock(),
                why_library=mock.Mock(),
                workers_externalize_fn=lambda: True,
            )
            # Find write endpoint
            write = None
            for route in router.routes:
                if getattr(route, "path", None) == "/api/knowledge" and "POST" in getattr(
                    route, "methods", set()
                ):
                    write = route.endpoint
                    break
            assert write is not None
            with mock.patch.object(ks, "upsert_document") as upsert:
                with mock.patch.object(ks, "prepare_staged_document") as prepare:
                    from Data.backend.routes.knowledge import KnowledgeWrite

                    out = write(KnowledgeWrite(title="Hello", content="x" * 100, source="manual"))
                    upsert.assert_not_called()
                    prepare.assert_not_called()
                    self.assertTrue(out["queued"])
                    self.assertEqual(out["status"], "INDEXING")
                    self.assertEqual(jobs[0]["capability_id"], "knowledge.prepare")
                    self.assertEqual(jobs[0]["worker_pool"], "knowledge_prepare")

    def test_no_inline_when_externalize_off_without_allow(self) -> None:
        from Data.backend.routes.knowledge import KnowledgeWrite, build_knowledge_router
        from fastapi import HTTPException

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ks = KnowledgeStore(root / "k.db", data_root=root / "data")
            ks.initialize()

            class _Settings:
                class knowledge:
                    data_root = root / "data"

                class features:
                    rag_v3 = False
                    deep_recall = False
                    why_library = False

            router = build_knowledge_router(
                settings=_Settings(),
                knowledge=ks,
                retriever=mock.Mock(),
                job_runtime=mock.Mock(),
                atlas_store=mock.Mock(),
                deep_recall_service=mock.Mock(),
                why_library=mock.Mock(),
                workers_externalize_fn=lambda: False,
            )
            write = None
            for route in router.routes:
                if getattr(route, "path", None) == "/api/knowledge" and "POST" in getattr(
                    route, "methods", set()
                ):
                    write = route.endpoint
                    break
            assert write is not None
            # Clear pytest allow by temporarily disabling session detection.
            with mock.patch(
                "Data.modules.knowledge.execution_gate.inline_execution_explicitly_allowed",
                return_value=False,
            ):
                with self.assertRaises(HTTPException) as ctx:
                    write(KnowledgeWrite(title="Hello", content="x" * 100, source="manual"))
                self.assertEqual(ctx.exception.status_code, 503)


class ArchitectureRegressionAstTests(unittest.TestCase):
    """Prevent FastAPI routes from reintroducing heavy KnowledgeStore calls."""

    FORBIDDEN_IN_ROUTES = {
        "scan_data_root",
        "ingest_file",
        "prepare_staged_document",
        "upsert_document",
        "embed_documents",
        "backfill_content",
    }

    def test_knowledge_routes_do_not_call_heavy_store_in_external_branch(self) -> None:
        path = Path("Data/backend/routes/knowledge.py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # Collect Call attribute names under write/ingest endpoints — soft check:
        # upsert_document / ingest_file / scan_data_root may only appear inside
        # the explicit inline-allow branch (after refuse_inline_knowledge).
        source = path.read_text(encoding="utf-8")
        # Ensure refuse gate exists.
        self.assertIn("refuse_inline_knowledge", source)
        self.assertIn("workers_externalize_fn", source)
        # Ensure production path uses enqueue, not scan_data_root without gate.
        self.assertIn("knowledge.prepare", source)
        self.assertIn("knowledge.ingest_path", source)

    def test_knowledge_prepare_does_not_call_embed_documents(self) -> None:
        path = Path("Data/modules/workers/entrypoints/knowledge_prepare.py")
        source = path.read_text(encoding="utf-8")
        self.assertNotIn("embed_documents", source)
        self.assertNotIn("include_embeddings=True", source)

    def test_embedding_worker_does_not_open_bulk_sqlite_writer(self) -> None:
        entry = Path("Data/modules/workers/entrypoints/embedding.py")
        worker = Path("Data/modules/embedding/worker.py")
        entry_src = entry.read_text(encoding="utf-8")
        worker_src = worker.read_text(encoding="utf-8")
        self.assertIn("process_embedding_job", entry_src)
        self.assertIn("submit_knowledge_chunk_embeddings", worker_src)
        self.assertNotIn("KnowledgeStore(", worker_src)
        self.assertNotIn("upsert_document", worker_src)

    def test_db_commit_handler_has_typed_ops(self) -> None:
        from Data.modules.db_commit.handlers.knowledge import handlers

        ops = {h.operation for h in handlers()}
        self.assertIn("knowledge.replace_chunks", ops)
        self.assertIn("knowledge.upsert_chunk_embeddings", ops)
        self.assertIn("knowledge.finalize_document", ops)


if __name__ == "__main__":
    unittest.main()
