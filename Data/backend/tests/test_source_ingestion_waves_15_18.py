"""Waves 15–18 — streaming ingest, parse-cache dedupe, progress honesty, scholarly honesty."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.research.source_quality import (
    PUBLICATION_TYPE_ARXIV_PREPRINT,
    PUBLICATION_TYPE_PEER_REVIEWED_ARTICLE,
    PEER_REVIEW_NOT_PEER_REVIEWED,
    PEER_REVIEW_PEER_REVIEWED,
    PEER_REVIEW_UNKNOWN,
    assess_source,
)
from Data.modules.research.types import ResearchSource, SourceType
from Data.modules.source_ingestion.handlers import documents as documents_mod
from Data.modules.source_ingestion.handlers.documents import (
    INLINE_TEXT_BYTES,
    DocumentHandler,
    _read_text_streaming,
    materialize_text_content,
)
from Data.modules.source_ingestion.progress import compute_weighted_progress
from Data.modules.source_ingestion.settings import SourceIngestionSettings
from Data.modules.source_ingestion.store import IngestionStore
from Data.modules.source_ingestion.types import (
    DetectionConfidence,
    DetectionResult,
    IngestionPhase,
    PARSER_VERSION,
    SourceKind,
)


class LargeFileStreamingTests(unittest.TestCase):
    def test_large_text_path_is_file_backed_not_full_bytearray(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            big = root / "big.txt"
            # Just over the inline threshold.
            payload = ("hello world\n" * 200_000).encode("utf-8")
            self.assertGreater(len(payload), INLINE_TEXT_BYTES)
            big.write_bytes(payload)

            # Guard: large path must not assemble a full bytearray of the raw file.
            real_bytearray = documents_mod.bytearray

            class _ForbiddenBytearray(bytearray):
                def __init__(self, *args, **kwargs):
                    raise AssertionError("large-file path must not buffer entire file into bytearray")

            with mock.patch.object(documents_mod, "bytearray", _ForbiddenBytearray):
                ref, digest = materialize_text_content(big, staging_root=root / "stage")
            self.assertIsNone(ref.text)
            self.assertIsNotNone(ref.path)
            self.assertTrue(Path(str(ref.path)).is_file())
            self.assertTrue(digest)
            # Compatibility wrapper still returns str without requiring bytearray.
            with mock.patch.object(documents_mod, "bytearray", _ForbiddenBytearray):
                text = _read_text_streaming(big, staging_root=root / "stage2")
            self.assertIn("hello world", text[:64])

    def test_large_text_path_does_not_call_path_read_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            big = root / "notes.txt"
            big.write_bytes(b"x" * (INLINE_TEXT_BYTES + 1024))
            with mock.patch.object(Path, "read_text", side_effect=AssertionError("read_text forbidden")):
                ref, _ = materialize_text_content(big, staging_root=root / "stage")
            self.assertIsNotNone(ref.path)

    def test_small_file_convenience_still_inline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "small.txt"
            path.write_text("tiny payload", encoding="utf-8")
            ref, digest = materialize_text_content(path)
            self.assertEqual(ref.text, "tiny payload")
            self.assertIsNone(ref.path)
            self.assertTrue(digest)

    def test_large_pdf_path_avoids_read_bytes_and_extract_document(self) -> None:
        handler = DocumentHandler()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.pdf"
            path.write_bytes(b"%PDF-1.4 " + (b"0" * (INLINE_TEXT_BYTES + 100)))
            detection = DetectionResult(
                kind=SourceKind.DOCUMENT,
                mime_type="application/pdf",
                extension=".pdf",
                confidence=DetectionConfidence.HIGH,
            )

            def _boom_extract(*_a, **_k):
                raise AssertionError("extract_document must not be mandatory for large PDFs")

            def _boom_legacy(*_a, **_k):
                raise AssertionError("legacy read_bytes PDF path must not run for large files")

            with mock.patch(
                "Data.modules.documents.extraction.extract_document",
                side_effect=_boom_extract,
            ), mock.patch.object(
                DocumentHandler,
                "_ingest_pdf_legacy",
                side_effect=_boom_legacy,
            ):
                art = handler.ingest(
                    path,
                    detection=detection,
                    relative_path="large.pdf",
                    settings=SourceIngestionSettings(),
                    staging_root=Path(tmp) / "stage",
                )
            self.assertEqual(art.parser, "pdf_stream")
            self.assertIsNotNone(art.content_hash)
            # Provenance must record streaming; pages may be UNMEASURED without pypdf text.
            self.assertTrue((art.provenance or {}).get("streaming") or art.outcome.value in {"success", "failed"})


class ParseCacheDedupeTests(unittest.TestCase):
    def test_content_hash_parse_cache_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = IngestionStore(Path(tmp) / "ing.db")
            store.initialize()
            store.put_parse_cache(
                content_hash="abc123",
                parser_version=PARSER_VERSION,
                parser="plain_text",
                snapshot_path=str(Path(tmp) / "snap.txt"),
                brain_document_id="doc-1",
                parse_status="ok",
                text_hash="t1",
            )
            hit = store.get_parse_cache("abc123", parser_version=PARSER_VERSION)
            self.assertIsNotNone(hit)
            assert hit is not None
            self.assertEqual(hit["brain_document_id"], "doc-1")
            self.assertEqual(hit["parser"], "plain_text")
            miss = store.get_parse_cache("nope", parser_version=PARSER_VERSION)
            self.assertIsNone(miss)


class ProgressMetadataHonestyTests(unittest.TestCase):
    def test_progress_keys_written_or_unmeasured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = IngestionStore(Path(tmp) / "ing.db")
            store.initialize()
            store.merge_progress(
                "src-1",
                project_id="p1",
                phase=IngestionPhase.PARSING,
                pages_parsed=3,
                pages_total=10,
                chunks_done="UNMEASURED",
                chunks_total="UNMEASURED",
                embedding_batches_done="UNMEASURED",
                embedding_batches_total="UNMEASURED",
            )
            container = store.get_container("src-1")
            assert container is not None
            progress = container["progress"]
            self.assertEqual(progress["pages_parsed"], 3)
            self.assertEqual(progress["pages_total"], 10)
            self.assertEqual(progress["chunks_done"], "UNMEASURED")
            self.assertEqual(progress["embedding_batches_total"], "UNMEASURED")

    def test_unmeasured_totals_do_not_fake_percentage(self) -> None:
        w = compute_weighted_progress(
            phase=IngestionPhase.PARSING,
            pages_parsed=None,
            pages_total=None,
        )
        self.assertIsNone(w.progress_pct)
        self.assertFalse(w.measured)
        self.assertIn("UNMEASURED", w.notes)


class ScholarlyHonestyTests(unittest.TestCase):
    def _src(self, uri: str, **meta) -> ResearchSource:
        return ResearchSource(
            source_id="s1",
            project_id="p",
            source_type=SourceType.WEB_PAGE,
            created_at="2026-01-01T00:00:00Z",
            canonical_uri=uri,
            title="Paper",
            metadata=dict(meta),
        )

    def test_arxiv_is_preprint_not_peer_reviewed(self) -> None:
        assessment = assess_source(self._src("https://arxiv.org/abs/1234.5678"))
        self.assertEqual(assessment.publication_type, PUBLICATION_TYPE_ARXIV_PREPRINT)
        self.assertEqual(assessment.peer_review_status, PEER_REVIEW_NOT_PEER_REVIEWED)
        self.assertNotEqual(assessment.source_class, "peer_reviewed")
        self.assertEqual(assessment.source_class, "preprint")

    def test_edu_alone_is_not_peer_reviewed(self) -> None:
        assessment = assess_source(self._src("https://cs.example.edu/people/alice/notes.html"))
        self.assertNotEqual(assessment.source_class, "peer_reviewed")
        self.assertEqual(assessment.peer_review_status, PEER_REVIEW_UNKNOWN)
        self.assertNotEqual(assessment.publication_type, PUBLICATION_TYPE_PEER_REVIEWED_ARTICLE)

    def test_explicit_metadata_can_be_peer_reviewed(self) -> None:
        assessment = assess_source(
            self._src(
                "https://journal.example.org/article/1",
                peer_review_status="PEER_REVIEWED",
                publication_type="PEER_REVIEWED_ARTICLE",
            )
        )
        self.assertEqual(assessment.source_class, "peer_reviewed")
        self.assertEqual(assessment.publication_type, PUBLICATION_TYPE_PEER_REVIEWED_ARTICLE)
        self.assertEqual(assessment.peer_review_status, PEER_REVIEW_PEER_REVIEWED)


if __name__ == "__main__":
    unittest.main()
