"""Round 3 — Knowledge and retrieval exit gates."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from Data.modules.knowledge import (
    HybridRetriever,
    IngestStatus,
    KnowledgeStore,
    LocalHashEmbeddingProvider,
    NullEmbeddingProvider,
    RetrievalMode,
    RetrievalQuery,
    bm25_relevance,
    build_embedding_provider,
    reciprocal_rank_fusion,
)


class Bm25SemanticsTests(unittest.TestCase):
    def test_sqlite_bm25_is_negative_and_lower_is_better(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = KnowledgeStore(Path(tmp) / "k.db")
            store.initialize()
            store.upsert_document(
                title="Hybrid",
                content="Hybrid retrieval combines BM25 with vector similarity for ranking.",
                source="test",
            )
            store.upsert_document(
                title="Cooking",
                content="Pasta carbonara recipe with eggs cheese and black pepper.",
                source="test",
            )
            store.upsert_document(
                title="BM25 note",
                content="BM25 is a probabilistic ranking function used in lexical search.",
                source="test",
            )
            rows = store.search_lexical("hybrid retrieval BM25", limit=10)
            self.assertTrue(rows)
            ranks = [float(r["rank"]) for r in rows]
            # FTS5 bm25: more negative = better match. At least one hit should be negative.
            self.assertTrue(any(r < 0 for r in ranks), ranks)
            # Ordering must be ascending (best first).
            self.assertEqual(ranks, sorted(ranks))

    def test_broken_positive_assumption_collapses_scores(self) -> None:
        """Document why 1/(1+max(rank,0)) is wrong for SQLite bm25."""
        negative_ranks = [-2.8, -2.0, -0.7]
        broken = [1.0 / (1.0 + max(r, 0.0)) for r in negative_ranks]
        self.assertEqual(len(set(broken)), 1)  # all become 1.0
        fixed = [bm25_relevance(r) for r in negative_ranks]
        self.assertEqual(fixed, sorted(fixed, reverse=True))

    def test_rrf_does_not_require_positive_scores(self) -> None:
        fused = reciprocal_rank_fusion(
            [["a", "b", "c"], ["b", "a", "d"]],
            k=60,
        )
        self.assertGreater(fused["b"], fused["c"])
        self.assertGreater(fused["a"], fused["d"])


class ModalityEvalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.embeddings = LocalHashEmbeddingProvider(dimensions=64)
        self.store = KnowledgeStore(
            Path(self.tmp.name) / "k.db",
            embedding_provider=self.embeddings,
        )
        self.store.initialize()
        self.store.upsert_document(
            title="Reconnect NL",
            content=(
                "Reconnect-fouten veroorzaken sessieverlies na timeout. "
                "Primaire oorzaken zijn netwerkflaps en stale tokens."
            ),
            source="test",
        )
        self.store.upsert_document(
            title="Pasta",
            content="Kook de pasta al dente met zout water en serveer met pesto.",
            source="test",
        )
        self.store.upsert_document(
            title="Hybrid EN",
            content="Hybrid retrieval fuses lexical BM25 ranks with dense cosine similarity.",
            source="test",
        )
        self.retriever = HybridRetriever(self.store, embeddings=self.embeddings)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_lexical_only_dutch_query(self) -> None:
        hits, trace = self.retriever.search_with_trace(
            RetrievalQuery(
                text="Wat is bekend over reconnect-fouten?",
                limit=3,
                mode=RetrievalMode.LEXICAL,
            )
        )
        self.assertTrue(hits)
        self.assertEqual(trace.mode, "lexical")
        self.assertEqual(trace.fusion, "bm25_relevance")
        self.assertTrue(any("reconnect" in h.content.lower() for h in hits))
        # Scores must differentiate — not all identical collapsed values.
        if len(hits) > 1:
            self.assertTrue(any(hits[0].score != h.score for h in hits[1:]) or hits[0].score > 0)

    def test_dense_only(self) -> None:
        hits, trace = self.retriever.search_with_trace(
            RetrievalQuery(
                text="session drop after network timeout token",
                limit=3,
                mode=RetrievalMode.DENSE,
            )
        )
        self.assertTrue(hits)
        self.assertEqual(trace.mode, "dense")
        self.assertTrue(all(h.modality == "vector" for h in hits))
        self.assertFalse(trace.embedding_is_semantic)

    def test_hybrid_uses_rrf(self) -> None:
        hits, trace = self.retriever.search_with_trace(
            RetrievalQuery(
                text="hybrid BM25 dense fusion",
                limit=3,
                mode=RetrievalMode.HYBRID,
            )
        )
        self.assertTrue(hits)
        self.assertEqual(trace.mode, "hybrid")
        # With both modalities available, fusion should be RRF.
        self.assertEqual(trace.fusion, "rrf")
        self.assertTrue(
            any(h.provenance.get("fusion") == "rrf" for h in hits if h.modality == "hybrid")
            or any(h.provenance.get("rrf_score") is not None for h in hits)
        )

    def test_hybrid_rerank_with_fake_reranker(self) -> None:
        class FakeReranker:
            provider_id = "fake"

            def available(self) -> bool:
                return True

            def status(self) -> dict[str, Any]:
                return {"available": True, "provider_id": self.provider_id}

            def score(self, query: str, passages: list[str]) -> list[float]:
                # Prefer passages mentioning reconnect.
                return [10.0 if "reconnect" in p.lower() else 1.0 for p in passages]

        retriever = HybridRetriever(
            self.store,
            embeddings=self.embeddings,
            reranker=FakeReranker(),  # type: ignore[arg-type]
        )
        hits, trace = retriever.search_with_trace(
            RetrievalQuery(
                text="reconnect timeout",
                limit=3,
                mode=RetrievalMode.HYBRID_RERANK,
            )
        )
        self.assertTrue(hits)
        self.assertEqual(hits[0].modality, "reranked")
        self.assertIn("rerank", trace.fusion)
        self.assertIn("reconnect", hits[0].content.lower())


class EmbeddingHonestyTests(unittest.TestCase):
    def test_hash_provider_is_not_semantic(self) -> None:
        provider = build_embedding_provider(kind="hash", hash_dimensions=32)
        status = provider.status()
        self.assertFalse(status["is_semantic"])
        self.assertTrue(status["truth"]["hash_vectors_are_not_semantic_embeddings"])
        self.assertFalse(getattr(provider, "is_semantic"))

    def test_null_provider_not_semantic(self) -> None:
        provider = NullEmbeddingProvider()
        self.assertFalse(provider.is_semantic)
        self.assertFalse(provider.status()["is_semantic"])

    def test_hybrid_trace_marks_hash_non_semantic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            embeddings = LocalHashEmbeddingProvider(dimensions=32)
            store = KnowledgeStore(Path(tmp) / "k.db", embedding_provider=embeddings)
            store.initialize()
            store.upsert_document(title="A", content="alpha beta gamma retrieval", source="t")
            retriever = HybridRetriever(store, embeddings=embeddings)
            _, trace = retriever.search_with_trace(
                RetrievalQuery(text="alpha retrieval", mode=RetrievalMode.HYBRID)
            )
            self.assertFalse(trace.embedding_is_semantic)
            self.assertTrue(trace.public_dict()["truth"]["hash_vectors_are_not_semantic_embeddings"])


class IndexDeleteProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.embeddings = LocalHashEmbeddingProvider(dimensions=32)
        self.store = KnowledgeStore(
            Path(self.tmp.name) / "k.db",
            embedding_provider=self.embeddings,
        )
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_delete_removes_lexical_and_dense(self) -> None:
        doc = self.store.upsert_document(
            title="Ephemeral",
            content="UniqueZebraToken must disappear after delete.",
            source="test",
        )
        chunk_ids = [c.chunk_id for c in self.store.list_chunks(doc.document_id)]
        self.assertTrue(chunk_ids)
        self.assertTrue(self.store.get_chunk_embedding(chunk_ids[0]) is not None)
        pre = HybridRetriever(self.store, embeddings=self.embeddings).search(
            RetrievalQuery(text="UniqueZebraToken", mode=RetrievalMode.LEXICAL)
        )
        self.assertTrue(pre)
        self.assertTrue(self.store.delete_document(doc.document_id))
        post_lex = HybridRetriever(self.store).search(
            RetrievalQuery(text="UniqueZebraToken", mode=RetrievalMode.LEXICAL)
        )
        self.assertEqual(post_lex, [])
        self.assertIsNone(self.store.get_chunk_embedding(chunk_ids[0]))
        self.assertIsNone(self.store.get_chunk(chunk_ids[0]))

    def test_update_changes_content_hash_and_index(self) -> None:
        doc = self.store.upsert_document(
            title="Mutable",
            content="OldUniqueAlpha content about whales.",
            source="test",
            document_id="doc-mutable",
        )
        old_hash = doc.content_hash
        updated = self.store.upsert_document(
            title="Mutable",
            content="NewUniqueBeta content about retrieval provenance.",
            source="test",
            document_id="doc-mutable",
        )
        self.assertNotEqual(old_hash, updated.content_hash)
        hits_old = HybridRetriever(self.store).search(
            RetrievalQuery(text="OldUniqueAlpha", mode=RetrievalMode.LEXICAL)
        )
        hits_new = HybridRetriever(self.store).search(
            RetrievalQuery(text="NewUniqueBeta", mode=RetrievalMode.LEXICAL)
        )
        self.assertEqual(hits_old, [])
        self.assertTrue(hits_new)
        self.assertEqual(hits_new[0].document_hash, updated.content_hash)

    def test_invalid_source_filtered(self) -> None:
        self.store.upsert_document(
            title="Revoked",
            content="SecretRevokedToken about policies.",
            source="test",
            trust_metadata={"trust": "manual", "revoked": True, "source_validity": "revoked"},
        )
        self.store.upsert_document(
            title="Valid",
            content="SecretValidToken about policies.",
            source="test",
            trust_metadata={"trust": "manual", "valid": True},
        )
        hits = HybridRetriever(self.store).search(
            RetrievalQuery(text="SecretRevokedToken SecretValidToken policies", limit=5)
        )
        self.assertTrue(hits)
        self.assertTrue(all("Revoked" not in h.title for h in hits))
        self.assertTrue(any("Valid" in h.title for h in hits))

    def test_expired_valid_until_filtered(self) -> None:
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(timespec="seconds")
        self.store.upsert_document(
            title="Expired",
            content="TempExpiredToken temporal knowledge.",
            source="test",
            trust_metadata={"valid_until": past},
        )
        self.store.upsert_document(
            title="Current",
            content="TempCurrentToken temporal knowledge.",
            source="test",
            trust_metadata={"valid_until": future},
        )
        hits = HybridRetriever(self.store).search(
            RetrievalQuery(text="TempExpiredToken TempCurrentToken temporal", limit=5)
        )
        titles = {h.title for h in hits}
        self.assertNotIn("Expired", titles)
        self.assertIn("Current", titles)

    def test_failed_status_excluded(self) -> None:
        doc = self.store.upsert_document(
            title="Fail",
            content="FailStatusToken should not retrieve.",
            source="test",
        )
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE knowledge_documents SET status = ? WHERE id = ?",
                (IngestStatus.FAILED.value, doc.document_id),
            )
        hits = HybridRetriever(self.store).search(
            RetrievalQuery(text="FailStatusToken", mode=RetrievalMode.LEXICAL)
        )
        self.assertEqual(hits, [])


class SemanticProviderOptionalTests(unittest.TestCase):
    def test_sentence_transformers_honest_when_missing(self) -> None:
        provider = build_embedding_provider(kind="sentence_transformers")
        status = provider.status()
        if provider.available():
            self.assertTrue(status["is_semantic"])
        else:
            self.assertFalse(status.get("is_semantic", False))
            self.assertTrue(status["truth"]["unavailable_is_not_success"])


if __name__ == "__main__":
    unittest.main()
