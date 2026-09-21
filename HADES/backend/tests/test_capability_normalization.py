from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from capability_intel.normalize import adapt_package, normalize_legacy_plugin
from capability_intel.registry import CapabilityRegistry
from capability_intel.service import reset_service
from capability_intel.taxonomy import CAPABILITY_KINDS, CONTRACT_VERSION


class CapabilityNormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_service()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        reset_service()
        self.tmp.cleanup()

    def test_taxonomy_is_first_class(self) -> None:
        self.assertEqual(
            CAPABILITY_KINDS,
            ("skill", "knowledge", "tool", "tool_provider", "mcp_provider", "agent", "service", "workflow", "resource"),
        )
        self.assertGreaterEqual(CONTRACT_VERSION, 1)

    def test_legacy_tool_manifest_normalizes_to_tools_and_provider(self) -> None:
        plugin = {
            "id": "legacy-search",
            "name": "Legacy Search",
            "plugin_type": "tool",
            "version": "1.0.0",
            "enabled": True,
            "status": "ready",
            "trust": "verified",
            "permissions": ["subprocess"],
            "manifest": {
                "plugin_type": "tool",
                "tools": [
                    {
                        "name": "search",
                        "description": "Search files",
                        "input_schema": {"type": "object"},
                        "capabilities": {"effects": ["read_files"], "side_effect_class": "read", "cost_class": "cheap"},
                    }
                ],
            },
        }
        (self.root / "hades-plugin.json").write_text(json.dumps(plugin["manifest"]), encoding="utf-8")
        plugin["local_path"] = str(self.root)
        result = normalize_legacy_plugin(plugin, tools=plugin["manifest"]["tools"])
        kinds = {item.kind for item in result.capabilities}
        self.assertIn("tool", kinds)
        self.assertIn("tool_provider", kinds)
        tool = next(item for item in result.capabilities if item.kind == "tool")
        self.assertEqual(tool.name, "search")
        self.assertIn("read_files", tool.effects)

    def test_semantic_capabilities_block_does_not_reuse_effect_contract(self) -> None:
        manifest = {
            "id": "coder",
            "plugin_type": "tool",
            "capabilities": {
                "skills": [{"id": "python-debugging", "domains": ["software.python", "debugging"], "intents": ["diagnose_bug"]}],
                "tools": [{"id": "repository-search", "domains": ["software.repository"], "intents": ["inspect_code"], "effects": ["read_files"]}],
                "agents": [{"id": "senior-coder", "specialties": ["python"], "accepts": ["coding_task"], "produces": ["patch"]}],
            },
            "tools": [{"name": "run", "description": "execute"}],
        }
        (self.root / "hades-plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        result = adapt_package(self.root, plugin={"id": "coder", "enabled": True, "status": "ready", "manifest": manifest})
        kinds = {item.kind for item in result.capabilities}
        self.assertTrue({"skill", "tool", "agent", "tool_provider"} <= kinds)
        skill = next(item for item in result.capabilities if item.kind == "skill")
        self.assertEqual(skill.side_effect_class, "none")
        self.assertEqual(skill.effects, [])
        agent = next(item for item in result.capabilities if item.kind == "agent")
        self.assertEqual(agent.extras["agent"]["accepts"], ["coding_task"])

    def test_plugin_is_container_not_capability_type(self) -> None:
        manifest = {
            "id": "mixed",
            "plugin_type": "service",
            "capabilities": {
                "skills": [{"id": "ops", "description": "operate services"}],
                "services": [{"id": "runtime", "description": "long running"}],
            },
            "tools": [{"name": "health", "description": "check"}],
        }
        (self.root / "hades-plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        result = adapt_package(self.root, plugin={"id": "mixed", "plugin_type": "service", "enabled": True, "status": "ready", "manifest": manifest})
        kinds = {item.kind for item in result.capabilities}
        self.assertIn("service", kinds)
        self.assertIn("skill", kinds)
        self.assertIn("tool", kinds)
        self.assertNotIn("plugin", kinds)

    def test_unknown_kind_is_reported_not_forced(self) -> None:
        manifest = {
            "id": "odd",
            "capabilities": {"spells": [{"id": "fireball", "kind": "spell"}]},
            "tools": [],
        }
        (self.root / "hades-plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        # Inject via convention file with bogus kind through raw adapter merge:
        from capability_intel.normalize import normalize_raw_capability
        from capability_intel.taxonomy import is_capability_kind

        self.assertFalse(is_capability_kind("spell"))
        self.assertIsNone(normalize_raw_capability({"id": "x", "kind": "spell"}, plugin={"id": "odd"}, adapter_id="test"))

    def test_native_capabilities_participate(self) -> None:
        registry = CapabilityRegistry()
        records = registry.refresh_native()
        ids = {item.canonical_id for item in records}
        self.assertIn("hades.coding_agent", ids)
        self.assertIn("hades.verification", ids)
        self.assertIn("hades.retrieval", ids)
        self.assertTrue(all(item.provider_id == "hades.native" for item in records))
