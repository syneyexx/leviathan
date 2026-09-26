"""Acceptance smoke tests for unified intelligence scenarios (unit level)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from Data.modules.cognition.experience import ExperienceStore
from Data.modules.cognition.meta_controller import MetaController
from Data.modules.cognition.perception import PerceptionService
from Data.modules.cognition.task_model import TaskModelBuilder
from Data.modules.cognition.types import CognitiveRunStatus, EpistemicType, ReasoningMode, ReasoningStrategy
from Data.modules.intelligence import (
    IntelligenceHealthService,
    KnowledgeAssimilationService,
    ReasoningPolicy,
)
from Data.modules.knowledge import (
    HybridRetriever,
    KnowledgeStore,
    RetrievalQuery,
    StagedRetriever,
    build_embedding_provider,
)


class ScenarioADatasetKnowledge(unittest.TestCase):
    """Upsert knowledge with dataset provenance → retriever finds it → provenance retained."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        embeddings = build_embedding_provider(kind="hash", hash_dimensions=32)
        self.store = KnowledgeStore(
            self.root / "k.db",
            data_root=self.root / "data",
            chunk_max_chars=400,
            chunk_overlap=40,
            embedding_provider=embeddings,
        )
        self.store.initialize()
        self.hybrid = HybridRetriever(self.store, embeddings=embeddings)
        self.staged = StagedRetriever(self.hybrid, rerank_policy="off")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_dataset_provenance_retained_through_hybrid_and_staged(self) -> None:
        trust = {
            "trust": "dataset",
            "datasetId": "ds-alpha",
            "versionId": "ver-1",
            "recordId": "rec-9",
            "scope": "dataset",
        }
        unique = "leviathan_scenario_a_token_xyzzy"
        doc = self.store.upsert_document(
            title="dataset/ds-alpha/rec-9",
            content=f"Dataset fact for retrieval: {unique} describes local indexing.",
            source="dataset:dataset",
            document_id="dataset:ds-alpha:ver-1:rec-9",
            trust_metadata=trust,
        )
        self.assertEqual(doc.document_id, "dataset:ds-alpha:ver-1:rec-9")

        hybrid_hits = self.hybrid.search(
            RetrievalQuery(text=unique, limit=5, use_embeddings=True, use_reranker=False)
        )
        self.assertGreaterEqual(len(hybrid_hits), 1)
        hit = hybrid_hits[0]
        self.assertEqual(hit.document_id, doc.document_id)
        hit_trust = (hit.provenance or {}).get("trust_metadata") or {}
        self.assertEqual(hit_trust.get("datasetId"), "ds-alpha")
        self.assertEqual(hit_trust.get("versionId"), "ver-1")
        self.assertEqual(hit_trust.get("recordId"), "rec-9")

        staged = self.staged.search(unique, limit=5)
        self.assertGreaterEqual(len(staged.hits), 1)
        staged_trust = (staged.hits[0].provenance or {}).get("trust_metadata") or {}
        self.assertEqual(staged_trust.get("datasetId"), "ds-alpha")


class ScenarioBResearchPromotionThin(unittest.TestCase):
    """Thin pointer — detailed promotion covered in test_intelligence_assimilation."""

    def test_assimilation_rejects_contradicted_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "knowledge.db"
            store = KnowledgeStore(db)
            store.initialize()
            svc = KnowledgeAssimilationService(
                database_path=Path(tmp) / "intel.db",
                knowledge_store=store,
            )
            receipt = svc.assimilate_research_project(
                {"project_id": "p-b", "title": "Thin"},
                claims=[
                    {
                        "claim_id": "c-b",
                        "proposition": "Should not promote",
                        "status": "disputed",
                        "supporting_evidence_ids": ["e1"],
                        "contradicting_evidence_ids": ["e2"],
                    }
                ],
                evidence=[{"evidence_id": "e1", "span_text": "span"}],
            )
            self.assertEqual(receipt.success_count, 0)
            self.assertIn("contradicted", {s.get("reason") for s in receipt.skipped})


class ScenarioCContradictionSupersession(unittest.TestCase):
    """Conflict preserved: contradicted claims are not promoted (gate retains conflict)."""

    def test_conflict_reason_preserved_on_skip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = KnowledgeStore(Path(tmp) / "k.db")
            store.initialize()
            svc = KnowledgeAssimilationService(knowledge_store=store)
            receipt = svc.assimilate_research_project(
                {"project_id": "p-c", "title": "Conflict"},
                claims=[
                    {
                        "claim_id": "old",
                        "proposition": "A is true",
                        "status": "supported",
                        "supporting_evidence_ids": ["e1"],
                    },
                    {
                        "claim_id": "new",
                        "proposition": "A is false",
                        "status": "disputed",
                        "supporting_evidence_ids": ["e2"],
                        "contradicting_evidence_ids": ["e1"],
                        "metadata": {"supersedes": "old", "conflict_with": "old"},
                    },
                ],
                evidence=[
                    {"evidence_id": "e1", "span_text": "supports A"},
                    {"evidence_id": "e2", "span_text": "supports not-A"},
                ],
            )
            # Supported claim may promote; disputed/contradicted must be skipped with reason.
            skipped = {s.get("claim_id"): s.get("reason") for s in receipt.skipped}
            self.assertEqual(skipped.get("new"), "contradicted")
            self.assertNotIn("new", receipt.document_ids)
            # Conflict metadata on the claim is retained in the skip path (not silently dropped as success).
            self.assertTrue(
                any(s.get("reason") == "contradicted" for s in receipt.skipped),
                msg="contradiction must remain visible on the assimilation receipt",
            )


