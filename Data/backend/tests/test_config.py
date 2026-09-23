from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.backend.config import ConfigurationError, Settings


class SettingsTests(unittest.TestCase):
    def test_defaults_load_with_compat_accessors(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            # Ensure dotenv-less pure defaults for this unit test.
            cfg = Settings.from_env()
        self.assertEqual(cfg.llm_base_url, "http://127.0.0.1:1234/v1")
        self.assertIsNone(cfg.llm_model)
        self.assertTrue(cfg.reasoning_enabled)
        self.assertEqual(cfg.knowledge_top_k, 5)
        self.assertEqual(cfg.max_history_messages, 24)
        self.assertTrue(cfg.features.neuro_enabled)
        self.assertTrue(cfg.features.rag_v3)
        self.assertTrue(cfg.features.cognition_enabled)
        self.assertFalse(cfg.features.cognition_shadow)
        self.assertFalse(cfg.features.neuro_soak_long)
        self.assertFalse(cfg.network.allow_outbound)
        self.assertEqual(cfg.knowledge.data_root, Path("D:/ModelData"))
        summary = cfg.public_summary()
        self.assertNotIn("api_key", str(summary))

    def test_intelligence_defaults_matrix(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = Settings.from_env()
        f = cfg.features
        self.assertTrue(f.reasoning_iterative_retrieval)
        self.assertTrue(f.memory_semantic)
        self.assertTrue(f.neuro_enabled)
        self.assertTrue(f.neuro_associative_memory)
        self.assertTrue(f.neuro_process_critic)
        self.assertTrue(f.neuro_residual_injection)
        self.assertTrue(f.neuro_cortex)
        self.assertTrue(f.neuro_memory_tiers)
        self.assertTrue(f.neuro_residual_orchestrator)
        self.assertTrue(f.neuro_cortex_blocks)
        self.assertTrue(f.neuro_contrastive_training)
        self.assertFalse(f.neuro_soak_long)
        self.assertFalse(f.neuro_training_real_worker)
        self.assertTrue(f.rag_v3)
        self.assertTrue(f.deep_recall)
        self.assertTrue(f.why_library)
        self.assertTrue(f.residual_production)
        self.assertTrue(f.cognition_enabled)
        self.assertFalse(f.cognition_shadow)
        self.assertTrue(f.cognition_iterative_loop)
        self.assertTrue(f.cognition_belief_state)
        self.assertTrue(f.cognition_neuro)
        self.assertTrue(f.cognition_adaptive_depth)
        self.assertTrue(f.cognition_delegation)
        self.assertTrue(f.cognition_experience_learning)
        self.assertEqual(cfg.knowledge.embedding_provider, "auto")
        self.assertEqual(cfg.knowledge.rerank_policy, "auto")
        self.assertEqual(cfg.reasoning.default_mode, "adaptive")
        self.assertTrue(cfg.reasoning.allow_fast_path)
        self.assertEqual(cfg.reasoning.fast_max_model_calls, 1)
        self.assertEqual(cfg.reasoning.standard_max_model_calls, 3)
        self.assertEqual(cfg.reasoning.deep_max_model_calls, 6)
        self.assertEqual(cfg.reasoning.maximum_max_model_calls, 10)
        self.assertTrue(cfg.context.auto_budget)
        self.assertTrue(cfg.verification.factual_grounding)
        self.assertTrue(cfg.research_integration.auto_promote_verified_knowledge)
        self.assertTrue(cfg.research_integration.datasets_auto_index_ready_to_knowledge)
        self.assertFalse(cfg.network.allow_outbound)

    def test_invalid_boolean_fails_clearly(self) -> None:
        with mock.patch.dict(os.environ, {"LEVIATHAN_REASONING_ENABLED": "maybe"}, clear=False):
            with self.assertRaises(ConfigurationError):
                Settings.from_env()

    def test_invalid_top_k_fails_clearly(self) -> None:
        with mock.patch.dict(os.environ, {"LEVIATHAN_KNOWLEDGE_TOP_K": "0"}, clear=False):
            with self.assertRaises(ConfigurationError):
                Settings.from_env()

    def test_neuro_child_flag_requires_parent(self) -> None:
        env = {
            "LEVIATHAN_FEATURE_NEURO": "false",
            "LEVIATHAN_FEATURE_NEURO_RESIDUAL_INJECTION": "true",
            # Parent-gated siblings must also be off when neuro is forced off.
            "LEVIATHAN_FEATURE_NEURO_ASSOCIATIVE_MEMORY": "false",
            "LEVIATHAN_FEATURE_NEURO_PROCESS_CRITIC": "false",
            "LEVIATHAN_FEATURE_NEURO_CORTEX": "false",
            "LEVIATHAN_FEATURE_NEURO_MEMORY_TIERS": "false",
            "LEVIATHAN_FEATURE_NEURO_RESIDUAL_ORCHESTRATOR": "false",
            "LEVIATHAN_FEATURE_NEURO_CORTEX_BLOCKS": "false",
            "LEVIATHAN_FEATURE_NEURO_CONTRASTIVE_TRAINING": "false",
            "LEVIATHAN_FEATURE_RESIDUAL_PRODUCTION": "false",
            "LEVIATHAN_FEATURE_COGNITION_NEURO": "false",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaises(ConfigurationError):
                Settings.from_env()

    def test_deep_recall_requires_rag_v3(self) -> None:
        env = {
            "LEVIATHAN_FEATURE_RAG_V3": "false",
            "LEVIATHAN_FEATURE_DEEP_RECALL": "true",
            "LEVIATHAN_FEATURE_WHY_LIBRARY": "false",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaises(ConfigurationError):
                Settings.from_env()

    def test_why_library_requires_rag_v3(self) -> None:
        env = {
            "LEVIATHAN_FEATURE_RAG_V3": "false",
            "LEVIATHAN_FEATURE_WHY_LIBRARY": "true",
            "LEVIATHAN_FEATURE_DEEP_RECALL": "false",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaises(ConfigurationError):
                Settings.from_env()

    def test_residual_production_requires_neuro_and_injection(self) -> None:
        env = {
            "LEVIATHAN_FEATURE_NEURO": "true",
            "LEVIATHAN_FEATURE_NEURO_RESIDUAL_INJECTION": "false",
            "LEVIATHAN_FEATURE_RESIDUAL_PRODUCTION": "true",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaises(ConfigurationError):
                Settings.from_env()

    def test_rag_v3_defaults_embedding_provider_to_auto(self) -> None:
        env = {"LEVIATHAN_FEATURE_RAG_V3": "true"}
        with mock.patch.dict(os.environ, env, clear=False):
            cfg = Settings.from_env()
        self.assertTrue(cfg.features.rag_v3)
        self.assertEqual(cfg.knowledge.embedding_provider, "auto")
        summary = cfg.public_summary()
        self.assertTrue(summary["features"]["rag_v3"])

    def test_embedding_provider_hash_still_valid_when_set(self) -> None:
        env = {
            "LEVIATHAN_FEATURE_RAG_V3": "true",
            "LEVIATHAN_EMBEDDING_PROVIDER": "hash",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            cfg = Settings.from_env()
        self.assertEqual(cfg.knowledge.embedding_provider, "hash")

    def test_loopback_only_rejects_non_loopback_host(self) -> None:
        env = {
            "LEVIATHAN_LOOPBACK_ONLY": "true",
            "LEVIATHAN_HOST": "0.0.0.0",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaises(ConfigurationError):
                Settings.from_env()

    def test_relative_database_path_resolves_under_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rel = "Data/backend/data/custom.db"
            with mock.patch.dict(os.environ, {"LEVIATHAN_DATABASE_PATH": rel}, clear=False):
                cfg = Settings.from_env()
            self.assertTrue(cfg.database_path.is_absolute())
            self.assertTrue(str(cfg.database_path).endswith(rel.replace("/", os.sep)) or rel in str(cfg.database_path))
            self.assertIn("custom.db", str(cfg.database_path))
            self.assertTrue(Path(tmp).exists())


if __name__ == "__main__":
    unittest.main()
