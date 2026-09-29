"""Source Ingestion end-product closure tests — OCR, child lookup, routing, provenance."""

from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from Data.modules.execution import build_default_catalog
from Data.modules.execution.gateway import ExecutionGateway
from Data.modules.jobs.resources import ResourceManager
from Data.modules.jobs.runtime import JobRuntime
from Data.modules.jobs.states import JobState
from Data.modules.jobs.store import JobStore
from Data.modules.knowledge import KnowledgeStore
from Data.modules.research.service import ResearchService
from Data.modules.research.store import ResearchStore
from Data.modules.source_ingestion.capabilities import build_format_capabilities
from Data.modules.source_ingestion.settings import SourceIngestionSettings
from Data.modules.source_ingestion.store import IngestionStore
from Data.modules.source_ingestion.types import (
    CAPABILITY_OCR_CONTINUE,
    DatasetRouteState,
    IngestionPhase,
    ManifestMember,
    MemberOutcome,
)


def _svc(tmp: Path):
    db = tmp / "leviathan.db"
    research = ResearchStore(db)
    research.initialize()
    knowledge = KnowledgeStore(db, data_root=tmp / "knowledge")
    knowledge.initialize()
    job_store = JobStore(db)
    job_store.initialize()
    gateway = ExecutionGateway(catalog=build_default_catalog())
    runtime = JobRuntime(job_store, gateway, ResourceManager(4))
    sources = tmp / "sources"
    snaps = tmp / "snapshots"
    sources.mkdir()
    snaps.mkdir()
    service = ResearchService(
        research,
        knowledge=knowledge,
        sources_root=sources,
        snapshots_root=snaps,
        job_runtime=runtime,
    )
    if service.source_ingestion is not None:
        service.source_ingestion.settings.runner = "inprocess_test"
        service.source_ingestion.settings.archive_parse_concurrency = 2
        service.source_ingestion.settings.archive_batch_size = 100
    return service, research, knowledge, job_store, runtime


