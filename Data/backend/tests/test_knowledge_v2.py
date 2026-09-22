from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.knowledge import (
    AtlasScale,
    AtlasStore,
    CognitiveEconomyGovernor,
    DeepRecallRequest,
    DeepRecallService,
    HybridRetriever,
    IngestStatus,
    KnowledgeStore,
    LocalHashEmbeddingProvider,
    NullEmbeddingProvider,
    RelationClass,
    RetrievalQuery,
    WhyLibrary,
    build_embedding_provider,
)
from Data.modules.knowledge.chunking import chunk_text, chunk_text_spans
from Data.modules.knowledge.embeddings import cosine_similarity


class ChunkingTests(unittest.TestCase):
    def test_short_text_is_single_chunk(self) -> None:
        self.assertEqual(chunk_text("hello world"), ["hello world"])

    def test_long_text_splits(self) -> None:
        text = ("alpha paragraph.\n\n" * 40) + ("beta " * 200)
        parts = chunk_text(text, max_chars=200, overlap=20)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(parts))

    def test_spans_have_offsets(self) -> None:
        text = "First paragraph.\n\nSecond paragraph that is longer."
        spans = chunk_text_spans(text, max_chars=80, overlap=10)
        self.assertGreaterEqual(len(spans), 1)
        for span in spans:
            self.assertEqual(text[span.start : span.end], span.text)
            self.assertLessEqual(span.start, span.end)


class KnowledgeStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data_root = self.root / "ModelData"
        self.data_root.mkdir()
        self.embeddings = LocalHashEmbeddingProvider(dimensions=64)
        self.store = KnowledgeStore(
            self.root / "k.db",
            data_root=self.data_root,
            embedding_provider=self.embeddings,
        )
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
        self.assertGreaterEqual(chunks[0].end_offset, chunks[0].start_offset)
        self.assertEqual(chunks[0].source_type, "document")
        self.assertIn("document_hash", chunks[0].provenance)

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

    def test_change_detection_rechunks_on_edit(self) -> None:
        path = self.data_root / "notes.txt"
        path.write_text("Original content about whales.", encoding="utf-8")
        first = self.store.ingest_file(path)
        assert first is not None
        first_chunks = self.store.list_chunks(first.document_id)
        path.write_text(
            "Updated content about Leviathan SQLite retrieval and evidence provenance.",
            encoding="utf-8",
        )
        second = self.store.ingest_file(path)
        assert second is not None
        self.assertEqual(first.document_id, second.document_id)
        self.assertNotEqual(first.content_hash, second.content_hash)
        second_chunks = self.store.list_chunks(second.document_id)
        self.assertTrue(second_chunks)
        self.assertNotEqual(first_chunks[0].content_hash, second_chunks[0].content_hash)

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

    def test_hybrid_fuses_dense_when_embeddings_available(self) -> None:
        self.store.upsert_document(
            title="Dense doc",
            content="Quantum entanglement experiment with photons and Bell inequality.",
            source="test",
        )
        self.store.upsert_document(
            title="Unrelated",
            content="Cooking pasta with tomato sauce and basil.",
            source="test",
        )
        retriever = HybridRetriever(self.store, embeddings=self.embeddings)
        hits = retriever.search(
            RetrievalQuery(text="photon entanglement quantum", limit=5, use_embeddings=True)
        )
        self.assertTrue(hits)
        self.assertTrue(any(h.modality in {"hybrid", "vector", "lexical"} for h in hits))
        # Top hit should prefer the physics doc over cooking for this query.
        self.assertIn(hits[0].title, {"Dense doc", "Unrelated"})
        physics = [h for h in hits if h.title == "Dense doc"]
        self.assertTrue(physics)

    def test_relation_atoms(self) -> None:
        doc = self.store.upsert_document(title="R", content="A is like B under evidence.", source="test")
        chunk = self.store.list_chunks(doc.document_id)[0]
        atom = self.store.add_relation_atom(
            subject_ref="A",
            object_ref="B",
            relation_class=RelationClass.LIKE,
            supporting_evidence_refs=[chunk.chunk_id],
            document_id=doc.document_id,
            chunk_id=chunk.chunk_id,
            confidence=0.8,
        )
        listed = self.store.list_relation_atoms(subject_ref="A")
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].atom_id, atom.atom_id)
        self.assertEqual(listed[0].relation_class, RelationClass.LIKE)


