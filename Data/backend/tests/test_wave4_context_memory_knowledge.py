"""Wave 4 — Context / memory / knowledge substrate exit gates (U061–U120)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.context import ContextBuilder, compact_conversation
from Data.modules.evidence import parse_evidence_ref
from Data.modules.knowledge import HybridRetriever, KnowledgeStore, RetrievalQuery
from Data.modules.memory import MemoryKind, MemoryScope, MemoryStore
from Data.modules.reasoning import ReasoningEngine


class ConstraintRetentionTests(unittest.TestCase):
    def test_pinned_constraints_survive_tight_budget(self) -> None:
        plan = ReasoningEngine().analyze("long project", has_knowledge=True)
        builder = ContextBuilder(token_budget=500, reserve_response_tokens=50, max_knowledge_chars=200)
        constraint = "MUST never share secrets across projects; always retain this constraint."
        history = [
            {"role": "user", "content": f"turn {i} filler " + ("word " * 40)}
            for i in range(30)
        ]
        knowledge = [
            {"title": f"Doc{i}", "content": ("knowledge " * 50), "source": "t", "chunk_hash": f"h{i}"}
            for i in range(15)
        ]
        pack = builder.build(
            history=history,
            knowledge=knowledge,
            plan=plan,
            constraints=constraint,
        )
        self.assertTrue(pack.constraints_retained)
        self.assertIn(constraint, pack.system_prompt)
        self.assertTrue(any(s.kind == "constraint" and s.pinned for s in pack.sections))
        self.assertIsNotNone(pack.snapshot_hash)
        self.assertIsNotNone(pack.budget_ledger)
        self.assertTrue(pack.public_dict()["truth"]["pinned_constraints_survive_budget_pressure"])

    def test_compaction_preserves_constraints_as_derived(self) -> None:
        history = [
            {"role": "user", "content": "You must always use SQLite as the only database."},
            {"role": "assistant", "content": "Understood, I will keep SQLite central."},
            {"role": "user", "content": "What about Postgres?"},
        ]
        result = compact_conversation(history)
        self.assertTrue(result.constraints)
        self.assertTrue(result.public_dict()["truth"]["does_not_replace_canonical_history"])


class RetrievalThresholdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        data_root = root / "ModelData"
        data_root.mkdir()
        db = root / "k.db"
        MigrationRunner(db).apply_all()
        self.store = KnowledgeStore(db, data_root=data_root)
        self.store.initialize()
        self.store.upsert_document(
            title="SQLite ownership",
            content="Leviathan uses a single SQLite database for metadata truth.",
            source="wave4",
        )
        self.retriever = HybridRetriever(self.store)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_min_score_filters_hits(self) -> None:
        hits, trace = self.retriever.search_with_trace(
            RetrievalQuery(text="SQLite database metadata", limit=5, min_score=0.0)
        )
        self.assertGreaterEqual(len(hits), 1)
        self.assertEqual(trace.selected_count, len(hits))
        # Impossible threshold → empty (threshold gate works).
        filtered, trace2 = self.retriever.search_with_trace(
            RetrievalQuery(text="SQLite database metadata", limit=5, min_score=1.1)
        )
        self.assertEqual(len(filtered), 0)
        self.assertGreaterEqual(trace2.dropped_below_threshold, 1)

    def test_citation_entailment_heuristic(self) -> None:
        hits = self.retriever.search(RetrievalQuery(text="SQLite", limit=3, min_score=0.0))
        self.assertTrue(hits)
        check = HybridRetriever.verify_citation(
            "Leviathan uses a single SQLite database",
            hits[0],
        )
        self.assertIn("overlap_ratio", check.public_dict())
        self.assertTrue(check.public_dict()["truth"]["heuristic_entailment_is_not_proof"])


class MemoryScopeLeakageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.tmp.name) / "mem.db")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_conversation_memory_does_not_leak(self) -> None:
        self.store.create(
            content="Secret preference for conversation A only",
            kind=MemoryKind.PREFERENCE,
            conversation_id="conv-a",
            scope=MemoryScope.CONVERSATION,
        )
        self.store.create(
            content="Global style note",
            kind=MemoryKind.NOTE,
            scope=MemoryScope.GLOBAL,
        )
        # Searching as conversation B must not see A's private memory.
        hits_b = self.store.search(
            "Secret preference",
            conversation_id="conv-b",
            include_global=True,
        )
        self.assertFalse(any("conversation A" in h.content for h in hits_b))
        hits_a = self.store.search(
            "Secret preference",
            conversation_id="conv-a",
            include_global=False,
        )
        self.assertTrue(any("conversation A" in h.content for h in hits_a))
        # Unscoped search only returns GLOBAL (no conversation leak).
        unscoped = self.store.search("Secret preference")
        self.assertFalse(any("conversation A" in h.content for h in unscoped))
        global_hits = self.store.search("Global style")
        self.assertTrue(any("Global style" in h.content for h in global_hits))


class EvidenceRefTests(unittest.TestCase):
    def test_parse_unified_refs(self) -> None:
        ref = parse_evidence_ref("ev:abc-123")
        assert ref is not None
        self.assertEqual(ref.kind, "evidence")
        self.assertEqual(ref.canonical(), "ev:abc-123")
        research = parse_evidence_ref("e:research-1")
        assert research is not None
        self.assertEqual(research.kind, "research")


if __name__ == "__main__":
    unittest.main()
