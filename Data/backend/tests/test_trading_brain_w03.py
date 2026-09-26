"""WAVE 03 — Trading uses canonical Brain/Knowledge retrieval (no second owner)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.knowledge import KnowledgeStore
from Data.modules.knowledge.embeddings import LocalHashEmbeddingProvider, NullEmbeddingProvider
from Data.modules.knowledge.retrieval import HybridRetriever, RetrievalQuery
from Data.modules.market_sim.brain_hooks import BrainFacade, adapt_knowledge_store
from Data.modules.market_sim.trading_brain import (
    TradingBrainAdapter,
    TradingRetrievalRequest,
)


class _FakeSemanticEmbeddings:
    """Minimal semantic fixture: similar phrases share a direction."""

    provider_id = "fake_semantic_fixture"
    is_semantic = True
    dimensions = 8

    def available(self) -> bool:
        return True

    def status(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "available": True,
            "is_semantic": True,
            "provider": "fake_semantic_fixture",
        }

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)

    def _vec(self, text: str) -> list[float]:
        key = text.lower()
        if any(
            tok in key
            for tok in (
                "volatility",
                "variance",
                "contraction",
                "declining",
                "range expansion",
                "breakout",
            )
        ):
            return [1.0, 0.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        return [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


class TradingBrainIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "k.db"
        self.data_root = self.root / "data"
        self.data_root.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _ingest(self, store: KnowledgeStore, text: str, *, title: str = "doc") -> str:
        path = self.data_root / f"{title}.txt"
        path.write_text(text, encoding="utf-8")
        doc = store.ingest_file(path, source=f"dataset:trading-knowledge:{title}")
        if doc is None:
            return ""
        return getattr(doc, "document_id", None) or getattr(doc, "id", "") or ""

    def test_semantic_fixture_retrieves_paraphrase(self) -> None:
        store = KnowledgeStore(
            self.db,
            data_root=self.data_root,
            embedding_provider=_FakeSemanticEmbeddings(),
        )
        store.initialize()
        self._ingest(
            store,
            "volatility contraction commonly precedes range expansion",
            title="vol-semantic",
        )
        # Ensure dense vectors exist for chunks when provider supports it.
        if hasattr(store, "reembed_all"):
            store.reembed_all()
        retriever = HybridRetriever(store, embeddings=_FakeSemanticEmbeddings())
        adapter = TradingBrainAdapter(hybrid_retriever=retriever, knowledge_store=store)
        result = adapter.retrieve(
            TradingRetrievalRequest(
                query="declining realized variance before breakout",
                max_hits=5,
                prefer_semantic=True,
            )
        )
        self.assertTrue(result.embeddings_semantic)
        self.assertFalse(result.miss)
        blob = " ".join(h.content_excerpt.lower() for h in result.hits)
        self.assertTrue("volatility" in blob or "contraction" in blob or "expansion" in blob)

    def test_semantic_style_query_finds_related_knowledge_with_hash_fixture(self) -> None:
        """Hash embeddings are NOT semantic — mode must be labeled honestly.

        Still, HybridRetriever should return the injected document for overlapping tokens,
        and TradingBrainAdapter must report embeddingsSemantic=False for hash provider.
        """
        store = KnowledgeStore(
            self.db,
            data_root=self.data_root,
            embedding_provider=LocalHashEmbeddingProvider(dimensions=64),
        )
        store.initialize()
        self._ingest(
            store,
            "volatility contraction commonly precedes range expansion in markets",
            title="vol-contraction",
        )
        retriever = HybridRetriever(store, embeddings=LocalHashEmbeddingProvider(dimensions=64))
        adapter = TradingBrainAdapter(hybrid_retriever=retriever, knowledge_store=store)
        # Semantically different wording — hash provider will not truly match meaning.
        result = adapter.retrieve(
            TradingRetrievalRequest(
                query="declining realized variance before breakout",
                role="strategy_researcher",
                max_hits=5,
                prefer_semantic=True,
            )
        )
        self.assertFalse(result.embeddings_semantic)
        self.assertIn(result.retrieval_mode, {"lexical", "hybrid_semantic", "hybrid"})
        # Honest: hash is not semantic.
        self.assertTrue(result.public_dict()["truth"]["hash_embeddings_are_not_semantic"])

        # Lexical overlapping query must hit.
        result2 = adapter.retrieve(
            TradingRetrievalRequest(
                query="volatility contraction range expansion",
                max_hits=5,
            )
        )
        self.assertFalse(result2.miss)
        blob = " ".join(h.content_excerpt for h in result2.hits).lower()
        self.assertIn("volatility", blob)

    def test_null_embedding_provider_reports_lexical(self) -> None:
        store = KnowledgeStore(
            self.db,
            data_root=self.data_root,
            embedding_provider=NullEmbeddingProvider(),
        )
        store.initialize()
        self._ingest(
            store,
            "volatility contraction commonly precedes range expansion",
            title="vol2",
        )
        retriever = HybridRetriever(store, embeddings=NullEmbeddingProvider())
        adapter = TradingBrainAdapter(hybrid_retriever=retriever, knowledge_store=store)
        result = adapter.retrieve(
            TradingRetrievalRequest(query="volatility contraction precedes", max_hits=3)
        )
        self.assertFalse(result.miss)
        self.assertFalse(result.embeddings_semantic)
        self.assertIn("lexical", result.retrieval_mode)

    def test_brain_facade_uses_canonical_adapter(self) -> None:
        store = KnowledgeStore(
            self.db,
            data_root=self.data_root,
            embedding_provider=LocalHashEmbeddingProvider(dimensions=32),
        )
        store.initialize()
        self._ingest(store, "momentum works as a hypothesis not proof", title="mom")
        facade = BrainFacade(
            knowledge=adapt_knowledge_store(
                store,
                hybrid_retriever=HybridRetriever(
                    store, embeddings=LocalHashEmbeddingProvider(dimensions=32)
                ),
            )
        )
        retrieval = facade.retrieve("momentum hypothesis", limit=3)
        self.assertFalse(retrieval.miss)
        # retrieve_trading path
        typed = facade.retrieve_trading(
            TradingRetrievalRequest(query="momentum hypothesis", role="critic", max_hits=3)
        )
        self.assertFalse(typed.miss)
        self.assertTrue(typed.public_dict()["truth"]["canonical_brain_owner"])
        self.assertTrue(typed.public_dict()["truth"]["no_second_retrieval_authority"])

    def test_hit_preserves_provenance_fields(self) -> None:
        store = KnowledgeStore(
            self.db,
            data_root=self.data_root,
            embedding_provider=NullEmbeddingProvider(),
        )
        store.initialize()
        self._ingest(store, "sharpe ratio definition is timeless reference", title="sharpe")
        adapter = TradingBrainAdapter(knowledge_store=store)
        result = adapter.retrieve(TradingRetrievalRequest(query="sharpe ratio", max_hits=3))
        self.assertFalse(result.miss)
        hit = result.hits[0].public_dict()
        self.assertIn("sourceKind", hit)
        self.assertIn("retrievalMode", hit)
        self.assertIn("contentExcerpt", hit)


if __name__ == "__main__":
    unittest.main()
