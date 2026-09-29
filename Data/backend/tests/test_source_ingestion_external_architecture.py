"""Architecture regression: source ingestion / OCR must stay externally owned.

Protects against reintroducing ResearchService/API → pipeline.process_source()
or SourceIngestionService.process_next() under normal production execution.
"""

from __future__ import annotations

import ast
import inspect
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.execution import build_default_catalog
from Data.modules.execution.workload import (
    ExecutionWorkloadClass,
    api_may_execute_inline,
    classify_capability,
)
from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES, JobRuntime
from Data.modules.jobs.store import JobStore
from Data.modules.jobs.resources import ResourceManager
from Data.modules.execution.gateway import ExecutionGateway
from Data.modules.source_ingestion.execution_gate import (
    allow_inprocess_execution,
    normalize_runner_value,
)
from Data.modules.workers.pools import pool_for_capability

REPO_DATA = Path(__file__).resolve().parents[2]
RESEARCH_SERVICE = REPO_DATA / "modules" / "research" / "service.py"
RESEARCH_ROUTES = REPO_DATA / "backend" / "routes" / "research.py"


def _method_calls_attr(tree: ast.AST, method_name: str, attr_names: set[str]) -> list[str]:
    """Return attribute call names found inside a ClassDef method body."""
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "ResearchService":
            continue
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if item.name != method_name:
                continue
            for child in ast.walk(item):
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                    if child.func.attr in attr_names:
                        hits.append(child.func.attr)
    return hits


