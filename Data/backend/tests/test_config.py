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
        self.assertFalse(cfg.features.neuro_enabled)
        self.assertFalse(cfg.network.allow_outbound)
        self.assertEqual(cfg.knowledge.data_root, Path("D:/ModelData"))
        summary = cfg.public_summary()
        self.assertNotIn("api_key", str(summary))

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
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaises(ConfigurationError):
                Settings.from_env()

    def test_deep_recall_requires_rag_v3(self) -> None:
        env = {
            "LEVIATHAN_FEATURE_RAG_V3": "false",
            "LEVIATHAN_FEATURE_DEEP_RECALL": "true",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaises(ConfigurationError):
                Settings.from_env()

    def test_why_library_requires_rag_v3(self) -> None:
        env = {
            "LEVIATHAN_FEATURE_RAG_V3": "false",
            "LEVIATHAN_FEATURE_WHY_LIBRARY": "true",
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

    def test_rag_v3_defaults_embedding_provider_to_hash(self) -> None:
        env = {"LEVIATHAN_FEATURE_RAG_V3": "true"}
        with mock.patch.dict(os.environ, env, clear=False):
            cfg = Settings.from_env()
        self.assertTrue(cfg.features.rag_v3)
        self.assertEqual(cfg.knowledge.embedding_provider, "hash")
        summary = cfg.public_summary()
        self.assertTrue(summary["features"]["rag_v3"])

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
