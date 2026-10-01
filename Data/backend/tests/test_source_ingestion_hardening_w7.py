"""Wave 7 — Source ingestion hardening (P1-004, P1-005 residual, P2-005, P2-006)."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.execution import build_default_catalog
from Data.modules.execution.gateway import ExecutionGateway
from Data.modules.jobs.resources import ResourceManager
from Data.modules.jobs.runtime import JobRuntime
from Data.modules.jobs.store import JobStore
from Data.modules.knowledge import KnowledgeStore, LocalHashEmbeddingProvider
from Data.modules.research.store import ResearchStore
from Data.modules.research.types import (
    BrainStatus,
    ParseStatus,
    ResearchError,
    ResearchSource,
    SourceType,
)
from Data.modules.research.store import utc_now as research_utc_now
from Data.modules.source_ingestion.handlers.dataset_route import DatasetRouteHandler
from Data.modules.source_ingestion.pipeline import SourceIngestionPipeline
from Data.modules.source_ingestion.service import SourceIngestionService
from Data.modules.source_ingestion.settings import SourceIngestionSettings
from Data.modules.source_ingestion.store import IngestionStore
from Data.modules.source_ingestion.types import (
    DetectionConfidence,
    DetectionResult,
    IngestionPhase,
    PARSER_VERSION,
    SourceKind,
)


def _settings(**overrides) -> SourceIngestionSettings:
    base = dict(
        enabled=True,
        runner="fabric",
        max_upload_bytes=8 * 1024 * 1024,
        dataset_route_min_bytes=1024,
    )
    base.update(overrides)
    return SourceIngestionSettings(**base)


class SourceIngestionHardeningW7Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "control.db"
        self.research = ResearchStore(self.db)
        self.research.initialize()
        self.knowledge = KnowledgeStore(
            self.root / "knowledge.db",
            embedding_provider=LocalHashEmbeddingProvider(dimensions=32),
        )
        self.knowledge.initialize()
        self.job_store = JobStore(self.db)
        self.job_store.initialize()
        self.runtime = JobRuntime(
            self.job_store,
            ExecutionGateway(catalog=build_default_catalog()),
            ResourceManager(2),
        )
        self.sources = self.root / "sources"
        self.snaps = self.root / "snapshots"
        self.staging = self.root / "staging"
        for p in (self.sources, self.snaps, self.staging):
            p.mkdir()
        self.ingestion = IngestionStore(self.db)
        self.ingestion.initialize()
        self.si = SourceIngestionService(
            research_store=self.research,
            ingestion_store=self.ingestion,
            settings=_settings(),
            sources_root=self.sources,
            snapshots_root=self.snaps,
            staging_root=self.staging,
            knowledge=self.knowledge,
            job_runtime=self.runtime,
        )
        self.project = self.research.create_project(
            title="w7",
            topic="hardening",
            objective="wave7",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_p1_004_repeated_upload_does_not_accumulate_raw_copies(self) -> None:
        payload = b"identical upload bytes for orphan raw cleanup\n" * 10
        first = self.si.accept_upload(
            self.project.project_id,
            filename="notes.txt",
            stream=io.BytesIO(payload),
            content_type="text/plain",
        )
        self.assertFalse(first.get("idempotent"))
        kept = self.research.get_source(first["source_id"])
        assert kept is not None
        kept_raw = Path(str(kept.provenance["raw_path"]))
        self.assertTrue(kept_raw.is_file())

        project_dir = self.sources / self.project.project_id
        before = sorted(p.name for p in project_dir.glob("*") if p.is_file())

        second = self.si.accept_upload(
            self.project.project_id,
            filename="notes.txt",
            stream=io.BytesIO(payload),
            content_type="text/plain",
        )
        self.assertTrue(second.get("idempotent"))
        self.assertEqual(second["source_id"], first["source_id"])

        after = sorted(p.name for p in project_dir.glob("*") if p.is_file())
        self.assertEqual(before, after)
        self.assertEqual(len(after), 1)
        self.assertTrue(kept_raw.is_file())
        self.assertEqual(kept_raw.read_bytes(), payload)

        # Third upload still does not accumulate.
        third = self.si.accept_upload(
            self.project.project_id,
            filename="notes-copy.txt",
            stream=io.BytesIO(payload),
            content_type="text/plain",
        )
        self.assertTrue(third.get("idempotent"))
        final = sorted(p.name for p in project_dir.glob("*") if p.is_file())
        self.assertEqual(len(final), 1)

    def test_p1_005_retry_enqueue_before_queued_no_orphan(self) -> None:
        payload = b"retry atomicity fixture\n"
        accepted = self.si.accept_upload(
            self.project.project_id,
            filename="retry.txt",
            stream=io.BytesIO(payload),
            content_type="text/plain",
        )
        source_id = accepted["source_id"]
        self.ingestion.upsert_container(
            container_source_id=source_id,
            project_id=self.project.project_id,
            phase=IngestionPhase.FAILED,
            error="simulated",
        )
        prior = self.ingestion.get_container(source_id)
        self.assertEqual(prior["phase"], IngestionPhase.FAILED.value)

        with mock.patch.object(
            self.si,
            "_enqueue_process",
            side_effect=ResearchError(
                "SOURCE_INGESTION_UNAVAILABLE",
                "enqueue boom",
                http_status=503,
            ),
        ):
            with self.assertRaises(ResearchError) as ctx:
                self.si.retry(source_id)
        self.assertEqual(ctx.exception.code, "SOURCE_INGESTION_UNAVAILABLE")
        after = self.ingestion.get_container(source_id)
        # Must not claim QUEUED without a kernel job.
        self.assertNotEqual(after["phase"], IngestionPhase.QUEUED.value)
        self.assertEqual(after["phase"], IngestionPhase.FAILED.value)

    def test_p1_005_retry_success_sets_queued_with_job(self) -> None:
        payload = b"retry success fixture\n"
        accepted = self.si.accept_upload(
            self.project.project_id,
            filename="retry-ok.txt",
            stream=io.BytesIO(payload),
            content_type="text/plain",
        )
        source_id = accepted["source_id"]
        self.ingestion.upsert_container(
            container_source_id=source_id,
            project_id=self.project.project_id,
            phase=IngestionPhase.FAILED,
        )
        result = self.si.retry(source_id)
        self.assertEqual(result["status"], IngestionPhase.QUEUED.value)
        self.assertTrue(result.get("job_id"))
        container = self.ingestion.get_container(source_id)
        self.assertEqual(container["phase"], IngestionPhase.QUEUED.value)
        self.assertEqual(container.get("job_id"), result["job_id"])

    def test_p2_005_dataset_route_semantics(self) -> None:
        handler = DatasetRouteHandler()
        settings = _settings(dataset_route_min_bytes=1024)

        # parquet always routes
        ok, reason = handler._should_route(ext=".parquet", size=10, settings=settings)
        self.assertTrue(ok)
        self.assertEqual(reason, "parquet_always")

        # small jsonl stays structured text / dataset_candidate
        ok, reason = handler._should_route(ext=".jsonl", size=100, settings=settings)
        self.assertFalse(ok)
        self.assertEqual(reason, "small_jsonl_structured")

        # large jsonl routes (format list + size)
        ok, reason = handler._should_route(ext=".jsonl", size=2048, settings=settings)
        self.assertTrue(ok)
        self.assertEqual(reason, "format_and_size")

        # large csv / json route
        ok, reason = handler._should_route(ext=".csv", size=2048, settings=settings)
        self.assertTrue(ok)
        self.assertIn(reason, {"format_and_size", "large_tabular_or_json"})

        ok, reason = handler._should_route(ext=".json", size=2048, settings=settings)
        self.assertTrue(ok)
        self.assertIn(reason, {"format_and_size", "large_tabular_or_json"})

        # small csv does not route via size gate
        ok, reason = handler._should_route(ext=".csv", size=100, settings=settings)
        self.assertFalse(ok)
        self.assertEqual(reason, "keep_structured")

        # ingest small jsonl marks dataset_candidate + route_reason
        path = self.root / "small.jsonl"
        path.write_text('{"id":"1","text":"hi"}\n', encoding="utf-8")
        detection = DetectionResult(
            kind=SourceKind.STRUCTURED,
            extension=".jsonl",
            mime_type="application/x-ndjson",
            is_binary=False,
            is_archive=False,
            handler_hint="structured",
            confidence=DetectionConfidence.HIGH,
        )
        artifact = handler.ingest(
            path,
            detection=detection,
            relative_path="small.jsonl",
            settings=settings,
        )
        self.assertEqual(artifact.source_kind, SourceKind.STRUCTURED)
        self.assertTrue(artifact.provenance.get("dataset_candidate"))
        self.assertEqual(artifact.provenance.get("route_reason"), "small_jsonl_structured")

        # ingest parquet routes to dataset
        pq = self.root / "tiny.parquet"
        pq.write_bytes(b"PAR1" + b"\x00" * 20)
        pq_det = DetectionResult(
            kind=SourceKind.DATASET,
            extension=".parquet",
            mime_type="application/octet-stream",
            is_binary=True,
            is_archive=False,
            handler_hint="dataset",
            confidence=DetectionConfidence.HIGH,
        )
        routed = handler.ingest(
            pq,
            detection=pq_det,
            relative_path="tiny.parquet",
            settings=settings,
        )
        self.assertEqual(routed.source_kind, SourceKind.DATASET)
        self.assertEqual(routed.route_target, "dataset")
        self.assertEqual(routed.provenance.get("route_reason"), "parquet_always")

    def test_p2_006_parse_cache_registers_multi_source_provenance(self) -> None:
        text = "shared parse-cache payload for multi-source lineage\n"
        snap = self.snaps / "shared.txt"
        snap.write_text(text, encoding="utf-8")
        content_hash = "abc123contenthash"

        first = ResearchSource(
            source_id="src-first",
            project_id=self.project.project_id,
            source_type=SourceType.LOCAL_FILE,
            original_uri="upload://first.txt",
            canonical_uri=f"upload://{self.project.project_id}/{content_hash}",
            title="first.txt",
            fetched_at=research_utc_now(),
            content_hash=content_hash,
            mime_type="text/plain",
            snapshot_path=str(snap),
            parse_status=ParseStatus.OK,
            parser="plain_text",
            brain_status=BrainStatus.PENDING,
            provenance={
                "filename": "first.txt",
                "relative_path": "first.txt",
                "content_hash": content_hash,
                "caller_context": "research",
            },
            metadata={},
            created_at=research_utc_now(),
        )
        self.research.upsert_source(first)
        pipe = SourceIngestionPipeline(
            research_store=self.research,
            ingestion_store=self.ingestion,
            settings=_settings(),
            knowledge=self.knowledge,
            snapshots_root=self.snaps,
            staging_root=self.staging,
        )
        synced = pipe._brain_sync(first, text)
        self.assertEqual(synced.brain_status, BrainStatus.SYNCED)
        doc_id = synced.brain_document_id
        assert doc_id

        self.ingestion.put_parse_cache(
            content_hash=content_hash,
            parser_version=PARSER_VERSION,
            parser="plain_text",
            snapshot_path=str(snap),
            parse_status="ok",
            brain_document_id=doc_id,
            text_hash=content_hash,
        )

        second = ResearchSource(
            source_id="src-second",
            project_id=self.project.project_id,
            source_type=SourceType.LOCAL_FILE,
            original_uri="upload://second.txt",
            canonical_uri=f"upload://{self.project.project_id}/{content_hash}-b",
            title="second.txt",
            fetched_at=research_utc_now(),
            content_hash=None,  # insert without colliding on first's hash
            mime_type="text/plain",
            snapshot_path=None,
            parse_status=ParseStatus.PENDING,
            parser=None,
            brain_status=BrainStatus.PENDING,
            provenance={
                "filename": "second.txt",
                "relative_path": "second.txt",
                "content_hash": content_hash,
                "caller_context": "research",
            },
            metadata={},
            created_at=research_utc_now(),
        )
        self.research.upsert_source(second)
        # Now share content_hash for parse-cache reuse / multi-source lineage.
        second = ResearchSource(
            source_id="src-second",
            project_id=self.project.project_id,
            source_type=SourceType.LOCAL_FILE,
            original_uri="upload://second.txt",
            canonical_uri=f"upload://{self.project.project_id}/{content_hash}-b",
            title="second.txt",
            fetched_at=research_utc_now(),
            content_hash=content_hash,
            mime_type="text/plain",
            snapshot_path=None,
            parse_status=ParseStatus.PENDING,
            parser=None,
            brain_status=BrainStatus.PENDING,
            provenance={
                "filename": "second.txt",
                "relative_path": "second.txt",
                "content_hash": content_hash,
                "caller_context": "research",
            },
            metadata={},
            created_at=research_utc_now(),
        )
        self.research.save_source(second)

        cached = self.ingestion.get_parse_cache(content_hash, parser_version=PARSER_VERSION)
        assert cached
        detection = DetectionResult(
            kind=SourceKind.PLAIN_TEXT,
            extension=".txt",
            mime_type="text/plain",
            is_binary=False,
            is_archive=False,
            handler_hint="plain_text",
            confidence=DetectionConfidence.HIGH,
        )
        pipe._finalize_from_parse_cache(
            second,
            detection,
            content_hash=content_hash,
            cached=cached,
            is_child=False,
        )

        doc = self.knowledge.get_document(doc_id)
        assert doc is not None
        locations = list((doc.trust_metadata or {}).get("source_locations") or [])
        source_ids = {loc.get("source_id") for loc in locations}
        self.assertIn("src-first", source_ids)
        self.assertIn("src-second", source_ids)
        rels = {loc.get("relative_path") for loc in locations}
        self.assertIn("first.txt", rels)
        self.assertIn("second.txt", rels)


if __name__ == "__main__":
    unittest.main()