class SourceIngestionExternalOwnershipTests(unittest.TestCase):
    def test_capabilities_classify_external_required(self) -> None:
        for cap in (
            "source_ingestion.process",
            "source_ingestion.brain_retry",
            "ocr.extract",
            "document_ai.ocr",
            "file.parse_pdf",
        ):
            self.assertEqual(
                classify_capability(cap),
                ExecutionWorkloadClass.EXTERNAL_REQUIRED,
                msg=cap,
            )
            self.assertFalse(api_may_execute_inline(cap), msg=cap)

    def test_pool_routing_exact(self) -> None:
        self.assertEqual(pool_for_capability("source_ingestion.process"), "source_ingestion")
        self.assertEqual(pool_for_capability("source_ingestion.brain_retry"), "source_ingestion")
        self.assertEqual(pool_for_capability("ocr.extract"), "document_ai")
        self.assertEqual(pool_for_capability("document_ai.ocr"), "document_ai")
        self.assertNotEqual(pool_for_capability("source_ingestion.process"), "general")
        self.assertNotEqual(pool_for_capability("ocr.extract"), "general")

    def test_api_job_runtime_cannot_steal_si_or_ocr(self) -> None:
        for cap in (
            "source_ingestion.process",
            "source_ingestion.brain_retry",
            "ocr.extract",
            "document_ai.ocr",
        ):
            self.assertIn(cap, EXTERNAL_WORKER_CAPABILITIES)

        catalog = build_default_catalog()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = JobStore(Path(tmp.name) / "jobs.db")
        store.initialize()
        runtime = JobRuntime(store, ExecutionGateway(catalog=catalog), ResourceManager(2))
        for cap, pool in (
            ("source_ingestion.process", "source_ingestion"),
            ("ocr.extract", "document_ai"),
        ):
            runtime.enqueue(
                capability_id=cap,
                arguments={"source_id": "s1", "path": "/tmp/x"},
                requested_by="test",
                worker_pool=pool,
                domain="test",
            )
        stolen = runtime.process_next()
        self.assertIsNone(stolen)

    def test_catalog_registers_ocr_caps(self) -> None:
        ids = {c.id for c in build_default_catalog().list()}
        self.assertIn("ocr.extract", ids)
        self.assertIn("document_ai.ocr", ids)
        self.assertIn("source_ingestion.process", ids)

    def test_inprocess_alias_fails_closed_without_allow_gate(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            # Clear pytest detection for this assertion by forcing allow=False path
            with mock.patch(
                "Data.modules.source_ingestion.execution_gate.pytest_session_active",
                return_value=False,
            ):
                self.assertEqual(normalize_runner_value("inprocess"), "fabric")
                self.assertEqual(normalize_runner_value("thread"), "fabric")
                self.assertEqual(normalize_runner_value("inprocess_test"), "inprocess_test")
                self.assertFalse(allow_inprocess_execution(None))

    def test_research_upload_source_ast_no_direct_heavy_calls(self) -> None:
        """upload_source must not directly call process_next / process_source.

        Drain is allowed only via the named TEST-ONLY helper.
        """
        tree = ast.parse(RESEARCH_SERVICE.read_text(encoding="utf-8"))
        direct = _method_calls_attr(
            tree, "upload_source", {"process_next", "process_source", "retry_brain_only"}
        )
        self.assertEqual(
            direct,
            [],
            msg=f"upload_source must not call heavy SI internals directly: {direct}",
        )
        # Helper exists and is the sole drain path
        helper_hits = _method_calls_attr(
            tree,
            "_maybe_drain_source_ingestion_inprocess",
            {"process_next", "process_source"},
        )
        self.assertTrue(helper_hits, msg="test-only drain helper must invoke SI internals")

    def test_research_retry_brain_ast_no_inline_sync_fallback(self) -> None:
        tree = ast.parse(RESEARCH_SERVICE.read_text(encoding="utf-8"))
        # retry_ingestion_brain must enqueue (or gated retry_brain), never retry_brain_sync
        hits = _method_calls_attr(
            tree, "retry_ingestion_brain", {"retry_brain_sync", "process_next", "process_source"}
        )
        self.assertEqual(hits, [])

    def test_research_routes_do_not_import_pipeline(self) -> None:
        tree = ast.parse(RESEARCH_ROUTES.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn("source_ingestion.pipeline", node.module)
                self.assertNotIn("source_ingestion.handlers", node.module)

    def test_production_upload_enqueues_without_inline_parse(self) -> None:
        from Data.modules.knowledge import KnowledgeStore
        from Data.modules.research.service import ResearchService
        from Data.modules.research.store import ResearchStore

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        db = root / "lev.db"
        research = ResearchStore(db)
        research.initialize()
        knowledge = KnowledgeStore(db, data_root=root / "knowledge")
        knowledge.initialize()
        job_store = JobStore(db)
        job_store.initialize()
        catalog = build_default_catalog()
        runtime = JobRuntime(job_store, ExecutionGateway(catalog=catalog), ResourceManager(2))
        sources = root / "sources"
        snaps = root / "snapshots"
        sources.mkdir()
        snaps.mkdir()

        with mock.patch.dict(
            os.environ,
            {
                "LEVIATHAN_SOURCE_INGESTION_RUNNER": "fabric",
                "LEVIATHAN_WORKERS_EXTERNALIZE_API": "1",
                "LEVIATHAN_SOURCE_INGESTION_ALLOW_INPROCESS_TEST": "0",
            },
            clear=False,
        ):
            with mock.patch(
                "Data.modules.source_ingestion.execution_gate.pytest_session_active",
                return_value=False,
            ):
                service = ResearchService(
                    research,
                    knowledge=knowledge,
                    sources_root=sources,
                    snapshots_root=snaps,
                    job_runtime=runtime,
                )
                self.assertIsNotNone(service.source_ingestion)
                service.source_ingestion.settings.runner = "fabric"
                project = service.create_project(title="ext", topic="boundary")
                result = service.upload_source(
                    project.project_id,
                    filename="hello.txt",
                    stream=__import__("io").BytesIO(b"hello fabric\n"),
                )
                self.assertEqual(result["status"], "queued")
                self.assertTrue(result.get("job_id"))
                # Must not have parsed inline
                src = research.get_source(result["source_id"])
                self.assertEqual(src.parse_status.value, "pending")
                # Job sits on SI pool — API runtime cannot steal it
                self.assertIsNone(runtime.process_next())
                queued = [
                    j
                    for j in job_store.list(limit=20)
                    if j.capability_id == "source_ingestion.process"
                ]
                self.assertEqual(len(queued), 1)
                self.assertEqual(queued[0].worker_pool, "source_ingestion")

    def test_brain_retry_enqueues_only(self) -> None:
        from Data.modules.knowledge import KnowledgeStore
        from Data.modules.research.service import ResearchService
        from Data.modules.research.store import ResearchStore
        from Data.modules.research.types import BrainStatus, ParseStatus, ResearchSource, SourceType
        from Data.modules.research.store import utc_now

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        db = root / "lev.db"
        research = ResearchStore(db)
        research.initialize()
        knowledge = KnowledgeStore(db, data_root=root / "knowledge")
        knowledge.initialize()
        job_store = JobStore(db)
        job_store.initialize()
        catalog = build_default_catalog()
        runtime = JobRuntime(job_store, ExecutionGateway(catalog=catalog), ResourceManager(2))
        sources = root / "sources"
        snaps = root / "snapshots"
        sources.mkdir()
        snaps.mkdir()

        with mock.patch(
            "Data.modules.source_ingestion.execution_gate.pytest_session_active",
            return_value=False,
        ):
            service = ResearchService(
                research,
                knowledge=knowledge,
                sources_root=sources,
                snapshots_root=snaps,
                job_runtime=runtime,
            )
            service.source_ingestion.settings.runner = "fabric"
            project = service.create_project(title="br", topic="brain")
            snap = snaps / "s.txt"
            snap.write_text("brain body", encoding="utf-8")
            source = ResearchSource(
                source_id="src-brain-1",
                project_id=project.project_id,
                source_type=SourceType.LOCAL_FILE,
                original_uri="upload://s.txt",
                canonical_uri="upload://s.txt",
                title="s.txt",
                fetched_at=utc_now(),
                content_hash="abc",
                mime_type="text/plain",
                snapshot_path=str(snap),
                parse_status=ParseStatus.OK,
                parser="plain_text",
                brain_status=BrainStatus.FAILED,
                provenance={"raw_path": str(snap)},
                metadata={},
                created_at=utc_now(),
            )
            research.upsert_source(source)
            out = service.retry_ingestion_brain(project.project_id, source.source_id)
            self.assertTrue(out.get("queued"))
            self.assertEqual(out.get("status"), "QUEUED")
            caps = {j.capability_id for j in job_store.list(limit=20)}
            self.assertIn("source_ingestion.brain_retry", caps)

    def test_document_ai_handler_fails_closed_no_fake_ocr(self) -> None:
        from Data.modules.workers.entrypoints import document_ai as dai
        from Data.modules.jobs.states import JobState
        from Data.modules.documents.ocr_backend import ReadinessState, OcrReadiness
        from unittest import mock

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = JobStore(Path(tmp.name) / "j.db")
        store.initialize()
        job = store.create(
            capability_id="ocr.extract",
            arguments={"source_id": "s1", "path": "/tmp/x.pdf", "project_id": "p"},
            requested_by="test",
            worker_pool="document_ai",
            domain="document_ai",
            domain_entity_type="source",
            domain_entity_id="s1",
        )
        store.transition(job.job_id, JobState.QUEUED)
        claimed = store.claim_next_queued(
            worker_id="doc-ai-test",
            lease_ttl_seconds=30.0,
            capability_ids={"ocr.extract"},
            worker_pool="document_ai",
        )
        self.assertIsNotNone(claimed)
        with mock.patch(
            "Data.modules.documents.ocr_backend.get_document_ai_backend"
        ) as get_backend:
            backend = mock.Mock()
            backend.name.return_value = "missing"
            backend.probe.return_value = OcrReadiness(
                state=ReadinessState.UNAVAILABLE,
                backend_name="missing",
                failure_reason="OCR backend missing",
            )
            get_backend.return_value = backend
            receipt = dai._handler({"job_store": store, "worker_id": "doc-ai-test"}, claimed)
        self.assertEqual(receipt.get("extracted_chars"), 0)
        self.assertIsNone(receipt.get("extracted_text"))
        self.assertIn(receipt.get("error_code"), {"OCR_UNAVAILABLE", "DOCUMENT_AI_UNAVAILABLE"})
        refreshed = store.get(claimed.job_id)
        self.assertEqual(refreshed.state, JobState.FAILED)
        self.assertFalse(receipt.get("truth", {}).get("fabricated"))


class SourceIngestionOcrDelegationTests(unittest.TestCase):
    def test_scanned_pdf_marks_ocr_required_and_enqueues_child(self) -> None:
        from Data.modules.source_ingestion.handlers.documents import DocumentHandler
        from Data.modules.source_ingestion.types import DetectionResult, SourceKind, DetectionConfidence
        from Data.modules.source_ingestion.settings import SourceIngestionSettings
        import io

        # Minimal PDF with no extractable text is hard; unit-test the error path via mock.
        handler = DocumentHandler()
        with mock.patch(
            "Data.modules.documents.extraction.extract_document"
        ) as extract:
            fake = mock.Mock()
            fake.pages = [{"page_number": 1, "text": ""}]
            fake.unsupported = ["ocr_scan"]
            fake.backend = "pdf"
            fake.content_sha256 = "deadbeef"
            extract.return_value = fake
            # Also stub legacy path to return empty
            with mock.patch(
                "Data.modules.source_ingestion.handlers.documents.DocumentHandler._ingest_pdf_legacy"
            ) as legacy:
                from Data.modules.source_ingestion.types import (
                    NormalizedArtifact,
                    MemberOutcome,
                    ContentRef,
                    ERROR_OCR_REQUIRED,
                    PARSER_VERSION,
                )

                legacy.return_value = NormalizedArtifact(
                    source_kind=SourceKind.DOCUMENT,
                    title="scan.pdf",
                    relative_path="scan.pdf",
                    mime_type="application/pdf",
                    parser="pdf",
                    parser_version=PARSER_VERSION,
                    content_hash="deadbeef",
                    content=ContentRef(text=""),
                    outcome=MemberOutcome.FAILED,
                    error_code=ERROR_OCR_REQUIRED,
                    skip_reason="PDF has no extractable text; OCR/document_ai required",
                    unsupported_features=["ocr"],
                    provenance={"pdf_class": "scanned_or_image_only", "ocr_status": "required"},
                )
                tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
                tmp.write(b"%PDF-1.4 empty")
                tmp.close()
                path = Path(tmp.name)
                try:
                    detection = DetectionResult(
                        kind=SourceKind.DOCUMENT,
                        mime_type="application/pdf",
                        extension=".pdf",
                        confidence=DetectionConfidence.HIGH,
                    )
                    art = handler.ingest(
                        path,
                        detection=detection,
                        relative_path="scan.pdf",
                        settings=SourceIngestionSettings(),
                    )
                    self.assertEqual(art.error_code, ERROR_OCR_REQUIRED)
                    self.assertEqual(art.content.read_text(), "")
                    self.assertIn("ocr", art.unsupported_features)
                finally:
                    path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