class ScenarioDResidualUnavailable(unittest.TestCase):
    """Unsupported residual → neuro/rag/cognition desired on, residual degraded."""

    def test_residual_degraded_while_peers_desired(self) -> None:
        settings = SimpleNamespace(
            features=SimpleNamespace(
                neuro_residual_injection=True,
                residual_production=False,
                neuro_residual_orchestrator=False,
                neuro_enabled=True,
                cognition_enabled=True,
                cognition_iterative_loop=True,
                cognition_belief_state=True,
                cognition_experience_learning=False,
                rag_v3=True,
                deep_recall=False,
                why_library=False,
                memory_semantic=False,
                neuro_cortex=False,
                neuro_cortex_blocks=False,
                neuro_associative_memory=False,
                neuro_process_critic=False,
            ),
            reasoning=SimpleNamespace(enabled=True, default_mode="adaptive", allow_fast_path=True),
            knowledge=SimpleNamespace(embedding_provider="null", embedding_model=None, reranker_model=None),
            neuro_runtime=SimpleNamespace(residual_kind="unsupported"),
        )

        class _Port:
            def supports_residuals(self) -> bool:
                return False

        class _Runtime:
            def health(self) -> dict:
                return {"enabled": True, "experience_learning": False}

        health = IntelligenceHealthService(
            settings=settings,
            residual_port=_Port(),
            cognition_runtime=_Runtime(),
            retriever=object(),
            neuro_advisor=SimpleNamespace(enabled=True, residual_port=_Port()),
            reasoning_policy=ReasoningPolicy.from_settings(settings),
        )
        payload = health.build()
        self.assertTrue(payload["neuro"]["desired"])
        self.assertTrue(payload["rag"]["desired"])
        self.assertTrue(payload["cognition"]["desired"])
        residual = payload["residual"]
        self.assertTrue(residual["desired"])
        self.assertFalse(residual["effective"])
        self.assertTrue(residual.get("degraded") or residual.get("degraded_reason"))
        summary = payload["stack_summary"]
        self.assertIn(summary["residual"], {"OFF", "DEGRADED", "UNSUPPORTED"})
        self.assertIn("residual", summary.get("degraded_sections") or summary.get("critical_degraded") or [])


class ScenarioEMetaControllerHotPolicy(unittest.TestCase):
    """MetaController policy HOT change reflects in budgets."""

    def test_set_policy_hot_swap_budgets(self) -> None:
        meta = MetaController()
        # Use TOOL_REQUIRED so DIRECT hard-caps do not mask policy hot-swap.
        task = TaskModelBuilder().build("Calculate 17 * 23 precisely")
        baseline = meta.decide(task, user_requested_depth="FAST")
        self.assertEqual(baseline.budgets.max_model_calls, 1)

        policy = ReasoningPolicy(
            mode_budgets={
                "FAST": {
                    "max_wall_time_seconds": 30.0,
                    "max_model_calls": 11,
                    "max_model_tokens": 2000,
                    "max_tool_calls": 0,
                    "max_agent_delegations": 0,
                    "max_replans": 0,
                    "max_retries": 1,
                    "max_retrieval_rounds": 1,
                    "max_parallel_workers": 1,
                    "max_context_tokens": 3000,
                    "max_critic_passes": 0,
                    "max_iterations": 2,
                }
            }
        )
        meta.set_policy(policy)
        updated = meta.decide(task, user_requested_depth="FAST")
        self.assertEqual(updated.mode, ReasoningMode.FAST)
        self.assertEqual(updated.budgets.max_model_calls, 11)


class ExperienceLearningClosedLoop(unittest.TestCase):
    """Procedural hints surface as low-confidence CONTEXT, not FACT."""

    def test_procedural_hints_as_context_not_fact(self) -> None:
        store = ExperienceStore()
        task = TaskModelBuilder().build("Fix reconnect race with tests")
        exp = store.build_from_run(
            task=task,
            status=CognitiveRunStatus.COMPLETED_VERIFIED,
            strategy=ReasoningStrategy.CODING_REPAIR,
            action_summaries=["RETRIEVE", "VERIFY"],
            verification_status="PASSED",
            evidence_refs=["ev-1"],
        )
        admitted = store.admit(exp)
        self.assertTrue(admitted.admitted)
        hints = store.procedural_hints(domain=task.domain)
        self.assertTrue(hints)

        perception = PerceptionService(experience_store=store)
        snap = perception.perceive(
            "reconnect race",
            experience_learning=True,
            domain=task.domain,
        )
        context_items = [
            i
            for i in snap.items
            if (i.payload or {}).get("kind") == "procedural_experience_context"
        ]
        self.assertTrue(context_items)
        for item in context_items:
            self.assertEqual(item.source_type, EpistemicType.HYPOTHESIS)
            self.assertLessEqual(item.confidence, 0.4)
            self.assertNotEqual(item.source_type, EpistemicType.EXACT_FACT)
            self.assertTrue(item.payload.get("not_fact"))

    def test_active_learning_candidate_not_auto_train(self) -> None:
        store = ExperienceStore()
        cand = store.record_active_learning_candidate(
            {
                "run_id": "r1",
                "domain": "coding",
                "reason": "verification_failed",
                "kind": "failure",
                "uncertainty": 0.9,
            }
        )
        self.assertTrue(cand["auto_promote_forbidden"])
        self.assertTrue(cand["requires_human_or_policy_approval"])
        listed = store.training_candidates()
        self.assertTrue(any(c.get("run_id") == "r1" for c in listed))
        self.assertTrue(all(c.get("auto_promote_forbidden") for c in listed))


if __name__ == "__main__":
    unittest.main()
