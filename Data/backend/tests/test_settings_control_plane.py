"""Settings Control Plane tests — persistence, secrets, hierarchy, duplicates."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.backend.config import Settings
from Data.backend.migrations import MigrationRunner
from Data.modules.settings import CATALOG, CATALOG_BY_KEY, SettingsControlPlane, SettingsError
from Data.modules.settings.catalog import build_catalog
from Data.modules.settings.service import apply_overrides_to_settings


class SettingsCatalogTests(unittest.TestCase):
    def test_catalog_keys_are_unique(self) -> None:
        keys = [item.key for item in CATALOG]
        self.assertEqual(len(keys), len(set(keys)))
        rebuilt = build_catalog()
        self.assertEqual([i.key for i in rebuilt], keys)

    def test_every_setting_has_owner_and_category(self) -> None:
        for item in CATALOG:
            self.assertTrue(item.consumer, msg=item.key)
            self.assertTrue(item.category, msg=item.key)
            self.assertTrue(item.path, msg=item.key)


class SettingsControlPlaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "leviathan.db"
        env = {
            "LEVIATHAN_DATABASE_PATH": str(self.db_path),
            "LEVIATHAN_LOOPBACK_ONLY": "true",
            "LEVIATHAN_HOST": "127.0.0.1",
        }
        self.env_patch = mock.patch.dict(os.environ, env, clear=False)
        self.env_patch.start()
        MigrationRunner(self.db_path).apply_all()
        self.boot = Settings.from_env()
        self.plane = SettingsControlPlane(self.boot)
        self.plane.start()

    def tearDown(self) -> None:
        self.env_patch.stop()
        self.tmp.cleanup()

    def test_hot_apply_persists_and_survives_reload(self) -> None:
        results = self.plane.patch_many({"knowledge.top_k": 11})
        self.assertEqual(results[0].status.value, "APPLIED")
        self.assertEqual(self.plane.effective.knowledge.top_k, 11)

        reloaded = SettingsControlPlane(Settings.from_env())
        reloaded.start()
        self.assertEqual(reloaded.effective.knowledge.top_k, 11)
        self.assertEqual(reloaded.get_state("knowledge.top_k").source, "override")

    def test_restart_required_keeps_effective_until_boot_merge(self) -> None:
        results = self.plane.patch_many({"runtime.port": 9001})
        self.assertEqual(results[0].status.value, "RESTART_REQUIRED")
        self.assertEqual(self.plane.effective.runtime.port, self.boot.runtime.port)
        self.assertEqual(self.plane.desired.runtime.port, 9001)
        state = self.plane.get_state("runtime.port")
        self.assertFalse(state.effective_now)
        self.assertEqual(state.status, "restart_required")

        # Simulate process restart: load_settings merges overrides into boot.
        merged = apply_overrides_to_settings(Settings.from_env(), {"runtime.port": 9001})
        self.assertEqual(merged.runtime.port, 9001)

    def test_secret_redacted_in_public_dict(self) -> None:
        self.plane.patch_many({"model.api_key": "sk-secret-value"})
        public = self.plane.get_state("model.api_key").public_dict()
        self.assertTrue(public["configured"])
        self.assertIsNone(public["effective_value"])
        self.assertIsNone(public["desired_value"])
        blob = str(self.plane.public_snapshot())
        self.assertNotIn("sk-secret-value", blob)

    def test_feature_hierarchy_coding_requires_agents(self) -> None:
        with self.assertRaises(SettingsError) as ctx:
            self.plane.patch_many({"features.coding_enabled": True})
        self.assertEqual(ctx.exception.code, "FEATURE_DEPENDENCY")

    def test_feature_hierarchy_mcp_stdio_requires_mcp(self) -> None:
        with self.assertRaises(SettingsError):
            self.plane.patch_many({"features.mcp_stdio": True})

    def test_feature_hierarchy_deep_recall_requires_rag(self) -> None:
        with self.assertRaises(SettingsError):
            self.plane.patch_many({"features.deep_recall": True})

    def test_cognition_child_requires_parent(self) -> None:
        with self.assertRaises(SettingsError):
            self.plane.patch_many({"features.cognition_shadow": True})

    def test_neuro_child_requires_parent(self) -> None:
        with self.assertRaises(SettingsError):
            self.plane.patch_many({"features.neuro_residual_injection": True})

    def test_dangerous_requires_confirmation(self) -> None:
        with self.assertRaises(SettingsError) as ctx:
            self.plane.patch_many({"network.allow_outbound": True})
        self.assertEqual(ctx.exception.code, "CONFIRM_REQUIRED")
        results = self.plane.patch_many({"network.allow_outbound": True}, confirm_dangerous=True)
        self.assertEqual(results[0].status.value, "APPLIED")
        self.assertTrue(self.plane.effective.network.allow_outbound)

    def test_bootstrap_database_path_locked(self) -> None:
        with self.assertRaises(SettingsError):
            self.plane.patch_many({"database_path": "Data/other.db"})

    def test_unknown_key_rejected(self) -> None:
        with self.assertRaises(SettingsError):
            self.plane.patch_many({"not.a.real.key": 1})

    def test_reset_restores_default(self) -> None:
        self.plane.patch_many({"knowledge.top_k": 12})
        self.plane.reset_key("knowledge.top_k")
        self.assertEqual(self.plane.effective.knowledge.top_k, self.boot.knowledge.top_k)

    def test_editable_categories_have_no_duplicate_keys(self) -> None:
        seen: dict[str, str] = {}
        for item in CATALOG:
            if not item.editable:
                continue
            self.assertNotIn(item.key, seen)
            seen[item.key] = item.category


class SettingsMigrationTests(unittest.TestCase):
    def test_migration_20_creates_overrides_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "db.sqlite"
            applied = MigrationRunner(path).apply_all()
            self.assertIn(20, applied)
            import sqlite3

            conn = sqlite3.connect(path)
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE name='settings_overrides'"
            ).fetchone()
            conn.close()
            self.assertIsNotNone(row)


if __name__ == "__main__":
    unittest.main()
