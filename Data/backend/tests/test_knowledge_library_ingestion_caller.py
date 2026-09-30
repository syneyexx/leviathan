"""Knowledge Library as first-class SourceIngestion caller (Wave 2)."""

from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from Data.modules.execution import build_default_catalog
from Data.modules.execution.gateway import ExecutionGateway
from Data.modules.jobs.resources import ResourceManager
from Data.modules.jobs.runtime import JobRuntime
from Data.modules.jobs.store import JobStore
from Data.modules.knowledge import KnowledgeStore, LocalHashEmbeddingProvider
from Data.modules.research.store import ResearchStore
from Data.modules.source_ingestion.service import SourceIngestionService
from Data.modules.source_ingestion.settings import SourceIngestionSettings
from Data.modules.source_ingestion.store import IngestionStore
from Data.modules.source_ingestion.types import (
    CALLER_CONTEXT_KNOWLEDGE_LIBRARY,
    KNOWLEDGE_LIBRARY_OWNER_PROJECT_ID,
)


class KnowledgeLibraryCallerTests(unittest.TestCase):
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
        job_store = JobStore(self.db)
        job_store.initialize()
        runtime = JobRuntime(
            job_store,
            ExecutionGateway(catalog=build_default_catalog()),
            ResourceManager(2),
        )
        sources = self.root / "sources"
        snaps = self.root / "snapshots"
        staging = self.root / "staging"
        sources.mkdir()
        snaps.mkdir()
        staging.mkdir()
        ingestion = IngestionStore(self.db)
        ingestion.initialize()
        settings = SourceIngestionSettings(
            enabled=True,
            runner="fabric",
            max_upload_bytes=8 * 1024 * 1024,
        )
        self.si = SourceIngestionService(
            research_store=self.research,
            ingestion_store=ingestion,
            settings=settings,
            sources_root=sources,
            snapshots_root=snaps,
            staging_root=staging,
            knowledge=self.knowledge,
            job_runtime=runtime,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_ensure_owner_is_durable_singleton(self) -> None:
        a = self.si.ensure_knowledge_library_owner()
        b = self.si.ensure_knowledge_library_owner()
        self.assertEqual(a, KNOWLEDGE_LIBRARY_OWNER_PROJECT_ID)
        self.assertEqual(a, b)
        project = self.research.get_project(a)
        self.assertIsNotNone(project)
        self.assertEqual(project.title, "Knowledge Library")

    def test_text_upload_uses_caller_context_and_does_not_use_file_text(self) -> None:
        payload = b"Leviathan knowledge library upload fixture.\n" * 20
        result = self.si.accept_knowledge_library_upload(
            filename="notes.txt",
            stream=io.BytesIO(payload),
            content_type="text/plain",
        )
        self.assertEqual(result["caller_context"], CALLER_CONTEXT_KNOWLEDGE_LIBRARY)
        self.assertEqual(result["owner_project_id"], KNOWLEDGE_LIBRARY_OWNER_PROJECT_ID)
        self.assertFalse(result.get("idempotent"))
        source = self.research.get_source(result["source_id"])
        assert source is not None
        self.assertEqual(source.project_id, KNOWLEDGE_LIBRARY_OWNER_PROJECT_ID)
        self.assertEqual(source.provenance.get("caller_context"), CALLER_CONTEXT_KNOWLEDGE_LIBRARY)
        self.assertEqual(int(source.provenance.get("size_bytes")), len(payload))
        # Raw artifact stored under owner project — not parsed in the upload request.
        raw = Path(source.provenance["raw_path"])
        self.assertTrue(raw.is_file())
        self.assertEqual(raw.read_bytes(), payload)

    def test_duplicate_upload_is_idempotent(self) -> None:
        payload = b"same bytes twice\n"
        first = self.si.accept_knowledge_library_upload(
            filename="dup.txt",
            stream=io.BytesIO(payload),
            content_type="text/plain",
        )
        second = self.si.accept_knowledge_library_upload(
            filename="dup.txt",
            stream=io.BytesIO(payload),
            content_type="text/plain",
        )
        self.assertTrue(second.get("idempotent"))
        self.assertEqual(first["source_id"], second["source_id"])

    def test_zip_upload_is_accepted_as_archive_without_browser_extract(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("inner/hello.txt", "hello from archive\n")
        raw = buf.getvalue()
        result = self.si.accept_knowledge_library_upload(
            filename="bundle.zip",
            stream=io.BytesIO(raw),
            content_type="application/zip",
        )
        self.assertEqual(result["source_type"], "archive")
        source = self.research.get_source(result["source_id"])
        assert source is not None
        self.assertTrue(source.provenance.get("is_archive") or source.metadata.get("is_container"))

    def test_recent_ingestions_for_library_owner(self) -> None:
        self.si.accept_knowledge_library_upload(
            filename="a.txt",
            stream=io.BytesIO(b"aaa"),
            content_type="text/plain",
        )
        self.si.accept_knowledge_library_upload(
            filename="b.txt",
            stream=io.BytesIO(b"bbb"),
            content_type="text/plain",
        )
        recent = self.si.list_recent_ingestions(
            caller_context=CALLER_CONTEXT_KNOWLEDGE_LIBRARY,
            limit=10,
        )
        self.assertGreaterEqual(len(recent["items"]), 2)
        names = {item["filename"] for item in recent["items"]}
        self.assertIn("a.txt", names)
        self.assertIn("b.txt", names)
        self.assertTrue(recent["truth"]["status_from_source_ingestion"])

    def test_oversized_upload_rejected(self) -> None:
        self.si.settings.max_upload_bytes = 64
        with self.assertRaises(Exception):
            self.si.accept_knowledge_library_upload(
                filename="big.txt",
                stream=io.BytesIO(b"x" * 128),
                content_type="text/plain",
            )


if __name__ == "__main__":
    unittest.main()
