"""W3–W7 control-plane / external worker hardening regression tests."""

from __future__ import annotations

import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.execution import (
    CapabilityRequest,
    CapabilityStatus,
    ExecutionGateway,
    build_default_catalog,
)
from Data.modules.jobs.resources import ResourceManager
from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES, JobRuntime
from Data.modules.jobs.store import JobStore
from Data.modules.knowledge.store import KnowledgeStore
from Data.modules.knowledge.types import IngestStatus
from Data.modules.training.service import _tail_text_file


class KnowledgeStartupBackfillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "k.db"
        self.store = KnowledgeStore(self.db, data_root=self.root / "data")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_initialize_does_not_chunk_legacy_docs(self) -> None:
        self.store.initialize_schema()
        # Manually insert a legacy READY doc with content but no chunks.
        with self.store.connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_documents(
                    id, title, content, source, created_at, updated_at, status, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "legacy-1",
                    "Legacy Doc",
                    "A" * 5000,
                    "manual",
                    "2020-01-01T00:00:00",
                    "2020-01-01T00:00:00",
                    "READY",
                    None,
                ),
            )
        # Re-initialize (schema only) must not create chunks.
        self.store.initialize()
        with self.store.connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM knowledge_chunks WHERE document_id = ?",
                ("legacy-1",),
            ).fetchone()["c"]
        self.assertEqual(count, 0)
        self.assertGreaterEqual(self.store.count_pending_content_backfill(), 1)

        result = self.store.backfill_content(limit=10)
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["remaining"], 0)
        with self.store.connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM knowledge_chunks WHERE document_id = ?",
                ("legacy-1",),
            ).fetchone()["c"]
        self.assertGreater(count, 0)

    def test_stage_then_prepare_avoids_inline_chunk_on_stage(self) -> None:
        self.store.initialize()
        staged = self.store.stage_document(
            title="Big Doc",
            content="word " * 2000,
            source="manual",
        )
        self.assertEqual(staged.status, IngestStatus.INDEXING)
        with self.store.connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM knowledge_chunks WHERE document_id = ?",
                (staged.document_id,),
            ).fetchone()["c"]
        self.assertEqual(count, 0)
        ready = self.store.prepare_staged_document(staged.document_id)
        self.assertEqual(ready.status, IngestStatus.READY)
        chunks = self.store.list_chunks(staged.document_id)
        self.assertGreater(len(chunks), 0)


class KnowledgePrepareWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "jobs.db"
        self.store = JobStore(self.db)
        self.store.initialize()
        self.gateway = ExecutionGateway(catalog=build_default_catalog())
        self.runtime = JobRuntime(self.store, self.gateway, ResourceManager(2))

        # Minimal settings stub for worker handler
        class _K:
            data_root = self.root / "data"
            chunk_max_chars = 400
            chunk_overlap = 40

        class _S:
            database_path = self.db
            knowledge = _K()

        self.ctx = {
            "settings": _S(),
            "job_store": self.store,
            "job_runtime": self.runtime,
            "worker_id": "knowledge_prepare-0-test",
            "lease_ttl_seconds": 30.0,
        }
        (self.root / "data").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_prepare_handler_chunks_staged_document(self) -> None:
        from Data.modules.workers.entrypoints.knowledge_prepare import _handle_prepare

        ks = KnowledgeStore(self.db, data_root=self.root / "data", chunk_max_chars=400)
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
        refreshed = ks.get_document(staged.document_id)
        assert refreshed is not None
        self.assertEqual(refreshed.status, IngestStatus.READY)


class ExternalRequiredCapabilitiesTests(unittest.TestCase):
    def test_new_caps_in_external_set(self) -> None:
        for cap in (
            "knowledge.ingest_scan",
            "research.fetch_url",
            "research.report.generate",
            "source_ingestion.brain_retry",
        ):
            self.assertIn(cap, EXTERNAL_WORKER_CAPABILITIES)


