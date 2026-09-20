from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.knowledge import (
    HybridRetriever,
    IngestStatus,
    KnowledgeStore,
    NullEmbeddingProvider,
    RetrievalQuery,
)
from Data.modules.knowledge.chunking import chunk_text


class ChunkingTests(unittest.TestCase):
    def test_short_text_is_single_chunk(self) -> None:
        self.assertEqual(chunk_text("hello world"), ["hello world"])

    def test_long_text_splits(self) -> None:
        text = ("alpha paragraph.\n\n" * 40) + ("beta " * 200)
        parts = chunk_text(text, max_chars=200, overlap=20)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(parts))


class KnowledgeStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data_root = self.root / "ModelData"
        self.data_root.mkdir()
        self.store = KnowledgeStore(self.root / "k.db", data_root=self.data_root)
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_upsert_creates_ready_chunks_and_hash(self) -> None:
        doc = self.store.upsert_document(
            title="Leviathan architecture",
            content="The runtime uses SQLite knowledge retrieval and a small reasoning layer.",
            source="test",
        )
        self.assertEqual(doc.status, IngestStatus.READY)
        self.assertTrue(doc.content_hash)
        chunks = self.store.list_chunks(doc.document_id)
        self.assertGreaterEqual(len(chunks), 1)

    def test_lexical_search_returns_chunk_provenance(self) -> None:
        self.store.upsert_document(
            title="Leviathan architecture",
            content="The runtime uses SQLite knowledge retrieval and a small reasoning layer.",
            source="test",
        )
        hits = HybridRetriever(self.store).search(RetrievalQuery(text="SQLite reasoning", limit=5))
        self.assertTrue(hits)
        self.assertEqual(hits[0].title, "Leviathan architecture")
        self.assertTrue(hits[0].chunk_id)
        self.assertEqual(hits[0].modality, "lexical")

    def test_null_embeddings_are_unavailable(self) -> None:
        self.assertFalse(NullEmbeddingProvider().available())

    def test_incremental_file_ingest_skips_unchanged(self) -> None:
        path = self.data_root / "notes.txt"
        path.write_text("Persistent local knowledge about LEVIATHAN runs.", encoding="utf-8")
        first = self.store.ingest_file(path)
        assert first is not None
        second = self.store.ingest_file(path)
        assert second is not None
        self.assertEqual(first.document_id, second.document_id)
        self.assertEqual(first.content_hash, second.content_hash)

    def test_path_escape_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.store.resolve_under_data_root("../outside.txt")

    def test_failed_document_not_returned_as_ready_search(self) -> None:
        doc = self.store.upsert_document(title="x", content="unique-token-abc", source="test")
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE knowledge_documents SET status = ? WHERE id = ?",
                (IngestStatus.FAILED.value, doc.document_id),
            )
        hits = HybridRetriever(self.store).search(RetrievalQuery(text="unique-token-abc"))
        self.assertEqual(hits, [])

    def test_metadata_source_filter(self) -> None:
        self.store.upsert_document(title="A", content="alpha signal knowledge", source="manual")
        self.store.upsert_document(title="B", content="alpha signal knowledge", source="modeldata")
        hits = HybridRetriever(self.store).search(
            RetrievalQuery(text="alpha signal", limit=5, source="modeldata")
        )
        self.assertTrue(hits)
        self.assertTrue(all(hit.source == "modeldata" for hit in hits))


if __name__ == "__main__":
    unittest.main()