class EmbeddingFactoryTests(unittest.TestCase):
    def test_build_hash_provider(self) -> None:
        provider = build_embedding_provider(kind="hash", hash_dimensions=32)
        self.assertTrue(provider.available())
        vec = provider.embed_query("hello leviathan")
        self.assertEqual(len(vec), 32)
        self.assertAlmostEqual(cosine_similarity(vec, vec), 1.0, places=5)

    def test_build_null_provider(self) -> None:
        provider = build_embedding_provider(kind="null")
        self.assertFalse(provider.available())


class AtlasDeepRecallWhyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.embeddings = LocalHashEmbeddingProvider(dimensions=32)
        self.store = KnowledgeStore(
            self.root / "k.db",
            embedding_provider=self.embeddings,
        )
        self.store.initialize()
        self.atlas = AtlasStore(self.root / "k.db")
        self.atlas.initialize()
        self.retriever = HybridRetriever(self.store, embeddings=self.embeddings)
        self.deep = DeepRecallService(
            knowledge=self.store,
            atlas=self.atlas,
            retriever=self.retriever,
            db_path=self.root / "k.db",
            enabled=True,
        )
        self.deep.initialize()
        self.why = WhyLibrary(self.root / "k.db", enabled=True)
        self.why.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_atlas_revise_does_not_rewrite_evidence(self) -> None:
        doc = self.store.upsert_document(
            title="Evidence",
            content="Exact evidence sentence about LEVIATHAN retrieval.",
            source="test",
        )
        chunk = self.store.list_chunks(doc.document_id)[0]
        original_content = chunk.content
        record = self.atlas.create(
            title="Investigation",
            summary="Initial summary",
            scale=AtlasScale.INVESTIGATION,
            evidence_record_refs=[chunk.chunk_id],
            entities=["LEVIATHAN"],
        )
        revised = self.atlas.revise(
            record.atlas_id,
            summary="Revised interpretation",
            revision_reason="operator_edit",
        )
        assert revised is not None
        self.assertEqual(revised.summary, "Revised interpretation")
        refreshed = self.store.get_chunk(chunk.chunk_id)
        assert refreshed is not None
        self.assertEqual(refreshed.content, original_content)

    def test_deep_recall_hydrates_with_budget(self) -> None:
        doc = self.store.upsert_document(
            title="Detail",
            content="The precise SQLite path for knowledge chunks is Data/backend/data/leviathan.db.",
            source="test",
        )
        chunk = self.store.list_chunks(doc.document_id)[0]
        self.atlas.create(
            title="DB path thread",
            summary="Where knowledge lives",
            evidence_record_refs=[chunk.chunk_id],
            unresolved_questions=["Is WAL enabled?"],
        )
        result = self.deep.recall(
            DeepRecallRequest(
                current_question="Where is the exact SQLite knowledge path?",
                missing_detail="path",
                maximum_context_budget=200,
                hydrate_limit=3,
                required_precision="high",
            )
        )
        self.assertTrue(result.available)
        self.assertTrue(result.atlas_matches or result.exact_details)
        self.assertLessEqual(result.context_cost, 200)
        self.assertTrue(result.retrieval_steps)

    def test_deep_recall_disabled_is_honest(self) -> None:
        disabled = DeepRecallService(
            knowledge=self.store,
            atlas=self.atlas,
            retriever=self.retriever,
            db_path=self.root / "k.db",
            enabled=False,
        )
        result = disabled.recall(DeepRecallRequest(current_question="anything"))
        self.assertFalse(result.available)
        self.assertEqual(result.stopped_reason, "feature_disabled")

    def test_why_parent_requires_evidence(self) -> None:
        without = self.why.assimilate(
            observation="Looks similar to parent domain",
            parent_ref="domain:trading",
            evidence_refs=[],
        )
        assert without is not None
        self.assertEqual(without.bucket.value, "superficial_resemblance")
        with_ev = self.why.assimilate(
            observation="Belongs under trading",
            parent_ref="domain:trading",
            evidence_refs=["chunk-1"],
        )
        assert with_ev is not None
        self.assertEqual(with_ev.bucket.value, "why_belongs_to_parent")

    def test_economy_governor_depth_on_demand(self) -> None:
        gov = CognitiveEconomyGovernor(default_deep_recall_budget=800)
        lean = gov.decide(
            complexity="low",
            intent="conversation",
            memory_coverage=0.9,
            deep_recall_enabled=True,
        )
        self.assertFalse(lean.allow_deep_recall)
        deep = gov.decide(
            complexity="high",
            intent="research",
            memory_coverage=0.1,
            deep_recall_enabled=True,
        )
        self.assertTrue(deep.allow_deep_recall)


if __name__ == "__main__":
    unittest.main()
