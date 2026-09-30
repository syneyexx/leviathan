"""Knowledge Library detail: embeddings, content, relations, download safety (Wave 3)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.knowledge import (
    HybridRetriever,
    KnowledgeStore,
    LocalHashEmbeddingProvider,
    RelationClass,
)
from Data.modules.knowledge.retrieval import RetrievalQuery


class KnowledgeLibraryDetailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data_root = self.root / "ModelData"
        self.data_root.mkdir()
        self.sources = self.root / "sources"
        self.sources.mkdir()
        self.store = KnowledgeStore(
            self.root / "k.db",
            data_root=self.data_root,
            embedding_provider=LocalHashEmbeddingProvider(dimensions=32),
        )
        self.store.initialize()
        self.doc_a = self.store.upsert_document(
            title="Alpha trading handbook",
            content=("Options trading strategies and risk management. " * 40),
            source="manual",
            size_bytes=4096,
            trust_metadata={"tags": ["trading"], "mime_type": "text/plain"},
        )
        self.doc_b = self.store.upsert_document(
            title="Beta volatility guide",
            content=("Volatility trading and market microstructure. " * 40),
            source="manual",
            size_bytes=2048,
            trust_metadata={"tags": ["trading"], "mime_type": "text/plain"},
        )
        self.store.add_relation_atom(
            subject_ref=f"knowledge:document:{self.doc_a.document_id}",
            object_ref=f"knowledge:document:{self.doc_b.document_id}",
            relation_class=RelationClass.LIKE,
            document_id=self.doc_a.document_id,
            confidence=0.8,
            notes="explicit test link",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_embedding_status_coverage(self) -> None:
        status = self.store.document_embedding_status(self.doc_a.document_id)
        assert status is not None
        self.assertGreater(status["chunks_total"], 0)
        self.assertEqual(status["chunks_embedded"], status["chunks_total"])
        self.assertEqual(status["embedding_status"], "OK")
        self.assertTrue(status["truth"]["ready_is_not_embedded"])
        self.assertNotIn("vectors", status)

    def test_content_chunks_bounded(self) -> None:
        page = self.store.list_document_content_chunks(self.doc_a.document_id, limit=2)
        assert page is not None
        self.assertLessEqual(len(page["chunks"]), 2)
        self.assertTrue(page["truth"]["bounded"])
        self.assertIn("content", page["chunks"][0])

    def test_relations_and_related_exclude_self(self) -> None:
        rel = self.store.list_document_relations(self.doc_a.document_id)
        assert rel is not None
        self.assertGreaterEqual(rel["total"], 1)
        self.assertEqual(rel["relations"][0]["relationship_kind"], "explicit")

        retriever = HybridRetriever(self.store)
        related = self.store.list_related_library_sources(
            self.doc_a.document_id, limit=10, retriever=retriever
        )
        assert related is not None
        ids = {r["id"] for r in related["related"]}
        self.assertNotIn(self.doc_a.document_id, ids)
        self.assertIn(self.doc_b.document_id, ids)
        kinds = {r["relationship_kind"] for r in related["related"]}
        self.assertIn("explicit", kinds)

    def test_download_rejects_outside_roots_and_streams_safe_file(self) -> None:
        # Place a safe artifact under sources_root and point trust at it.
        artifact = self.sources / "safe.txt"
        artifact.write_text("safe artifact bytes", encoding="utf-8")
        self.store.merge_document_trust_metadata(
            self.doc_a.document_id,
            {"filename": "safe.txt", "mime_type": "text/plain"},
        )
        # Without research_store, fall back to original_path under data_root.
        under_root = self.data_root / "nested" / "doc.txt"
        under_root.parent.mkdir(parents=True)
        under_root.write_text("nested", encoding="utf-8")
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE knowledge_documents SET original_path = ? WHERE id = ?",
                (str(under_root), self.doc_a.document_id),
            )
        resolved = self.store.resolve_downloadable_artifact(
            self.doc_a.document_id,
            sources_root=self.sources,
        )
        assert resolved is not None
        self.assertEqual(Path(resolved["path"]), under_root.resolve())
        self.assertTrue(resolved["truth"]["path_not_client_supplied"])

        # Escape attempt: point original_path outside allowed roots.
        evil = self.root / "evil.bin"
        evil.write_bytes(b"nope")
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE knowledge_documents SET original_path = ? WHERE id = ?",
                (str(evil), self.doc_a.document_id),
            )
        blocked = self.store.resolve_downloadable_artifact(
            self.doc_a.document_id,
            sources_root=self.sources,
        )
        assert blocked is not None
        self.assertIsNone(blocked.get("path"))

    def test_text_preview_bounded(self) -> None:
        preview = self.store.bounded_text_preview(self.doc_a.document_id, max_chars=100)
        assert preview is not None
        self.assertLessEqual(len(preview["text"]), 100)
        self.assertTrue(preview["truncated"])

    def test_missing_document(self) -> None:
        self.assertIsNone(self.store.document_embedding_status("missing"))
        self.assertIsNone(self.store.list_document_content_chunks("missing"))
        self.assertIsNone(self.store.list_document_relations("missing"))
        self.assertIsNone(self.store.list_related_library_sources("missing"))


if __name__ == "__main__":
    unittest.main()
