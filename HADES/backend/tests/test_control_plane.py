"""Tests for the HADES control-plane: registry, resolver, unlimited, persistence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from control.capabilities import CapabilityRegistry
from control.definitions import create_default_registry
from control.presets import list_presets, preset_values
from control.resolver import PolicyResolver
from control.service import ControlService
from control.types import ConstraintKind, CapabilityDescriptor, ResolveContext, SettingScope
from control.validation import SettingValidationError, is_unlimited, validate_value
from database import Database
from reasoning.atomic_budget import SharedBudgetPool
from reasoning.budgets import ExecutionBudget, resolve_tool_round_budget


class ControlRegistryTests(unittest.TestCase):
    def test_registry_has_core_categories_and_unique_keys(self) -> None:
        registry = create_default_registry()
        categories = set(registry.categories())
        for required in {
            "agent_execution",
            "agent_autonomy",
            "agent_delegation",
            "tool_use",
            "reasoning",
            "context",
            "memory",
            "search",
            "filesystem",
            "terminal",
            "network",
            "plugins",
            "mcp",
            "concurrency",
            "resources",
            "logging",
        }:
            self.assertIn(required, categories)
        self.assertGreaterEqual(len(registry.all()), 100)
        keys = [d.storage_key for d in registry.all()]
        self.assertEqual(len(keys), len(set(keys)))

    def test_defaults_preserve_legacy_behavior(self) -> None:
        registry = create_default_registry()
        self.assertEqual(registry.require("tools.max_rounds").default_value, 3)
        self.assertEqual(registry.require("agents.execution.max_concurrent_tasks").default_value, 2)
        self.assertTrue(registry.require("tools.max_rounds").allow_unlimited)


class ValidationTests(unittest.TestCase):
    def test_unlimited_null(self) -> None:
        registry = create_default_registry()
        definition = registry.require("tools.max_rounds")
        self.assertTrue(is_unlimited(validate_value(definition, None)))

    def test_rejects_invalid_type(self) -> None:
        registry = create_default_registry()
        definition = registry.require("tools.max_rounds")
        with self.assertRaises(SettingValidationError):
            validate_value(definition, "banana")


class ResolverTests(unittest.TestCase):
    def test_inheritance_task_overrides_global(self) -> None:
        registry = create_default_registry()
        resolver = PolicyResolver(
            registry,
            global_values={"max_tool_rounds": 100},
            overrides=[
                {
                    "key": "max_tool_rounds",
                    "scope": SettingScope.AGENT_TYPE.value,
                    "scope_id": "coding",
                    "value": None,
                },
                {
                    "key": "max_tool_rounds",
                    "scope": SettingScope.TASK.value,
                    "scope_id": "task_1",
                    "value": 20,
                },
            ],
        )
        effective = resolver.resolve(
            "tools.max_rounds",
            ResolveContext(agent_type="coding", task_id="task_1"),
        )
        self.assertEqual(effective.configured, 20)
        self.assertEqual(effective.effective, 20)
        self.assertEqual(effective.scope, SettingScope.TASK)

    def test_capability_clamping_is_visible(self) -> None:
        registry = create_default_registry()
        caps = {
            "models.max_output_tokens": CapabilityDescriptor(
                id="models.max_output_tokens",
                kind=ConstraintKind.PROVIDER_LIMIT,
                label="Provider maximum",
                provider_max=32768,
            )
        }
        # Use a real setting id that we can clamp via capability keyed by id.
        resolver = PolicyResolver(
            registry,
            global_values={"profile_maximum_min_max_tokens": 65536},
            capabilities={
                "reasoning.profiles.maximum.min_max_tokens": CapabilityDescriptor(
                    id="reasoning.profiles.maximum.min_max_tokens",
                    kind=ConstraintKind.PROVIDER_LIMIT,
                    label="Provider maximum",
                    provider_max=32768,
                )
            },
        )
        result = resolver.resolve("reasoning.profiles.maximum.min_max_tokens")
        self.assertTrue(result.clamped)
        self.assertEqual(result.configured, 65536)
        self.assertEqual(result.effective, 32768)
        self.assertIsNotNone(result.clamp_reason)


class ControlServicePersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "hades.db"))
        self.db.initialize()
        self.service = ControlService(self.db)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_patch_persist_and_history(self) -> None:
        saved = self.service.patch_global({"max_tool_rounds": None})
        self.assertIsNone(saved["max_tool_rounds"])
        resolved = self.service.resolve("tools.max_rounds")
        self.assertTrue(resolved.unlimited_requested)
        self.assertIsNone(resolved.effective)
        history = self.service.history(key="max_tool_rounds", limit=5)
        self.assertTrue(history)
        self.assertIsNone(history[0]["new_value"])

    def test_scoped_override(self) -> None:
        self.service.patch_global({"max_tool_rounds": 10})
        self.service.set_override("tools.max_rounds", 2, scope="agent", scope_id="agent_a")
        global_eff = self.service.resolve("tools.max_rounds")
        agent_eff = self.service.resolve("tools.max_rounds", ResolveContext(agent_id="agent_a"))
        self.assertEqual(global_eff.effective, 10)
        self.assertEqual(agent_eff.effective, 2)

    def test_rejects_non_whole_float_integer(self) -> None:
        from control.validation import SettingValidationError, validate_value
        from control.types import SettingDefinition, SettingType

        definition = SettingDefinition(
            id="tools.max_rounds",
            storage_key="max_tool_rounds",
            category="tools",
            label="Max rounds",
            description="test",
            type=SettingType.INTEGER,
            default_value=8,
            min=0,
            max=100,
            allow_unlimited=True,
        )
        with self.assertRaises(SettingValidationError):
            validate_value(definition, 1.9)
        with self.assertRaises(SettingValidationError):
            validate_value(definition, "2.5")
        self.assertEqual(validate_value(definition, 2.0), 2)

    def test_preset_maximum_autonomy_sets_unlimited(self) -> None:
        result = self.service.apply_preset("maximum_autonomy")
        self.assertIn("max_tool_rounds", result["applied_keys"])
        self.assertIsNone(result["values"]["max_tool_rounds"])
        self.assertIsNone(result["values"]["max_model_calls_per_task"])
        self.assertIn("apply_modes", result)
        self.assertIn("immediate", result["apply_modes"])
        self.assertIn("run_config_snapshot", result)
        snap = result["run_config_snapshot"]
        self.assertGreater(snap.get("entry_count") or 0, 0)
        self.assertEqual(snap.get("config_version"), result.get("config_version"))

    def test_task_scope_does_not_leak_to_other_task(self) -> None:
        self.service.patch_global({"max_tool_rounds": 10})
        self.service.set_override("tools.max_rounds", 3, scope="task", scope_id="task_a")
        a = self.service.resolve("tools.max_rounds", ResolveContext(task_id="task_a"))
        b = self.service.resolve("tools.max_rounds", ResolveContext(task_id="task_b"))
        self.assertEqual(a.effective, 3)
        self.assertEqual(a.scope.value if hasattr(a.scope, "value") else a.scope, "task")
        self.assertEqual(b.effective, 10)
        self.assertNotEqual(b.scope.value if hasattr(b.scope, "value") else b.scope, "task")

    def test_export_redacts_secrets(self) -> None:
        exported = self.service.export_config(include_secrets=False)
        self.assertEqual(exported["values"]["lm_studio_api_key"], "***")

    def test_import_export_roundtrip(self) -> None:
        self.service.patch_global({"max_tool_rounds": 12, "max_subtasks": 16})
        payload = self.service.export_config(include_secrets=False)
        self.service.reset_all()
        self.service.import_config(payload)
        values = self.service.global_values()
        self.assertEqual(values["max_tool_rounds"], 12)
        self.assertEqual(values["max_subtasks"], 16)

    def test_import_fails_closed_on_bad_override(self) -> None:
        payload = {
            "config_schema_version": self.service.schema_version(),
            "values": {"max_tool_rounds": 8},
            "overrides": [
                {
                    "key": "tools.max_rounds",
                    "value": "not-an-int",
                    "scope": "task",
                    "scope_id": "task_bad",
                }
            ],
        }
        with self.assertRaises(SettingValidationError):
            self.service.import_config(payload)

    def test_cache_invalidation_bumps_version(self) -> None:
        before = self.service.cache_version
        self.service.patch_global({"max_parallel_steps": 4})
        self.assertGreater(self.service.cache_version, before)

    def test_limit_inspector_records_events(self) -> None:
        event = self.service.explain_stop(
            "tools.max_rounds",
            current=3,
            enforced_by="unit_test",
            message="test stop",
        )
        self.assertEqual(event["constraint_id"], "tools.max_rounds")
        recent = self.service.recent_limit_events(5)
        self.assertTrue(any(item["enforced_by"] == "unit_test" for item in recent))

    def test_schema_version(self) -> None:
        self.assertGreaterEqual(self.service.schema_version(), 1)


class BudgetUnlimitedTests(unittest.TestCase):
    def test_shared_pool_none_is_unlimited(self) -> None:
        pool = SharedBudgetPool()
        pool.configure({"max_tool_calls": None})
        for _ in range(50):
            self.assertTrue(pool.try_reserve("tool", 1))

    def test_resolve_tool_rounds_unlimited(self) -> None:
        self.assertIsNone(
            resolve_tool_round_budget(
                settings_max_tool_rounds=None,
                profile_max_tool_rounds=None,
                tools_allowed=True,
            )
        )
        budget = ExecutionBudget(max_model_calls=None, max_tool_rounds=None)
        self.assertTrue(budget.can_tool_round())
        self.assertTrue(budget.can_model_call())


class PresetTests(unittest.TestCase):
    def test_presets_are_plain_value_maps(self) -> None:
        presets = list_presets()
        ids = {item["id"] for item in presets}
        self.assertIn("maximum_autonomy", ids)
        values = preset_values("maximum_autonomy")
        self.assertIsNone(values["max_tool_rounds"])
        self.assertTrue(values["loop_detection_enabled"])


if __name__ == "__main__":
    unittest.main()
