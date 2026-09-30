"""Memory V2 control-plane tests — pagination, lifecycle, semantic, analytics."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.memory import MemoryKind, MemoryScope, MemoryStatus, MemoryStore
from Data.modules.memory.sources import actor_from_record, normalize_source
from Data.modules.memory.worker import process_memory_job


class MemoryV2StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.tmp.name) / "control.db")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_pagination_cursor(self) -> None:
        ids = []
        for i in range(5):
            rec = self.store.create(content=f"item {i} bitcoin research", kind=MemoryKind.NOTE)
            ids.append(rec.memory_id)
        page1 = self.store.list_page(limit=2, sort="newest")
        self.assertEqual(len(page1["memory"]), 2)
        self.assertIsNotNone(page1["next_cursor"])
        page2 = self.store.list_page(limit=2, cursor=page1["next_cursor"], sort="newest")
        self.assertEqual(len(page2["memory"]), 2)
        seen = {m.memory_id for m in page1["memory"] + page2["memory"]}
        self.assertEqual(len(seen), 4)

    def test_filters_kind_source_tag(self) -> None:
        self.store.create(content="alpha", kind=MemoryKind.FACT, source="manual", tags=["pinned"])
        self.store.create(content="beta", kind=MemoryKind.NOTE, source="agent", tags=["x"])
        facts = self.store.list_page(kind=MemoryKind.FACT, limit=10)
        self.assertTrue(all(m.kind == MemoryKind.FACT for m in facts["memory"]))
        pinned = self.store.list_page(pinned_only=True, limit=10)
        self.assertEqual(len(pinned["memory"]), 1)
        agents = self.store.list_page(source="agent", limit=10)
        self.assertEqual(len(agents["memory"]), 1)

    def test_scope_isolation_search(self) -> None:
        self.store.create(
            content="secret conversation note about atlantic",
            kind=MemoryKind.NOTE,
            scope=MemoryScope.CONVERSATION,
            conversation_id="c1",
        )
        self.store.create(
            content="other conversation atlantic",
            kind=MemoryKind.NOTE,
            scope=MemoryScope.CONVERSATION,
            conversation_id="c2",
        )
        hits = self.store.search("atlantic", conversation_id="c1", include_global=False)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].conversation_id, "c1")

    def test_pin_unpin_patch(self) -> None:
        rec = self.store.create(content="pin me", tags=["a"])
        pinned = self.store.pin(rec.memory_id)
        assert pinned is not None
        self.assertTrue(any(t.lower() == "pinned" for t in pinned.tags))
        unpinned = self.store.unpin(rec.memory_id)
        assert unpinned is not None
        self.assertFalse(any(t.lower() == "pinned" for t in unpinned.tags))
        patched = self.store.update(rec.memory_id, priority=0.9, tags=["a", "b"])
        assert patched is not None
        self.assertAlmostEqual(patched.priority, 0.9)
        self.assertEqual(list(patched.tags), ["a", "b"])

    def test_archive_restore_revoke(self) -> None:
        rec = self.store.create(content="lifecycle")
        archived = self.store.set_status(rec.memory_id, MemoryStatus.ARCHIVED)
        assert archived is not None
        self.assertEqual(archived.status, MemoryStatus.ARCHIVED)
        restored = self.store.restore(rec.memory_id)
        assert restored is not None
        self.assertEqual(restored.status, MemoryStatus.ACTIVE)
        revoked = self.store.set_status(rec.memory_id, MemoryStatus.REVOKED)
        assert revoked is not None
        with self.assertRaises(ValueError):
            self.store.restore(rec.memory_id)

    def test_correction_supersedes(self) -> None:
        original = self.store.create(
            content="Bitcoin is orange",
            kind=MemoryKind.FACT,
            trust="explicit",
        )
        correction = self.store.correct(
            original.memory_id,
            content="Bitcoin is digital gold",
            trust="explicit",
        )
        self.assertEqual(correction.kind, MemoryKind.CORRECTION)
        self.assertEqual(correction.supersedes_id, original.memory_id)
        old = self.store.get(original.memory_id)
        assert old is not None
        self.assertEqual(old.status, MemoryStatus.SUPERSEDED)
        active = self.store.list(status=MemoryStatus.ACTIVE, limit=50)
        self.assertTrue(any(m.memory_id == correction.memory_id for m in active))
        self.assertFalse(any(m.memory_id == original.memory_id for m in active))

    def test_overview_aggregates(self) -> None:
        self.store.create(content="one", kind=MemoryKind.NOTE, source="manual")
        self.store.create(content="two", kind=MemoryKind.FACT, source="research")
        archived = self.store.create(content="three", kind=MemoryKind.NOTE)
        self.store.set_status(archived.memory_id, MemoryStatus.ARCHIVED)
        overview = self.store.overview()
        self.assertEqual(overview["total"], 3)
        self.assertEqual(overview["active"], 2)
        self.assertEqual(overview["archived"], 1)
        self.assertGreaterEqual(overview["unique_sources"], 2)
        self.assertEqual(overview["storage"]["provenance"], "MEASURED")
        self.assertIn("semantic_index", overview)

    def test_provenance_preserved_on_patch(self) -> None:
        rec = self.store.create(
            content="keep provenance",
            source="research",
            trust="imported",
            kind=MemoryKind.FACT,
        )
        updated = self.store.update(rec.memory_id, tags=["x"])
        assert updated is not None
        self.assertEqual(updated.source, "research")
        self.assertEqual(updated.trust, "imported")
        self.assertEqual(updated.content, "keep provenance")

    def test_embedding_upsert_and_search_lexical(self) -> None:
        rec = self.store.create(content="vector recall bitcoin halving analysis")
        vec = [0.1] * 8
        receipt = self.store.upsert_embedding(
            rec.memory_id,
            vector=vec,
            provider_id="test",
            model_id="test-model",
            content_hash=self.store.content_hash(rec.content),
        )
        self.assertFalse(receipt["stale"])
        emb = self.store.get_embedding(rec.memory_id)
        assert emb is not None
        self.assertEqual(emb["dimensions"], 8)
        scored = self.store.search_scored("bitcoin halving", mode="lexical", limit=5)
        self.assertGreaterEqual(len(scored["memory"]), 1)
        self.assertEqual(scored["mode"], "lexical")
        self.assertIn("combined_score", scored["memory"][0]["scores"])

    def test_semantic_degrades_without_provider(self) -> None:
        self.store.create(content="semantic unavailable path")
        scored = self.store.search_scored(
            "semantic",
            mode="semantic",
            limit=5,
            query_vector=None,
            is_semantic_provider=False,
        )
        self.assertTrue(scored["degraded"])
        self.assertEqual(scored["mode"], "lexical")

    def test_duplicate_detection_same_scope(self) -> None:
        self.store.create(
            content="Exact same text",
            scope=MemoryScope.GLOBAL,
        )
        self.store.create(
            content="Exact same text",
            scope=MemoryScope.GLOBAL,
        )
        dups = self.store.find_exact_duplicates()
        self.assertGreaterEqual(len(dups), 1)
        self.assertGreaterEqual(dups[0]["count"], 2)

    def test_analytics_and_activity(self) -> None:
        self.store.create(content="analytics item")
        self.store.record_search_telemetry(
            mode="lexical",
            duration_ms=12.0,
            result_count=1,
            scope_class="global_default",
            topic_label="bitcoin",
            query_hash="abc",
        )
        analytics = self.store.analytics(range_key="7d")
        self.assertEqual(analytics["range"], "7d")
        self.assertIn("new_items", analytics["series"])
        self.assertTrue(any(t["topic"] == "bitcoin" for t in analytics["topics"]))
        activity = self.store.list_activity(limit=10)
        self.assertTrue(any(a["event_type"] == "memory.created" for a in activity))

    def test_source_normalization(self) -> None:
        self.assertEqual(normalize_source("web_research"), "research")
        self.assertEqual(normalize_source("manual"), "manual")
        rec = self.store.create(content="x", source="consolidation")
        self.assertEqual(actor_from_record(rec), "Memory Worker")


class MemoryWorkerIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.tmp.name) / "control.db")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_index_action_with_hash_provider(self) -> None:
        from Data.modules.knowledge.embeddings import LocalHashEmbeddingProvider

        rec = self.store.create(content="index this memory about agents")

        class _Job:
            job_id = "job-1"
            arguments = {"action": "index", "memory_ids": [rec.memory_id], "limit": 1}
            capability_id = "memory.enrich"
            lease_owner = "w1"
            result = None

        class _JobStore:
            def get(self, _job_id: str) -> None:
                return None

        ctx = {
            "job_store": _JobStore(),
            "memory_store": self.store,
            "embedding_provider": LocalHashEmbeddingProvider(dimensions=32),
        }
        # Monkeypatch fenced_transition to no-op complete path
        import Data.modules.memory.worker as worker_mod

        def _fake_transition(*_a, **_k):
            return None

        worker_mod.fenced_transition = _fake_transition  # type: ignore[attr-defined]
        from Data.modules.jobs import leases

        original = leases.fenced_transition
        leases.fenced_transition = lambda *a, **k: None  # type: ignore[assignment]
        try:
            result = process_memory_job(ctx, _Job())
        finally:
            leases.fenced_transition = original  # type: ignore[assignment]
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.get("action"), "index")
        self.assertGreaterEqual(int(result.get("indexed") or 0), 1)
        emb = self.store.get_embedding(rec.memory_id)
        self.assertIsNotNone(emb)
        # Hash provider is NOT semantic
        self.assertFalse(result.get("is_semantic"))


if __name__ == "__main__":
    unittest.main()
