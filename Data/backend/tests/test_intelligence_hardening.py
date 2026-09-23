"""Hardening tests: auto budgets, MMR diversity, expansions, consumer_truth."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from Data.modules.context import ContextBuilder
from Data.modules.cognition.context_v3 import ContextBuilderV3
from Data.modules.cognition.task_model import TaskModelBuilder
from Data.modules.intelligence import IntelligenceHealthService, ReasoningPolicy
from Data.modules.knowledge import (
    HybridRetriever,
    KnowledgeStore,
    RetrievalHit,
    RetrievalQuery,
    StagedRetriever,
    build_embedding_provider,
)
from Data.modules.reasoning import ReasoningEngine


class AutoBudgetTests(unittest.TestCase):
    def test_fixed_fallback_when_no_window(self) -> None:
        builder = ContextBuilder(
            token_budget=4000,
            reserve_response_tokens=500,
            auto_budget=True,
            max_context_fraction=0.72,
            reserve_response_fraction=0.18,
        )
        resolved = builder.resolve_budgets()
        self.assertFalse(resolved["auto_budget_applied"])
        self.assertEqual(resolved["usable_budget"], 3500)
        self.assertEqual(builder.usable_budget, 3500)

    def test_auto_fraction_when_window_known(self) -> None:
        builder = ContextBuilder(
            token_budget=4000,
            reserve_response_tokens=500,
            auto_budget=True,
            max_context_fraction=0.5,
            reserve_response_fraction=0.2,
            minimum_response_tokens=256,
            model_context_window=8000,
        )
        resolved = builder.resolve_budgets()
        self.assertTrue(resolved["auto_budget_applied"])
        self.assertEqual(resolved["usable_budget"], 4000)  # 8000 * 0.5
        self.assertGreaterEqual(resolved["reserve_response_tokens"], 256)

    def test_build_records_budget_resolution(self) -> None:
        plan = ReasoningEngine().analyze("budget", has_knowledge=False)
        pack = ContextBuilder(
            token_budget=2000,
            reserve_response_tokens=200,
            auto_budget=True,
            model_context_window=10000,
            max_context_fraction=0.6,
        ).build(
            history=[{"role": "user", "content": "hi"}],
            knowledge=[],
            plan=plan,
        )
        br = pack.provenance.get("budget_resolution") or {}
        self.assertTrue(br.get("auto_budget_applied"))
        self.assertEqual(br.get("model_context_window"), 10000)

    def test_context_v3_shares_resolver(self) -> None:
        v3 = ContextBuilderV3(
            token_budget=3000,
            reserve_response_tokens=300,
            auto_budget=True,
            model_context_window=9000,
            max_context_fraction=0.4,
        )
        resolved = v3.resolve_budgets()
        self.assertTrue(resolved["auto_budget_applied"])
        self.assertEqual(resolved["usable_budget"], 3600)
        task = TaskModelBuilder().build("hello")
        result = v3.build(task=task)
        self.assertIn("budget_resolution", result.pack.provenance)


class MmrDiversityTests(unittest.TestCase):
    def test_mmr_prefers_exact_then_diversifies(self) -> None:
        hits = [
            RetrievalHit(
                document_id="d1",
                chunk_id="c1",
                chunk_index=0,
                title="A",
                source="t",
                content="alpha beta gamma unique phrase here",
                score=0.9,
                modality="lexical",
                original_path=None,
                document_hash=None,
                chunk_hash="h1",
            ),
            RetrievalHit(
                document_id="d1",
                chunk_id="c2",
                chunk_index=1,
                title="A2",
                source="t",
                content="alpha beta gamma nearly duplicate wording",
                score=0.88,
                modality="lexical",
                original_path=None,
                document_hash=None,
                chunk_hash="h2",
            ),
            RetrievalHit(
                document_id="d2",
                chunk_id="c3",
                chunk_index=0,
                title="B",
                source="t",
                content="completely different topic about widgets",
                score=0.7,
                modality="lexical",
                original_path=None,
                document_hash=None,
                chunk_hash="h3",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            store = KnowledgeStore(Path(tmp) / "k.db")
            store.initialize()
            retriever = HybridRetriever(
                store,
                diversity_enabled=True,
                diversity_strength=0.8,
            )
            selected = retriever._mmr_select(  # noqa: SLF001
                hits,
                query_text="alpha beta gamma unique phrase here",
                limit=2,
                strength=0.8,
            )
            self.assertEqual(len(selected), 2)
            # Exact query match pinned first.
            self.assertEqual(selected[0].chunk_id, "c1")
            # Second should prefer different doc over near-duplicate.
            self.assertEqual(selected[1].chunk_id, "c3")


class QueryExpansionTests(unittest.TestCase):
    def test_simple_expansions_generate_multiple(self) -> None:
        expansions = StagedRetriever._simple_expansions(
            "how does leviathan staged retrieval work exactly",
            conversation_terms=["hybrid"],
            max_expansions=4,
        )
        self.assertGreaterEqual(len(expansions), 3)
        self.assertEqual(expansions[0], "how does leviathan staged retrieval work exactly")
        # Cap = original + max_expansions
        self.assertLessEqual(len(expansions), 5)

    def test_expansion_disabled_skips_stage_c(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            embeddings = build_embedding_provider(kind="hash", hash_dimensions=32)
            store = KnowledgeStore(
                root / "k.db",
                data_root=root / "data",
                chunk_max_chars=400,
                chunk_overlap=40,
                embedding_provider=embeddings,
            )
            store.initialize()
            # One weak lexical hit → coverage low (not empty, not high).
            store.upsert_document(
                title="weak",
                content="something about widgets and gadgets in general",
                source="test",
            )
            hybrid = HybridRetriever(store, embeddings=embeddings)
            staged = StagedRetriever(
                hybrid,
                rerank_policy="off",
                query_expansion=False,
                early_exit_enabled=False,
            )
            result = staged.search("widgets gadgets obscure zzqx", limit=5)
            self.assertEqual(result.coverage, "low")
            stage_c = next(s for s in result.stages if s.stage == "C")
            self.assertEqual(stage_c.action, "skip")
            self.assertIn("disabled", stage_c.detail.get("reason", ""))


class ConsumerTruthApiTests(unittest.TestCase):
    def test_health_exposes_consumer_truth_list(self) -> None:
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
                rag_v3=True,
                deep_recall=False,
                why_library=False,
                memory_semantic=False,
                neuro_cortex=False,
                neuro_cortex_blocks=False,
                neuro_associative_memory=False,
                neuro_process_critic=False,
            ),
            reasoning=SimpleNamespace(
                enabled=True,
                default_mode="adaptive",
                allow_fast_path=True,
                require_verification_for_high_risk=True,
            ),
            knowledge=SimpleNamespace(
                embedding_provider="null", embedding_model=None, reranker_model=None
            ),
            neuro_runtime=SimpleNamespace(residual_kind="unsupported"),
        )

        class _Port:
            def supports_residuals(self) -> bool:
                return False

        health = IntelligenceHealthService(
            settings=settings,
            residual_port=_Port(),
            retriever=object(),
            reasoning_policy=ReasoningPolicy.from_settings(settings),
        )
        payload = health.build()
        self.assertIn("consumer_truth", payload)
        self.assertIsInstance(payload["consumer_truth"], list)
        self.assertGreaterEqual(len(payload["consumer_truth"]), 5)
        keys = {item["feature_key"] for item in payload["consumer_truth"]}
        self.assertIn("features.rag_v3", keys)
        self.assertIn("features.neuro_residual_injection", keys)
        residual = next(
            item
            for item in payload["consumer_truth"]
            if item["feature_key"] == "features.neuro_residual_injection"
        )
        self.assertTrue(residual["desired"])
        self.assertFalse(residual["effective"])
        self.assertTrue(residual["degraded"])


if __name__ == "__main__":
    unittest.main()