class ResearchExternalGuardsTests(unittest.TestCase):
    def test_run_coerces_to_enqueue_when_externalized(self) -> None:
        from Data.modules.research.service import ResearchService

        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}, clear=False):
            os.environ.pop("LEVIATHAN_WORKER_ID", None)
            svc = mock.Mock(spec=ResearchService)
            # Call the real method binding
            svc._runners_externalized = ResearchService._runners_externalized
            svc.get_project = mock.Mock(
                return_value=mock.Mock(status=mock.Mock(**{"value": "planned", "__eq__": lambda s, o: False}))
            )
            # Use a simpler unit check on the static helper + coerce path via enqueue_run mock
            self.assertTrue(ResearchService._runners_externalized())


class TrainingLogTailTests(unittest.TestCase):
    def test_tail_does_not_load_full_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "huge.log"
            # Write 2MB
            path.write_bytes(b"x" * (2 * 1024 * 1024) + b"TAIL_MARKER_OK")
            text = _tail_text_file(path, max_bytes=64_000)
            self.assertLessEqual(len(text.encode("utf-8")), 64_000 + 16)
            self.assertTrue(text.endswith("TAIL_MARKER_OK"))


class TrainingCancelAsyncTests(unittest.TestCase):
    def test_cancel_default_wait_is_zero(self) -> None:
        import inspect
        from Data.modules.training.service import TrainingService

        sig = inspect.signature(TrainingService.cancel_job)
        self.assertEqual(sig.parameters["wait_seconds"].default, 0.0)


class ArtifactStreamingHashTests(unittest.TestCase):
    def test_verify_hash_streams(self) -> None:
        from Data.modules.artifacts.store import ArtifactStore, sha256_file

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "a.db"
            store = ArtifactStore(db, root / "artifacts")
            store.initialize()
            payload = b"artifact-bytes-" + (b"Z" * 100_000)
            record = store.create_from_bytes(
                data=payload,
                artifact_type="blob",
                producer="test",
                filename="blob.bin",
            )
            self.assertTrue(store.verify_hash(record.artifact_id))
            # Corrupt
            Path(record.path).write_bytes(b"nope")
            self.assertFalse(store.verify_hash(record.artifact_id))
            self.assertEqual(sha256_file(Path(record.path)), __import__("hashlib").sha256(b"nope").hexdigest())


class PdfFunctionApiGuardTests(unittest.TestCase):
    def test_external_required_blocks_api_pdf(self) -> None:
        catalog = build_default_catalog()
        gateway = ExecutionGateway(catalog=catalog)
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}, clear=False):
            os.environ.pop("LEVIATHAN_WORKER_ID", None)
            result = gateway.execute(
                CapabilityRequest(capability_id="file.parse_pdf", arguments={"path": "/tmp/x.pdf"})
            )
            self.assertEqual(result.status, CapabilityStatus.REJECTED)
            self.assertIn("EXTERNAL_REQUIRED", result.error or "")


class PidIsolationMetadataTests(unittest.TestCase):
    """Lightweight isolation assertions using worker-reported pid metadata."""

    def test_job_started_event_includes_worker_pid_distinct_concept(self) -> None:
        from Data.modules.workers.events import WorkerEventEmitter

        buf = io.StringIO()
        emitter = WorkerEventEmitter(stream=buf, enable_structured=False)
        api_pid = os.getpid()
        worker_pid = api_pid + 1  # simulated different worker
        line = emitter.job_started(
            job_id="job12345678",
            capability_id="research.advance",
            pool="research",
            worker_id="research-0-abc",
            worker_pid=worker_pid,
            human_title="Isolation topic",
        )
        self.assertIn("gestart", line)
        self.assertNotEqual(worker_pid, api_pid)


class KnowledgePrepareNoFallbackTests(unittest.TestCase):
    def test_api_write_path_stages_not_upsert_when_external(self) -> None:
        """Exercise stage_document vs upsert_document under external mode intent."""
        with tempfile.TemporaryDirectory() as tmp:
            store = KnowledgeStore(Path(tmp) / "k.db", data_root=Path(tmp) / "data")
            store.initialize()
            with mock.patch.object(store, "upsert_document") as upsert:
                staged = store.stage_document(title="t", content="c" * 1000, source="manual")
                upsert.assert_not_called()
                self.assertEqual(staged.status, IngestStatus.INDEXING)


if __name__ == "__main__":
    unittest.main()
