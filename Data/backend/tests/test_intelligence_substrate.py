"""Tests for unified intelligence substrate (policy, health, assimilation)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from Data.backend.config import Settings
from Data.modules.cognition.meta_controller import MetaController
from Data.modules.cognition.task_model import TaskModelBuilder
from Data.modules.cognition.types import ReasoningMode
from Data.modules.intelligence import (
    IntelligenceHealthService,
    KnowledgeAssimilationService,
    ReasoningPolicy,
)
from Data.modules.knowledge.store import KnowledgeStore


class ReasoningPolicyTests(unittest.TestCase):
    def test_from_settings_reads_defaults(self) -> None:
        cfg = Settings.from_env()
        policy = ReasoningPolicy.from_settings(cfg)
        self.assertEqual(policy.default_mode, "adaptive")
        self.assertTrue(policy.allow_fast_path)
        self.assertEqual(policy.uncertainty_deep_threshold, 0.75)
        self.assertEqual(policy.budget_for("FAST")["max_model_calls"], 1)
        self.assertEqual(policy.budgets_for("STANDARD")["max_model_calls"], 3)
        self.assertEqual(policy.budget_for("DEEP")["max_model_calls"], 6)
        self.assertTrue(policy.public_dict()["truth"]["modes_control_real_budgets"])


class MetaControllerPolicyTests(unittest.TestCase):
    def test_uses_policy_budgets(self) -> None:
        cfg = Settings.from_env()
        # Mutate flat budget field via a lightweight stand-in settings object.
        reasoning = SimpleNamespace(**{**cfg.reasoning.__dict__, "fast_max_model_calls": 7})
        settings = SimpleNamespace(reasoning=reasoning)
        policy = ReasoningPolicy.from_settings(settings)
        self.assertEqual(policy.budget_for("FAST")["max_model_calls"], 7)

        meta = MetaController(policy=policy)
        task = TaskModelBuilder().build("hi")
        decision = meta.decide(task, user_requested_depth="FAST")
        self.assertEqual(decision.mode, ReasoningMode.FAST)
        self.assertEqual(decision.budgets.max_model_calls, 7)

    def test_set_policy_hot_swap(self) -> None:
        meta = MetaController()
        task = TaskModelBuilder().build("hi")
        baseline = meta.decide(task, user_requested_depth="FAST")
        self.assertEqual(baseline.budgets.max_model_calls, 1)

        policy = ReasoningPolicy(
            mode_budgets={
                "FAST": {
                    "max_wall_time_seconds": 30.0,
                    "max_model_calls": 9,
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
        self.assertEqual(updated.budgets.max_model_calls, 9)

    def test_allow_fast_path_false_escalates(self) -> None:
        policy = ReasoningPolicy(allow_fast_path=False)
        meta = MetaController(policy=policy)
        task = TaskModelBuilder().build("hi")
        decision = meta.decide(task)
        self.assertEqual(decision.mode, ReasoningMode.STANDARD)

    def test_adaptive_falls_through_to_heuristics(self) -> None:
        meta = MetaController(policy=ReasoningPolicy(default_mode="adaptive"))
        task = TaskModelBuilder().build("hi")
        decision = meta.decide(task, user_requested_depth="ADAPTIVE")
        self.assertEqual(decision.mode, ReasoningMode.FAST)


class IntelligenceHealthTests(unittest.TestCase):
    def test_residual_desired_true_effective_false_when_unsupported(self) -> None:
        settings = SimpleNamespace(
            features=SimpleNamespace(
                neuro_residual_injection=True,
                residual_production=False,
                neuro_residual_orchestrator=False,
                neuro_enabled=True,
                cognition_enabled=False,
                cognition_iterative_loop=False,
                cognition_belief_state=False,
                cognition_experience_learning=False,
                rag_v3=False,
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

        health = IntelligenceHealthService(
            settings=settings,
            residual_port=_Port(),
            reasoning_policy=ReasoningPolicy.from_settings(settings),
        )
        payload = health.build()
        residual = payload["residual"]
        self.assertTrue(residual["desired"])
        self.assertFalse(residual["effective"])
        self.assertTrue(residual.get("degraded") or residual.get("degraded_reason"))
        summary = payload["stack_summary"]
        self.assertIn(summary["residual"], {"OFF", "DEGRADED"})


class KnowledgeAssimilationTests(unittest.TestCase):
    def test_research_promotion_rejects_claim_without_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "knowledge.db"
            store = KnowledgeStore(db)
            store.initialize()
            svc = KnowledgeAssimilationService(
                database_path=Path(tmp) / "intel.db",
                knowledge_store=store,
            )
            claim = {
                "claim_id": "c1",
                "proposition": "Unsupported speculation",
                "status": "supported",
                "supporting_evidence_ids": [],
            }
            receipt = svc.assimilate_research_project(
                {"project_id": "p1", "title": "Probe"},
                claims=[claim],
            )
            self.assertFalse(receipt.ok)
            self.assertEqual(receipt.success_count, 0)
            self.assertEqual(receipt.skipped_count, 1)
            self.assertEqual(receipt.skipped[0]["reason"], "no_evidence_links")
            self.assertEqual(len(store.list_documents(limit=10)), 0)

    def test_research_promotion_accepts_supported_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "knowledge.db"
            store = KnowledgeStore(db)
            store.initialize()
            svc = KnowledgeAssimilationService(
                database_path=Path(tmp) / "intel.db",
                knowledge_store=store,
            )
            claim = {
                "claim_id": "c2",
                "proposition": "Local agents can own chat responses",
                "status": "supported",
                "supporting_evidence_ids": ["e1"],
                "source_diversity": 2,
            }
            evidence = [
                {
                    "evidence_id": "e1",
                    "span_text": "CognitiveRuntime returns response_ownership=cognition",
                }
            ]
            receipt = svc.assimilate_research_project(
                {"project_id": "p2", "title": "Cognition"},
                claims=[claim],
                evidence=evidence,
            )
            self.assertTrue(receipt.ok)
            self.assertEqual(receipt.success_count, 1)
            self.assertEqual(receipt.failure_count, 0)
            docs = store.list_documents(limit=10)
            self.assertEqual(len(docs), 1)
            self.assertIn("Local agents can own chat responses", docs[0].content)


if __name__ == "__main__":
    unittest.main()
