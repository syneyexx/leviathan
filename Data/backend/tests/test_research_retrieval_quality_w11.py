"""Wave 11 — Research local retrieval quality (hybrid + fair multi-scope)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from Data.modules.knowledge import HybridRetriever, KnowledgeStore, RetrievalHit, RetrievalQuery
from Data.modules.knowledge.embeddings import LocalHashEmbeddingProvider
from Data.modules.knowledge.types import IngestStatus
from Data.modules.research.local_retrieval import LocalResearchRetriever


class _SemanticEmbedder:
    provider_id = "fake_semantic"

    def available(self) -> bool:
        return True

    @property
    def is_semantic(self) -> bool:
        return True

    def status(self) -> dict[str, Any]:
        return {"is_semantic": True, "production_grade": True, "provider_id": self.provider_id}

    def embed_query(self, text: str) -> list[float]:
        # Deterministic tiny vector from character ordinates.
        vals = [float((ord(c) % 13) + 1) for c in (text or "x")[:8]]
        while len(vals) < 8:
            vals.append(1.0)
        return vals[:8]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(t) for t in texts]


class _FakeSearcher:
    """Scope-aware stub returning dense ranked hits per source."""

    def __init__(self, by_scope: dict[str | None, list[RetrievalHit]]) -> None:
        self.by_scope = by_scope
        self.calls: list[RetrievalQuery] = []
        self.embeddings = _SemanticEmbedder()

    def _embedding_is_semantic(self) -> bool:
        return True

    def search(self, query: RetrievalQuery) -> list[RetrievalHit]:
        self.calls.append(query)
        scope = query.source
        hits = list(self.by_scope.get(scope) or [])
        return hits[: query.limit]


def _hit(chunk_id: str, source: str, score: float, content: str) -> RetrievalHit:
    return RetrievalHit(
        document_id=f"doc-{chunk_id}",
        chunk_id=chunk_id,
        chunk_index=0,
        title=chunk_id,
        source=source,
        content=content,
        score=score,
        modality="lexical",
        original_path=None,
        document_hash=None,
        chunk_hash=f"hash-{chunk_id}",
    )


class HybridModeHonestyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "k.db"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_hash_provider_is_honest_lexical_fallback(self) -> None:
        store = KnowledgeStore(
            self.db,
            data_root=self.root / "data",
            embedding_provider=LocalHashEmbeddingProvider(dimensions=16),
        )
        store.initialize()
        store.upsert_document(
            title="t",
            content="semantic needle appears here for retrieval",
            source="dataset:ds1:v1",
            document_id="d1",
        )
        retriever = LocalResearchRetriever(
            HybridRetriever(store, embeddings=store.embedding_provider)
        )
        hits = retriever.search(
            "semantic needle",
            limit=5,
            local_scopes=["dataset:ds1:v1"],
        )
        self.assertTrue(hits)
        self.assertIsNotNone(retriever.last_telemetry)
        self.assertEqual(retriever.last_telemetry.mode, "lexical_fallback")
        self.assertFalse(retriever.last_telemetry.use_embeddings)
        self.assertIs(retriever.last_telemetry.embedding_is_semantic, False)
        self.assertEqual(hits[0].retrieval_mode, "lexical_fallback")

    def test_semantic_provider_enables_hybrid(self) -> None:
        store = KnowledgeStore(
            self.db,
            data_root=self.root / "data",
            embedding_provider=_SemanticEmbedder(),
        )
        store.initialize()
        doc = store.upsert_document(
            title="t",
            content="quantum entanglement tutorial dataset evidence",
            source="dataset:ds1:v1",
            document_id="d1",
        )
        self.assertEqual(doc.status, IngestStatus.READY)
        # Persist embeddings for dense path.
        chunks = store.list_chunks(doc.document_id)
        vectors = _SemanticEmbedder().embed_documents([c.content for c in chunks])
        store.persist_embedding_batch(
            doc.document_id,
            [
                {
                    "chunk_id": c.chunk_id,
                    "embedding": vectors[i],
                    "content_hash": c.content_hash,
                    "provider_id": "fake_semantic",
                    "dimensions": len(vectors[i]),
                }
                for i, c in enumerate(chunks)
            ],
        )
        hybrid = HybridRetriever(store, embeddings=store.embedding_provider)
        retriever = LocalResearchRetriever(hybrid)
        hits = retriever.search(
            "quantum entanglement",
            limit=5,
            local_scopes=["dataset:ds1:v1"],
        )
        self.assertTrue(hits)
        tel = retriever.last_telemetry
        assert tel is not None
        self.assertEqual(tel.mode, "hybrid")
        self.assertTrue(tel.use_embeddings)
        self.assertTrue(tel.embedding_is_semantic)
        # Underlying HybridRetriever should have been asked for embeddings.
        # Inspect via a second call with a recording wrapper.
        calls: list[RetrievalQuery] = []
        real_search = hybrid.search

        def wrap(q: RetrievalQuery):
            calls.append(q)
            return real_search(q)

        hybrid.search = wrap  # type: ignore[method-assign]
        retriever.search("quantum entanglement", limit=3, local_scopes=["dataset:ds1:v1"])
        self.assertTrue(calls)
        self.assertTrue(calls[0].use_embeddings)


class FairMultiScopeMergeTests(unittest.TestCase):
    def test_first_scope_cannot_starve_later_scopes(self) -> None:
        scope_a = "dataset:aaa:v1"
        scope_b = "dataset:bbb:v1"
        # Scope A returns many high-scoring hits; scope B has one relevant hit.
        hits_a = [
            _hit(f"a{i}", scope_a, score=10.0 - i, content=f"alpha common term {i}")
            for i in range(12)
        ]
        hits_b = [_hit("b0", scope_b, score=9.5, content="beta unique marker ZYX")]
        searcher = _FakeSearcher({scope_a: hits_a, scope_b: hits_b})
        retriever = LocalResearchRetriever(searcher)
        results = retriever.search(
            "common",
            limit=5,
            local_scopes=[scope_a, scope_b],
            per_scope_candidate_limit=8,
        )
        self.assertEqual(len(results), 5)
        sources = {h.source for h in results}
        self.assertIn(scope_b, sources)
        self.assertIn(scope_a, sources)
        tel = retriever.last_telemetry
        assert tel is not None
        self.assertEqual(tel.fusion, "rrf_multi_scope")
        self.assertEqual(tel.scopes_searched, 2)
        self.assertTrue(tel.truth["first_scope_cannot_starve_later_scopes"])
        # Both scopes were queried with the candidate bound (not global fill-from-first).
        self.assertEqual(len(searcher.calls), 2)
        self.assertTrue(all(c.limit == 8 for c in searcher.calls))

    def test_legacy_first_scope_fill_is_gone(self) -> None:
        """Regression: previous implementation returned early after first scope filled limit."""
        scope_a = "dataset:one:v1"
        scope_b = "dataset:two:v1"
        searcher = _FakeSearcher(
            {
                scope_a: [_hit("a0", scope_a, 1.0, "only a")],
                scope_b: [_hit("b0", scope_b, 1.0, "only b")],
            }
        )
        retriever = LocalResearchRetriever(searcher)
        results = retriever.search("only", limit=1, local_scopes=[scope_a, scope_b])
        # With RRF across two singleton lists, either may win — but both scopes queried.
        self.assertEqual(len(searcher.calls), 2)
        self.assertEqual(len(results), 1)


if __name__ == "__main__":
    unittest.main()