class ChildLookupScaleTests(unittest.TestCase):
    def test_indexed_child_lookup_beyond_2000(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = IngestionStore(Path(tmp) / "k.db")
            store.initialize()
            container = "c-big"
            store.upsert_container(
                container_source_id=container,
                project_id="p1",
                phase=IngestionPhase.EXPANDING,
            )
            # Seed >2000 members with unique paths
            for i in range(2500):
                store.upsert_member(
                    ManifestMember(
                        member_id=f"m{i}",
                        container_source_id=container,
                        relative_path=f"docs/file_{i:05d}.txt",
                        original_filename=f"file_{i:05d}.txt",
                        size_bytes=10,
                        outcome=MemberOutcome.PENDING,
                    )
                )
            # Bind a child far past the old 2000 limit
            target = "docs/file_02499.txt"
            store.bind_child_source(container, target, "child-2499", content_hash="abc")
            member = store.get_member(container, target)
            self.assertIsNotNone(member)
            self.assertEqual(member.child_source_id, "child-2499")
            self.assertEqual(store.get_child_source_id(container, target), "child-2499")
            # Lookup must not depend on list_sources ordering / limit
            missing = store.get_child_source_id(container, "docs/nope.txt")
            self.assertIsNone(missing)

    def test_ensure_child_idempotent_via_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service, research, knowledge, job_store, runtime = _svc(root)
            si = service.source_ingestion
            assert si is not None
            from Data.modules.research.types import ResearchSource, SourceType, ParseStatus, BrainStatus
            from Data.modules.research.store import utc_now
            from Data.modules.source_ingestion.detection import detect_source_type

            proj = service.create_project(topic="p")
            parent = ResearchSource(
                source_id="parent1",
                project_id=proj.project_id,
                source_type=SourceType.LOCAL_FILE,
                original_uri="archive://x.zip",
                canonical_uri="archive://x.zip",
                title="x.zip",
                parse_status=ParseStatus.PENDING,
                brain_status=BrainStatus.NOT_APPLICABLE,
                provenance={},
                metadata={},
                created_at=utc_now(),
            )
            research.upsert_source(parent)
            si.ingestion.upsert_container(
                container_source_id=parent.source_id,
                project_id=proj.project_id,
                phase=IngestionPhase.PARSING,
            )
            member = ManifestMember(
                member_id="m1",
                container_source_id=parent.source_id,
                relative_path="a/b.txt",
                original_filename="b.txt",
                size_bytes=3,
                content_hash="deadbeef",
            )
            si.ingestion.upsert_member(member)
            detection = detect_source_type(filename="a/b.txt", sample=b"hi\n", allow_unknown_text=True)
            raw = root / "b.txt"
            raw.write_text("hi\n", encoding="utf-8")
            pipe = si.pipeline()
            c1 = pipe._ensure_child_source(parent=parent, member=member, detection=detection, raw_path=raw)
            c2 = pipe._ensure_child_source(parent=parent, member=member, detection=detection, raw_path=raw)
            self.assertEqual(c1.source_id, c2.source_id)
            self.assertEqual(
                si.ingestion.get_child_source_id(parent.source_id, "a/b.txt"),
                c1.source_id,
            )


class OcrBackendTests(unittest.TestCase):
    def test_probe_available(self) -> None:
        from Data.modules.documents.ocr_backend import probe_document_ai_readiness

        ready = probe_document_ai_readiness()
        self.assertIn(ready.state.value, {"AVAILABLE", "DEGRADED", "UNAVAILABLE", "MISCONFIGURED"})
        self.assertEqual(ready.backend_name, "tesseract")

    def test_image_ocr_extract(self) -> None:
        from Data.modules.documents.ocr_backend import get_document_ai_backend
        from PIL import Image, ImageDraw

        backend = get_document_ai_backend()
        ready = backend.probe()
        if ready.state.value != "AVAILABLE":
            self.skipTest("tesseract unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hello.png"
            img = Image.new("RGB", (400, 80), color=(255, 255, 255))
            draw = ImageDraw.Draw(img)
            draw.text((10, 20), "HELLO OCR", fill=(0, 0, 0))
            img.save(path)
            result = backend.extract(path, mime_type="image/png")
            self.assertTrue(result.ok, result.error_message)
            self.assertGreater(len(result.text), 0)
            self.assertEqual(result.retry_class, None)

    def test_structural_unavailable_retry_class(self) -> None:
        from Data.modules.documents.ocr_backend import (
            OcrRetryClass,
            ReadinessState,
            TesseractDocumentBackend,
        )

        backend = TesseractDocumentBackend()
        with mock.patch.object(
            backend,
            "probe",
            return_value=__import__("Data.modules.documents.ocr_backend", fromlist=["OcrReadiness"]).OcrReadiness(
                state=ReadinessState.UNAVAILABLE,
                backend_name="tesseract",
                failure_reason="missing",
            ),
        ):
            with tempfile.NamedTemporaryFile(suffix=".png") as tf:
                Path(tf.name).write_bytes(b"\x89PNG\r\n\x1a\n")
                result = backend.extract(Path(tf.name))
            self.assertFalse(result.ok)
            self.assertEqual(result.retry_class, OcrRetryClass.STRUCTURAL_UNAVAILABLE)
            self.assertEqual(result.error_code, "OCR_UNAVAILABLE")


class DocumentAiHandlerTests(unittest.TestCase):
    def test_missing_file_is_terminal(self) -> None:
        from Data.modules.workers.entrypoints import document_ai as dai

        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "j.db")
            store.initialize()
            job = store.create(
                capability_id="ocr.extract",
                arguments={"source_id": "s1", "path": str(Path(tmp) / "missing.png"), "project_id": "p"},
                requested_by="test",
                worker_pool="document_ai",
                domain="document_ai",
            )
            store.transition(job.job_id, JobState.QUEUED)
            claimed = store.claim_next_queued(
                worker_id="doc-ai-test",
                lease_ttl_seconds=30.0,
                capability_ids={"ocr.extract"},
                worker_pool="document_ai",
            )
            receipt = dai._handler({"job_store": store, "worker_id": "doc-ai-test"}, claimed)
            self.assertEqual(receipt.get("error_code"), "OCR_FAILED")
            self.assertEqual(receipt.get("retry_class"), "TERMINAL")

    def test_ocr_success_enqueues_continue(self) -> None:
        from Data.modules.workers.entrypoints import document_ai as dai
        from Data.modules.documents.ocr_backend import probe_document_ai_readiness
        from PIL import Image, ImageDraw

        if probe_document_ai_readiness().state.value != "AVAILABLE":
            self.skipTest("tesseract unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service, research, knowledge, job_store, runtime = _svc(root)
            proj = service.create_project(topic="ocr-proj")
            path = root / "scan.png"
            img = Image.new("RGB", (300, 60), color=(255, 255, 255))
            ImageDraw.Draw(img).text((8, 15), "SCAN TEXT", fill=(0, 0, 0))
            img.save(path)
            from Data.modules.research.types import ResearchSource, SourceType, ParseStatus, BrainStatus
            from Data.modules.research.store import utc_now

            src = ResearchSource(
                source_id="ocr-src",
                project_id=proj.project_id,
                source_type=SourceType.LOCAL_FILE,
                original_uri=str(path),
                canonical_uri=str(path),
                title="scan.png",
                parse_status=ParseStatus.PENDING,
                brain_status=BrainStatus.PENDING,
                provenance={"raw_path": str(path)},
                metadata={},
                created_at=utc_now(),
            )
            research.upsert_source(src)
            job = job_store.create(
                capability_id="ocr.extract",
                arguments={
                    "source_id": src.source_id,
                    "project_id": proj.project_id,
                    "path": str(path),
                    "relative_path": "scan.png",
                    "mime_type": "image/png",
                },
                requested_by="test",
                worker_pool="document_ai",
                domain="document_ai",
            )
            job_store.transition(job.job_id, JobState.QUEUED)
            claimed = job_store.claim_next_queued(
                worker_id="doc-ai",
                lease_ttl_seconds=60.0,
                capability_ids={"ocr.extract"},
                worker_pool="document_ai",
            )
            receipt = dai._handler(
                {
                    "job_store": job_store,
                    "job_runtime": runtime,
                    "worker_id": "doc-ai",
                    "settings": type("S", (), {"database_path": job_store.path, "project_root": root})(),
                },
                claimed,
            )
            self.assertEqual(receipt.get("status"), "SUCCESS")
            self.assertGreater(int(receipt.get("extracted_chars") or 0), 0)
            self.assertTrue(receipt.get("ocr_continue_job_id"))
            refreshed = research.get_source(src.source_id)
            self.assertEqual(refreshed.parse_status.value, "ok")
            self.assertTrue(refreshed.snapshot_path)


class DatasetRoutingTests(unittest.TestCase):
    def test_route_success_persists_job_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service, research, knowledge, job_store, runtime = _svc(root)
            si = service.source_ingestion
            assert si is not None
            path = root / "big.parquet"
            path.write_bytes(b"PAR1" + b"\x00" * 100)

            class FakeDS:
                def enqueue_import_local(self, **kwargs):
                    return type("J", (), {"job_id": "dj1", "dataset_id": "ds1"})()

            si.dataset_service = FakeDS()
            from Data.modules.research.types import ResearchSource, SourceType, ParseStatus, BrainStatus
            from Data.modules.research.store import utc_now
            from Data.modules.source_ingestion.types import NormalizedArtifact, ContentRef, SourceKind, PARSER_VERSION

            proj = service.create_project(topic="ds")
            src = ResearchSource(
                source_id="ds-src",
                project_id=proj.project_id,
                source_type=SourceType.LOCAL_FILE,
                original_uri=str(path),
                canonical_uri=str(path),
                title="big.parquet",
                parse_status=ParseStatus.PENDING,
                brain_status=BrainStatus.NOT_APPLICABLE,
                provenance={},
                metadata={},
                created_at=utc_now(),
            )
            research.upsert_source(src)
            art = NormalizedArtifact(
                source_kind=SourceKind.DATASET,
                title="big.parquet",
                relative_path="big.parquet",
                mime_type="application/octet-stream",
                parser="dataset_route",
                parser_version=PARSER_VERSION,
                content_hash="x",
                content=ContentRef(text=""),
                outcome=MemberOutcome.ROUTED,
                route_target="dataset",
                provenance={"raw_path": str(path)},
            )
            route = si.pipeline()._route_dataset(src, art)
            self.assertEqual(route["state"], DatasetRouteState.ROUTED.value)
            self.assertEqual(route["dataset_job_id"], "dj1")
            saved = research.get_source(src.source_id)
            self.assertEqual(saved.provenance.get("dataset_route", {}).get("dataset_job_id"), "dj1")

    def test_route_unavailable_not_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service, research, knowledge, job_store, runtime = _svc(root)
            si = service.source_ingestion
            assert si is not None
            si.dataset_service = None
            from Data.modules.research.types import ResearchSource, SourceType, ParseStatus, BrainStatus
            from Data.modules.research.store import utc_now
            from Data.modules.source_ingestion.types import NormalizedArtifact, ContentRef, SourceKind, PARSER_VERSION

            src = ResearchSource(
                source_id="ds2",
                project_id="p",
                source_type=SourceType.LOCAL_FILE,
                original_uri="x",
                canonical_uri="x",
                title="x.parquet",
                parse_status=ParseStatus.PENDING,
                brain_status=BrainStatus.NOT_APPLICABLE,
                provenance={},
                metadata={},
                created_at=utc_now(),
            )
            art = NormalizedArtifact(
                source_kind=SourceKind.DATASET,
                title="x.parquet",
                relative_path="x.parquet",
                mime_type="application/octet-stream",
                parser="dataset_route",
                parser_version=PARSER_VERSION,
                content_hash="x",
                content=ContentRef(text=""),
                outcome=MemberOutcome.ROUTED,
                route_target="dataset",
                provenance={"raw_path": str(root / "x.parquet")},
            )
            route = si.pipeline()._route_dataset(src, art)
            self.assertEqual(route["state"], DatasetRouteState.ROUTE_UNAVAILABLE.value)
            self.assertEqual(route["error_code"], "DATASET_ROUTE_UNAVAILABLE")

    def test_route_exception_persists_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service, research, knowledge, job_store, runtime = _svc(root)
            si = service.source_ingestion
            assert si is not None

            class Boom:
                def enqueue_import_local(self, **kwargs):
                    raise RuntimeError("boom")

            si.dataset_service = Boom()
            from Data.modules.research.types import ResearchSource, SourceType, ParseStatus, BrainStatus
            from Data.modules.research.store import utc_now
            from Data.modules.source_ingestion.types import NormalizedArtifact, ContentRef, SourceKind, PARSER_VERSION

            path = root / "z.parquet"
            path.write_bytes(b"x")
            proj = service.create_project(topic="ds3")
            src = ResearchSource(
                source_id="ds3",
                project_id=proj.project_id,
                source_type=SourceType.LOCAL_FILE,
                original_uri=str(path),
                canonical_uri=str(path),
                title="z.parquet",
                parse_status=ParseStatus.PENDING,
                brain_status=BrainStatus.NOT_APPLICABLE,
                provenance={},
                metadata={},
                created_at=utc_now(),
            )
            research.upsert_source(src)
            art = NormalizedArtifact(
                source_kind=SourceKind.DATASET,
                title="z.parquet",
                relative_path="z.parquet",
                mime_type="application/octet-stream",
                parser="dataset_route",
                parser_version=PARSER_VERSION,
                content_hash="x",
                content=ContentRef(text=""),
                outcome=MemberOutcome.ROUTED,
                route_target="dataset",
                provenance={"raw_path": str(path)},
            )
            route = si.pipeline()._route_dataset(src, art)
            self.assertEqual(route["state"], DatasetRouteState.ROUTE_FAILED.value)


class FormatCapabilityTests(unittest.TestCase):
    def test_matrix_reports_7z_rar_and_ocr(self) -> None:
        caps = build_format_capabilities(SourceIngestionSettings(allow_7z=False, allow_rar=False))
        self.assertTrue(caps["formats"][".txt"]["supported"])
        self.assertTrue(caps["formats"][".7z"]["intentionally_unsupported"])
        self.assertTrue(caps["formats"][".rar"]["intentionally_unsupported"])
        self.assertIn("ocr_readiness", caps)


class LegacyGateTests(unittest.TestCase):
    def test_standalone_requires_unsafe_gate(self) -> None:
        import importlib.util
        import os

        script = Path(__file__).resolve().parents[3] / "scripts" / "source_ingestion_worker.py"
        spec = importlib.util.spec_from_file_location("si_worker_script", script)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        with mock.patch.dict(
            os.environ,
            {
                "LEVIATHAN_SOURCE_INGESTION_RUNNER": "standalone_legacy",
                "LEVIATHAN_ALLOW_STANDALONE_SOURCE_INGESTION": "0",
                "LEVIATHAN_WORKERS_ENABLED": "0",
                "LEVIATHAN_WORKERS_SUPERVISOR": "0",
            },
            clear=False,
        ):
            code = mod._guarded_main([])
            self.assertEqual(code, 2)


class BrainProvenanceTests(unittest.TestCase):
    def test_multi_location_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service, research, knowledge, job_store, runtime = _svc(root)
            si = service.source_ingestion
            assert si is not None
            from Data.modules.research.types import ResearchSource, SourceType, ParseStatus, BrainStatus
            from Data.modules.research.store import utc_now

            text = "shared content body for dedupe"
            content_hash = __import__("Data.modules.common.hashing", fromlist=["sha256_text"]).sha256_text(text)
            proj = service.create_project(topic="dedupe")
            for i, rel in enumerate(["a/foo.txt", "b/foo.txt"]):
                src = ResearchSource(
                    source_id=f"s{i}",
                    project_id=proj.project_id,
                    source_type=SourceType.LOCAL_FILE,
                    original_uri=rel,
                    canonical_uri=rel,
                    title=Path(rel).name,
                    content_hash=content_hash,
                    parse_status=ParseStatus.OK,
                    brain_status=BrainStatus.PENDING,
                    provenance={
                        "container_source_id": f"c{i}",
                        "relative_path": rel,
                        "original_filename": Path(rel).name,
                        "archive_filename": f"arc{i}.zip",
                    },
                    metadata={},
                    created_at=utc_now(),
                )
                research.upsert_source(src)
                synced = si.pipeline()._brain_sync(src, text)
                self.assertEqual(synced.brain_status, BrainStatus.SYNCED)
            doc = knowledge.get_document(f"research-upload:{content_hash}")
            self.assertIsNotNone(doc)
            locs = (doc.trust_metadata or {}).get("source_locations") or []
            self.assertGreaterEqual(len(locs), 2)


class DbCommitBrainSyncTests(unittest.TestCase):
    def test_commit_brain_sync_applies_with_canonical_upsert(self) -> None:
        from Data.modules.db_commit.handlers.source_ingestion import _commit_brain_sync
        from Data.modules.db_commit.types import CommitIntent, CommitReceiptStatus
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            store = IngestionStore(db)
            store.initialize()
            store.upsert_container(
                container_source_id="src1",
                project_id="p1",
                phase=IngestionPhase.BRAIN_SYNCING,
            )
            intent = CommitIntent(
                commit_id="c1",
                idempotency_key="k1",
                operation="source_ingestion.commit_brain_sync",
                domain="source_ingestion",
            )
            receipt = _commit_brain_sync(
                intent,
                {"source_id": "src1", "sync": {"ok": True}, "project_id": "p1"},
                db,
                SimpleNamespace(),
            )
            self.assertEqual(receipt.status, CommitReceiptStatus.APPLIED.value)
            container = store.get_container("src1")
            self.assertTrue(container["progress"].get("brain_sync_aux", {}).get("ok"))


class CapabilityCatalogTests(unittest.TestCase):
    def test_ocr_continue_registered(self) -> None:
        catalog = build_default_catalog()
        ids = {c.id for c in catalog.list()}
        self.assertIn(CAPABILITY_OCR_CONTINUE, ids)
        self.assertIn("ocr.extract", ids)


class IntegrationPlainTextTests(unittest.TestCase):
    def test_upload_to_brain_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service, research, knowledge, job_store, runtime = _svc(root)
            proj = service.create_project(topic="plain")
            result = service.upload_source(
                proj.project_id,
                filename="note.txt",
                stream=io.BytesIO(b"hello leviathan world\n"),
                content_type="text/plain",
            )
            source_id = result["source"]["source_id"]
            # Drain inprocess
            for _ in range(5):
                service.source_ingestion.process_next()
            status = service.get_ingestion_status(proj.project_id, source_id)
            phase = (status.get("container") or {}).get("phase") or status["progress"].get("status")
            self.assertIn(phase, {"completed", "partial", IngestionPhase.COMPLETED.value})
            src = research.get_source(source_id)
            self.assertEqual(src.brain_status.value, "synced")
            self.assertIsNotNone(src.brain_document_id)


class IntegrationArchiveParallelTests(unittest.TestCase):
    def test_large_archive_child_binding_and_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service, research, knowledge, job_store, runtime = _svc(root)
            si = service.source_ingestion
            assert si is not None
            si.settings.max_member_count = 10_000
            members = {f"f/{i:04d}.txt": f"content-{i}\n".encode() for i in range(120)}
            # Duplicate content for dedupe
            members["f/dup_a.txt"] = b"same-bytes\n"
            members["f/dup_b.txt"] = b"same-bytes\n"
            zpath = root / "big.zip"
            with zipfile.ZipFile(zpath, "w") as zf:
                for name, data in members.items():
                    zf.writestr(name, data)
            proj = service.create_project(topic="arch")
            result = service.upload_source(
                proj.project_id,
                filename="big.zip",
                stream=io.BytesIO(zpath.read_bytes()),
                content_type="application/zip",
            )
            source_id = result["source"]["source_id"]
            for _ in range(20):
                done = service.source_ingestion.process_next()
                if done is None:
                    break
            counts = si.ingestion.count_members(source_id)
            self.assertGreater(int(counts.get("total") or 0), 100)
            # Every successful member should have child_source_id bound
            sample = si.ingestion.list_members(source_id, limit=50)
            bound = [m for m in sample if m.child_source_id and m.outcome in {MemberOutcome.SUCCESS, MemberOutcome.DUPLICATE}]
            self.assertTrue(bound)
            # Direct lookup works
            m0 = si.ingestion.get_member(source_id, "f/0000.txt")
            self.assertIsNotNone(m0)
            self.assertTrue(m0.child_source_id)


class IntegrationOcrScannedPdfTests(unittest.TestCase):
    def test_scanned_pdf_ocr_to_brain(self) -> None:
        from Data.modules.documents.ocr_backend import probe_document_ai_readiness
        from PIL import Image, ImageDraw
        import fitz

        if probe_document_ai_readiness().state.value != "AVAILABLE":
            self.skipTest("tesseract unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service, research, knowledge, job_store, runtime = _svc(root)
            # Build a scanned PDF from an image (no native text)
            img = Image.new("RGB", (500, 120), color=(255, 255, 255))
            ImageDraw.Draw(img).text((20, 40), "SCANNED DOCUMENT BODY", fill=(0, 0, 0))
            img_path = root / "page.png"
            img.save(img_path)
            pdf_path = root / "scan.pdf"
            doc = fitz.open()
            page = doc.new_page(width=500, height=120)
            page.insert_image(page.rect, filename=str(img_path))
            doc.save(str(pdf_path))
            doc.close()
            proj = service.create_project(topic="scan")
            result = service.upload_source(
                proj.project_id,
                filename="scan.pdf",
                stream=io.BytesIO(pdf_path.read_bytes()),
                content_type="application/pdf",
            )
            source_id = result["source"]["source_id"]
            # Process SI then OCR then continue
            for _ in range(30):
                # Prefer draining SI then document_ai via direct handler when queued
                si_job = service.source_ingestion.process_next()
                ocr_jobs = [
                    j
                    for j in job_store.list(limit=50)
                    if j.capability_id.startswith("ocr.") or j.capability_id.startswith("document_ai.")
                ]
                for j in ocr_jobs:
                    if j.state == JobState.QUEUED:
                        claimed = job_store.claim_next_queued(
                            worker_id="doc-ai",
                            lease_ttl_seconds=120.0,
                            capability_ids={"ocr.extract", "document_ai.ocr"},
                            worker_pool="document_ai",
                        )
                        if claimed:
                            from Data.modules.workers.entrypoints import document_ai as dai

                            dai._handler(
                                {
                                    "job_store": job_store,
                                    "job_runtime": runtime,
                                    "worker_id": "doc-ai",
                                    "settings": None,
                                },
                                claimed,
                            )
                cont = [
                    j
                    for j in job_store.list(limit=50)
                    if j.capability_id == CAPABILITY_OCR_CONTINUE and j.state == JobState.QUEUED
                ]
                if cont or si_job:
                    continue
                src = research.get_source(source_id)
                if src and src.brain_status.value == "synced":
                    break
            src = research.get_source(source_id)
            # Either completed via OCR continuation or still OCR_PENDING if PDF had extractable text
            if src.brain_status.value != "synced":
                # Force OCR path: enqueue + run
                receipt = service.source_ingestion.enqueue_ocr(
                    source_id=source_id,
                    project_id=proj.project_id,
                    path=str(pdf_path),
                    relative_path="scan.pdf",
                    mime_type="application/pdf",
                )
                self.assertTrue(receipt.get("queued"), receipt)
                claimed = None
                for j in job_store.list(limit=50):
                    if j.capability_id == "ocr.extract" and j.state == JobState.QUEUED:
                        claimed = job_store.claim_next_queued(
                            worker_id="doc-ai",
                            lease_ttl_seconds=120.0,
                            capability_ids={"ocr.extract"},
                            worker_pool="document_ai",
                        )
                        break
                    if j.capability_id == "ocr.extract" and j.state == JobState.RUNNING:
                        claimed = j
                        break
                if claimed is None:
                    claimed = job_store.claim_next_queued(
                        worker_id="doc-ai",
                        lease_ttl_seconds=120.0,
                        capability_ids={"ocr.extract"},
                        worker_pool="document_ai",
                    )
                # If OCR already completed in the earlier drain loop, accept that.
                if claimed is None:
                    done = [
                        j
                        for j in job_store.list(limit=50)
                        if j.capability_id == "ocr.extract" and j.state == JobState.COMPLETED
                    ]
                    self.assertTrue(done, "expected OCR job")
                    for _ in range(10):
                        service.source_ingestion.process_next()
                    src = research.get_source(source_id)
                else:
                    from Data.modules.workers.entrypoints import document_ai as dai

                    out = dai._handler(
                        {
                            "job_store": job_store,
                            "job_runtime": runtime,
                            "worker_id": "doc-ai",
                            "settings": type(
                                "S", (), {"database_path": job_store.path, "project_root": root}
                            )(),
                        },
                        claimed,
                    )
                    self.assertEqual(out.get("status"), "SUCCESS", out)
                    for _ in range(10):
                        service.source_ingestion.process_next()
                    src = research.get_source(source_id)
            self.assertEqual(src.brain_status.value, "synced")
            self.assertIsNotNone(src.brain_document_id)
            # OCR provenance may live on the source after document_ai completion
            self.assertTrue(
                "ocr" in (src.provenance or {})
                or (src.parser or "") == "ocr"
                or src.snapshot_path
            )
            doc = knowledge.get_document(src.brain_document_id)
            self.assertIsNotNone(doc)
            self.assertGreater(len(doc.content or ""), 0)


if __name__ == "__main__":
    unittest.main()
