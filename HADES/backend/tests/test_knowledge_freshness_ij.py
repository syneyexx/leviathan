"""Behavior tests for work package J — retrieval quality / knowledge freshness."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claim_register import ClaimRegister
from platform_db import PlatformDatabase
from platform_services_core import KnowledgeService
from reasoning.knowledge_freshness import (
    ROLE_BOUNDARIES,
    EmbeddingStore,
    KnowledgeFreshnessService,
    assert_role_distinct,
    build_retrieval_inspection,
    citation_anchor,
    content_hash_text,
    embedding_key,
    measure_retrieval_quality,
    preserve_critical_user_conditions,
)
from reasoning.retrieval import (
    EmbeddingIndexState,
    RetrievalHit,
    build_lexical_hits_from_records,
    merge_rank,
    pack_hits_non_dumping,
)


class RoleBoundaryTests(unittest.TestCase):
    def test_memory_knowledge_evidence_roles_distinct(self) -> None:
        for role in ("memory", "knowledge", "evidence"):
            boundary = assert_role_distinct(role)
            self.assertEqual(boundary.role, role)
        self.assertFalse(ROLE_BOUNDARIES["memory"].may_be_bulk_indexed)
        self.assertTrue(ROLE_BOUNDARIES["knowledge"].may_be_bulk_indexed)
        self.assertNotEqual(ROLE_BOUNDARIES["memory"].notes, ROLE_BOUNDARIES["evidence"].notes)


class ChangedDocsAndStaleEmbeddingsTests(unittest.TestCase):
    def test_changed_docs_invalidate_chunks_and_embeddings(self) -> None:
        store = EmbeddingStore(model_id="embed-v1", index_version=1)
        svc = KnowledgeFreshnessService(embedding_store=store)
        first = svc.upsert_source(uri="file:/docs/a.md", content="alpha policy note", chunks=["alpha policy note"])
        sid = first["source"]["source_id"]
        ch = first["source"]["chunk_hashes"][0]
        store.put(content_hash=ch, vector=[0.1, 0.2], source_id=sid, chunk_id="c0")
        self.assertIsNotNone(store.get(ch))

        second = svc.upsert_source(uri="file:/docs/a.md", content="beta revised note", chunks=["beta revised note"])
        self.assertTrue(second["reimported"])
        self.assertFalse(second["unchanged"])
        self.assertNotEqual(second["previous_content_hash"], second["source"]["content_hash"])
        # New content hash ⇒ embeddings for new chunks missing until reindex.
        pending = svc.assess_freshness(sid, current_file_hash=content_hash_text("beta revised note"))
        self.assertEqual(pending["status"], "stale_embedding")
        new_ch = second["source"]["chunk_hashes"][0]
        store.put(content_hash=new_ch, vector=[0.3, 0.4], source_id=sid, chunk_id="c1")
        fresh = svc.assess_freshness(sid, current_file_hash=content_hash_text("beta revised note"))
        self.assertEqual(fresh["status"], "fresh")
        stale = svc.assess_freshness(sid, current_file_hash=content_hash_text("alpha policy note"))
        self.assertEqual(stale["status"], "stale_content")

        # Model/index version change invalidates embeddings.
        removed = store.invalidate_model_change("embed-v2")
        self.assertGreaterEqual(removed, 0)
        self.assertIsNone(store.get(new_ch))
        self.assertEqual(store.index_version, 2)

    def test_embedding_key_tied_to_hash_model_index(self) -> None:
        a = embedding_key(content_hash="h1", model_id="m1", index_version=1)
        b = embedding_key(content_hash="h1", model_id="m1", index_version=2)
        c = embedding_key(content_hash="h1", model_id="m2", index_version=1)
        d = embedding_key(content_hash="h2", model_id="m1", index_version=1)
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertNotEqual(a, d)


class IdempotentReimportTests(unittest.TestCase):
    def test_idempotent_reimport_unchanged(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        db = PlatformDatabase(str(tmp / "platform.db"))
        db.initialize()
        knowledge = KnowledgeService(db, tmp)
        first = knowledge.ingest_text(title="Doc", text="same body", source_type="file", uri="/tmp/doc.txt")
        second = knowledge.ingest_text(title="Doc", text="same body", source_type="file", uri="/tmp/doc.txt")
        self.assertTrue(second.get("unchanged"))
        self.assertFalse(second.get("reimported"))
        self.assertEqual(first["id"], second["id"])
        third = knowledge.ingest_text(title="Doc", text="changed body", source_type="file", uri="/tmp/doc.txt")
        self.assertTrue(third.get("reimported"))
        self.assertEqual(third["id"], first["id"])
        self.assertNotEqual(third["content_hash"], first["content_hash"])


class CitationAndSourceVersionTests(unittest.TestCase):
    def test_exact_source_versions_and_citation_anchors(self) -> None:
        anchor = citation_anchor(
            source_id="src_1",
            source_version="abc123",
            chunk_id="chk_9",
            sequence=9,
            char_start=10,
            char_end=40,
            heading="Intro",
        )
        self.assertEqual(anchor["source_version"], "abc123")
        self.assertIn("src_1@abc123", anchor["anchor_id"])
        self.assertEqual(anchor["heading"], "Intro")


class SupersededMemoryAndConflictsTests(unittest.TestCase):
    def test_superseded_memory_and_conflicting_sources(self) -> None:
        svc = KnowledgeFreshnessService()
        old = svc.upsert_source(uri="memory:pref", content="Use Python 3.10", role="memory")
        new = svc.upsert_source(uri="memory:pref:v2", content="Use Python 3.12", role="memory")
        marked = svc.mark_superseded(old["source"]["source_id"], by_source_id=new["source"]["source_id"], reason="user_correction")
        self.assertEqual(marked["source"]["status"], "superseded")
        a = svc.upsert_source(uri="file:/a", content="rate is 5%", role="knowledge")
        b = svc.upsert_source(uri="file:/b", content="rate is 7%", role="knowledge")
        conflict = svc.mark_conflict(a["source"]["source_id"], b["source"]["source_id"])
        self.assertEqual(conflict["status"], "conflict")

        claims = ClaimRegister()
        cid = claims.add_claim(text="rate is 5%", provenance="file:/a", source_kind="primary")
        claims.supersede(cid, new_text="rate is 7%", provenance="file:/b", reason="newer_source")
        self.assertEqual(claims.get(cid)["verification_status"], "SUPERSEDED")


class ScopeFilterTests(unittest.TestCase):
    def test_project_and_conversation_scope(self) -> None:
        svc = KnowledgeFreshnessService()
        p1 = svc.upsert_source(uri="k:1", content="alpha", project_id="projA", conversation_id="c1")
        p2 = svc.upsert_source(uri="k:2", content="beta", project_id="projB", conversation_id="c2")
        scoped = svc.filter_scope(
            [p1["source"]["source_id"], p2["source"]["source_id"]],
            project_id="projA",
        )
        self.assertEqual(scoped["kept"], [p1["source"]["source_id"]])
        self.assertTrue(any(d["reason"] == "out_of_project_scope" for d in scoped["dropped"]))


class DeletedUnreachableSourceTests(unittest.TestCase):
    def test_deleted_and_unreachable_sources(self) -> None:
        svc = KnowledgeFreshnessService()
        src = svc.upsert_source(uri="file:/gone.md", content="x", local_path="/gone.md")
        missing = svc.assess_freshness(src["source"]["source_id"], file_exists=False)
        self.assertEqual(missing["status"], "source_missing")
        unreachable = svc.assess_freshness(src["source"]["source_id"], file_reachable=False)
        self.assertEqual(unreachable["status"], "source_unreachable")


class ContextBudgetCriticalTests(unittest.TestCase):
    def test_context_budgets_preserve_critical_user_conditions(self) -> None:
        items = [
            {"item_id": "c1", "kind": "user_constraint", "content": "MUST use offline mode only", "critical": True},
            {"item_id": "k1", "kind": "knowledge", "content": "long " * 400},
            {"item_id": "k2", "kind": "knowledge", "content": "more " * 400},
        ]
        packed = preserve_critical_user_conditions(items, max_chars=200)
        self.assertEqual(packed["critical_kept"], packed["critical_total"])
        self.assertTrue(any(i.get("item_id") == "c1" for i in packed["kept"]))
        self.assertTrue(packed["ok"])


class CancelledBulkIngestResumeTests(unittest.TestCase):
    def test_resume_cancelled_bulk_ingestion(self) -> None:
        svc = KnowledgeFreshnessService()
        paths = [f"/tmp/doc_{i}.txt" for i in range(5)]
        texts = {p: f"body {i}" for i, p in enumerate(paths)}
        job = svc.start_bulk_ingest(paths=paths)
        # Process two, then cancel.
        for _ in range(2):
            svc.ingest_next(job["id"], read_text=lambda p: texts[p])
        cancelled = svc.cancel_bulk_ingest(job["id"])
        self.assertIn(cancelled["status"], {"cancel_requested", "cancelled"})
        blocked = svc.ingest_next(job["id"], read_text=lambda p: texts[p])
        self.assertTrue(blocked.get("cancelled"))
        resumed = svc.resume_bulk_ingest(job["id"])
        self.assertEqual(resumed["status"], "running")
        self.assertEqual(resumed["cursor"], 2)
        while True:
            step = svc.ingest_next(job["id"], read_text=lambda p: texts[p])
            if step.get("done"):
                break
        final = svc.get_ingest_job(job["id"])
        assert final is not None
        self.assertEqual(final["status"], "completed")
        self.assertEqual(final["cursor"], 5)


class LexicalFallbackAndInspectionTests(unittest.TestCase):
    def test_lexical_works_when_semantic_unavailable(self) -> None:
        records = [
            {"id": "1", "title": "Alpha", "content": "offline lexical retrieval baseline", "content_hash": "v1"},
            {"id": "2", "title": "Beta", "content": "unrelated weather chatter", "content_hash": "v2"},
        ]
        lexical = build_lexical_hits_from_records("lexical retrieval", records, kind="knowledge")
        self.assertTrue(lexical)
        merged = merge_rank(lexical, [], limit=4)
        self.assertEqual(merged.method, "lexical")
        self.assertIn("semantic_unavailable_lexical_fallback", merged.notes)

        store = EmbeddingStore(model_id=None, index_version=1)
        self.assertFalse(store.semantic_available())
        inspection = build_retrieval_inspection(
            query="lexical retrieval",
            hits=[h.to_dict() for h in lexical],
            method="hybrid",
            embedding_store=store,
            scope={"project_id": "demo"},
        )
        self.assertEqual(inspection.method, "lexical")
        self.assertFalse(inspection.semantic_available)
        self.assertTrue(inspection.passages)
        self.assertEqual(inspection.passages[0].citation["source_version"], "v1")
        self.assertIn("data", inspection.policy_note.lower())

    def test_embedding_index_state_model_and_hash(self) -> None:
        state = EmbeddingIndexState(embedding_model="m1", index_version=1)
        self.assertTrue(state.needs_reindex("s1", "hashA"))
        state.mark_indexed("s1", "hashA")
        self.assertFalse(state.needs_reindex("s1", "hashA"))
        self.assertTrue(state.needs_reindex("s1", "hashB"))
        state.set_model("m2")
        self.assertTrue(state.needs_reindex("s1", "hashA"))

    def test_measure_on_small_versioned_q_source_set(self) -> None:
        corpus = [
            {"id": "s1", "title": "Protocol", "content": "HADES uses offline-first retrieval", "content_hash": "verA"},
            {"id": "s2", "title": "Cooking", "content": "Bake bread at 220C", "content_hash": "verB"},
        ]
        cases = [
            {"query": "offline-first retrieval", "expected_source_version": "verA"},
            {"query": "bake bread", "expected_source_version": "verB"},
        ]

        def retrieve_fn(query: str, case: dict):
            hits = build_lexical_hits_from_records(query, corpus, kind="knowledge")
            packed, _meta = pack_hits_non_dumping(hits, max_hits=3, max_chars_total=2000)
            store = EmbeddingStore(model_id=None)
            return build_retrieval_inspection(
                query=query,
                hits=[h.to_dict() for h in packed],
                method="lexical",
                embedding_store=store,
            )

        metrics = measure_retrieval_quality(cases=cases, retrieve_fn=retrieve_fn)
        self.assertEqual(metrics["cases"], 2)
        self.assertGreaterEqual(metrics["hit_at_1"], 1.0)
        self.assertGreaterEqual(metrics["hit_at_3"], 1.0)


if __name__ == "__main__":
    unittest.main()
