"""Knowledge Library bounded query / overview contracts (Wave 1)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.knowledge import KnowledgeStore, LocalHashEmbeddingProvider, NullEmbeddingProvider
from Data.modules.knowledge.library import (
    extract_tags,
    infer_library_type,
    normalize_library_type,
    normalize_tag,
    validate_library_sort,
)


class LibraryHelpersTests(unittest.TestCase):
    def test_normalize_type_and_tags(self) -> None:
        self.assertEqual(normalize_library_type("source_code"), "code")
        self.assertEqual(normalize_library_type("research_paper"), "research_paper")
        self.assertEqual(normalize_tag("#Finance"), "finance")
        self.assertIsNone(normalize_tag(""))
        self.assertEqual(
            extract_tags({"tags": ["#AI", "trading", "AI"]}),
            ["ai", "trading"],
        )

    def test_infer_does_not_invent_books(self) -> None:
        # Filename-ish titles must not become books without typed provenance.
        inferred = infer_library_type(
            source="research_upload",
            parser="plain_text",
            trust_metadata={"filename": "Options Trading Strategies Handbook.pdf"},
        )
        self.assertEqual(inferred, "document")
        pdf = infer_library_type(
            mime_type="application/pdf",
            trust_metadata={"detection": {"kind": "document"}},
        )
        self.assertEqual(pdf, "document")
        code = infer_library_type(
            trust_metadata={"detection": {"kind": "source_code"}},
        )
        self.assertEqual(code, "code")

    def test_relevance_requires_query(self) -> None:
        self.assertEqual(validate_library_sort("relevance", has_query=False), "updated_desc")
        self.assertEqual(validate_library_sort("relevance", has_query=True), "relevance")
        with self.assertRaises(ValueError):
            validate_library_sort("not_a_sort", has_query=False)


class KnowledgeLibraryQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = KnowledgeStore(
            self.root / "k.db",
            data_root=self.root / "ModelData",
            embedding_provider=LocalHashEmbeddingProvider(dimensions=32),
        )
        self.store.initialize()
        # Seed a small but pagination-sensitive corpus.
        for i in range(25):
            self.store.upsert_document(
                title=f"Doc {i:02d} trading notes",
                content=f"Content about markets and trading strategy number {i}. " * 5,
                source="manual" if i % 5 else "research_upload",
                size_bytes=1000 + i * 10,
                trust_metadata={
                    "trust": "test",
                    "tags": ["trading", "finance"] if i % 2 == 0 else ["ai"],
                    "mime_type": "text/plain",
                    "library_type": "note" if i % 5 == 0 else "document",
                },
                source_type="document",
            )
        self.store.upsert_document(
            title="Alpha code module",
            content="def run():\n    return 42\n",
            source="upload:run.py",
            size_bytes=128,
            trust_metadata={
                "trust": "test",
                "tags": ["code"],
                "detection": {"kind": "source_code"},
                "mime_type": "text/x-python",
            },
            source_type="code",
            parser="code",
        )
        # Simulate an unmeasured artifact size (NULL) without inventing zero bytes.
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE knowledge_documents SET size_bytes = NULL WHERE title = ?",
                ("Alpha code module",),
            )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_total_sources_and_overview(self) -> None:
        overview = self.store.library_overview()
        self.assertEqual(overview["total_sources"], 26)
        self.assertGreaterEqual(overview["measured_sources"], 25)
        self.assertEqual(overview["unknown_size_sources"], 1)
        self.assertIsInstance(overview["measured_bytes"], int)
        self.assertGreater(overview["measured_bytes"], 0)
        self.assertGreaterEqual(overview["source_type_count"], 2)
        types = {c["id"]: c["count"] for c in overview["source_type_counts"]}
        self.assertIn("document", types)
        self.assertIn("note", types)
        self.assertIn("code", types)
        # Embedding coverage uses chunk denominator with hash provider available.
        emb = overview["embedding"]
        self.assertEqual(emb["status"], "OK")
        self.assertIsNotNone(emb["coverage_percent"])
        self.assertGreaterEqual(emb["coverage_percent"], 99.0)
        self.assertIsNotNone(overview["latest_ingestion"])
        self.assertTrue(overview["truth"]["does_not_count_chunks_as_sources"])

    def test_null_embedding_provider_not_zero_percent(self) -> None:
        store = KnowledgeStore(
            self.root / "null.db",
            embedding_provider=NullEmbeddingProvider(),
        )
        store.initialize()
        store.upsert_document(title="x", content="hello world " * 20, source="manual")
        overview = store.library_overview()
        self.assertEqual(overview["embedding"]["status"], "NOT_CONFIGURED")
        self.assertIsNone(overview["embedding"]["coverage_percent"])

    def test_pagination_is_bounded_and_stable(self) -> None:
        page1 = self.store.query_library(limit=10, offset=0, sort="updated_desc")
        self.assertEqual(len(page1["items"]), 10)
        self.assertEqual(page1["total"], 26)
        self.assertTrue(page1["has_more"])
        self.assertEqual(page1["next_offset"], 10)
        # No content/chunks in rows
        for item in page1["items"]:
            self.assertNotIn("content", item)
            self.assertTrue(item["truth"]["summary_excludes_content"])

        page2 = self.store.query_library(limit=10, cursor=str(page1["next_cursor"]))
        self.assertEqual(len(page2["items"]), 10)
        ids1 = {i["id"] for i in page1["items"]}
        ids2 = {i["id"] for i in page2["items"]}
        self.assertFalse(ids1 & ids2)

        # Max page size clamped
        big = self.store.query_library(limit=500)
        self.assertEqual(big["limit"], 100)
        self.assertLessEqual(len(big["items"]), 100)

    def test_filters_search_type_tag_status(self) -> None:
        by_type = self.store.query_library(library_type="code")
        self.assertEqual(by_type["total"], 1)
        self.assertEqual(by_type["items"][0]["library_type"], "code")

        by_tag = self.store.query_library(tag="finance")
        self.assertGreaterEqual(by_tag["total"], 10)
        for item in by_tag["items"]:
            self.assertIn("finance", item["tags"])

        by_q = self.store.query_library(q="Alpha code", sort="relevance")
        self.assertGreaterEqual(by_q["total"], 1)
        self.assertEqual(by_q["sort"], "relevance")
        self.assertEqual(by_q["items"][0]["title"], "Alpha code module")

        # Relevance without query falls back
        browse = self.store.query_library(sort="relevance")
        self.assertEqual(browse["sort"], "updated_desc")

    def test_invalid_sort_and_status_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.store.query_library(sort="bogus")
        with self.assertRaises(ValueError):
            self.store.query_library(status="NOT_A_STATUS")
        with self.assertRaises(ValueError):
            self.store.query_library(cursor="not-int")

    def test_tag_mutations(self) -> None:
        doc = self.store.upsert_document(
            title="Tagged",
            content="tag me",
            source="manual",
            trust_metadata={"tags": ["alpha"]},
        )
        tags = self.store.add_document_tags(doc.document_id, ["beta", "alpha"])
        self.assertEqual(tags, ["alpha", "beta"])
        replaced = self.store.set_document_tags(doc.document_id, ["gamma"])
        self.assertEqual(replaced, ["gamma"])
        summary = self.store.get_library_document_summary(doc.document_id)
        assert summary is not None
        self.assertEqual(summary["tags"], ["gamma"])

    def test_zero_data_overview(self) -> None:
        empty = KnowledgeStore(self.root / "empty.db")
        empty.initialize()
        overview = empty.library_overview()
        self.assertEqual(overview["total_sources"], 0)
        self.assertEqual(overview["measured_bytes"], 0)
        self.assertEqual(overview["source_type_count"], 0)
        self.assertIsNone(overview["latest_ingestion"])
        self.assertIn(overview["embedding"]["status"], {"NOT_CONFIGURED", "NO_CHUNKS"})


if __name__ == "__main__":
    unittest.main()
