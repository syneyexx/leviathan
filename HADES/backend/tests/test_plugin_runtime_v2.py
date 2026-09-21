"""Plugin Runtime v2: trust ladder, capabilities, isolation, restart truth, timeline, MCP."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from platform_db import PlatformDatabase
from platform_services import PluginManager
from plugin_runtime_v2 import (
    build_capability_contract,
    build_timeline,
    eligible_for_autonomous,
    enrich_manifest,
    evaluate_global_side_effect_policies,
    min_trust_for_autonomous,
    normalize_trust,
    process_alive,
    read_service_state,
    required_policy_kinds,
    write_service_state,
)
from reasoning.tools import discover_tools
import platform_services_core as psc


class PluginRuntimeV2UnitTests(unittest.TestCase):
    def test_trust_aliases_and_ladder(self) -> None:
        self.assertEqual(normalize_trust("locally-converted"), "untrusted")
        self.assertEqual(normalize_trust("trusted"), "trusted")
        contract = build_capability_contract({"permissions": ["network", "subprocess"]})
        self.assertEqual(min_trust_for_autonomous(contract), "verified")
        risky = build_capability_contract({"permissions": ["filesystem:write", "network", "subprocess"]})
        self.assertEqual(min_trust_for_autonomous(risky), "trusted")

    def test_mcp_effect_requires_subprocess_unless_http_shaped(self) -> None:
        mcp_only = build_capability_contract({"permissions": [], "mcp": {"expand_tools": True}, "manifest": {"mcp": {"expand_tools": True}}})
        self.assertIn("subprocess", required_policy_kinds(mcp_only))
        http_shaped = {"effects": ["mcp", "network"], "side_effect_class": "network"}
        self.assertNotIn("subprocess", required_policy_kinds(http_shaped))
        denied = evaluate_global_side_effect_policies(
            contract=build_capability_contract({"permissions": ["subprocess"]}),
            settings={"subprocess_policy": "ask"},
            invocation_type="autonomous",
            approved_by_user=True,
        )
        self.assertFalse(denied["allowed"])
        self.assertIn("ask", denied["reason"])

    def test_enrich_manifest_adds_v2_fields(self) -> None:
        manifest = enrich_manifest(
            {
                "format": 1,
                "id": "demo",
                "name": "Demo",
                "version": "1.2.3",
                "permissions": ["subprocess", "network"],
                "tools": [
                    {
                        "name": "ping",
                        "command": ["{python}", "-c", "print(1)"],
                        "description": "ping",
                        "input_schema": {"type": "object", "properties": {}},
                    }
                ],
            }
        )
        self.assertEqual(manifest["isolation"], "plugin_cwd")
        self.assertIn("network", manifest["capabilities"]["effects"])
        self.assertEqual(manifest["marketplace"]["pinned_version"], "1.2.3")
        self.assertTrue(manifest["tools"][0]["capabilities"]["effects"])

    def test_bare_filesystem_is_read_not_write(self) -> None:
        contract = build_capability_contract({"permissions": ["filesystem", "subprocess"]})
        self.assertIn("read_files", contract["effects"])
        self.assertNotIn("write_files", contract["effects"])


class PluginRuntimeV2IntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = PlatformDatabase(str(self.root / "platform.db"))
        self.db.initialize()
        self.manager = PluginManager(self.db, self.root / "data")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_plugin(self, plugin_id: str = "demo-tool", *, network: bool = False, mcp: bool = False) -> Path:
        folder = self.root / "src" / plugin_id
        folder.mkdir(parents=True)
        permissions = ["subprocess"]
        if network:
            permissions.append("network")
        tools = [
            {
                "name": "echo",
                "action": "echo",
                "command": ["{python}", "-c", "import json,sys; print(json.dumps({'ok': True}))"],
                "description": "Echo tool for tests",
                "input_schema": {"type": "object", "properties": {}},
                "autonomous": True,
            }
        ]
        if mcp:
            tools = [
                {
                    "name": "list_tools",
                    "action": "list",
                    "command": ["{python}", "-c", "import json; print(json.dumps({'tools':[{'name':'remote_ping','description':'ping'}]}))"],
                    "description": "list",
                    "input_schema": {"type": "object", "properties": {}},
                },
                {
                    "name": "call_tool",
                    "action": "call",
                    "command": ["{python}", "-c", "import json; print(json.dumps({'ok': True}))"],
                    "description": "call",
                    "input_schema": {
                        "type": "object",
                        "properties": {"tool": {"type": "string"}, "arguments": {"type": "string", "default": "{}"}},
                    },
                },
            ]
        manifest = {
            "format": 1,
            "id": plugin_id,
            "name": plugin_id,
            "version": "0.1.0",
            "description": "demo plugin",
            "runtime_type": "python",
            "entrypoint": "echo",
            "plugin_type": "tool",
            "permissions": permissions,
            "autonomous": True,
            "hades_api": ">=0.4.1",
            "tools": tools,
        }
        if mcp:
            manifest["mcp"] = {"expand_tools": True, "transport": "stdio"}
        (folder / "hades-plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        return folder

    def test_import_sets_trust_verified_and_capabilities(self) -> None:
        folder = self._write_plugin()
        result = self.manager.import_local_folder(folder, install_dependencies=False)
        plugin = result["plugin"]
        self.assertEqual(plugin["status"], "ready")
        self.assertEqual(plugin["trust"], "verified")
        self.assertEqual(plugin["isolation"], "plugin_cwd")
        self.assertIn("subprocess", (plugin.get("capabilities") or plugin["manifest"]["capabilities"])["effects"])
        self.assertIsNone(plugin.get("failure_state"))

    def test_dependency_failure_sets_failure_state(self) -> None:
        folder = self._write_plugin("broken-deps")
        (folder / "requirements.txt").write_text("definitely-not-a-real-package-xyz-123==9.9.9\n", encoding="utf-8")
        with mock.patch.object(
            PluginManager,
            "_install_dependencies",
            return_value={"installed": False, "error": "pip failed", "commands": [["pip", "install", "-r", "requirements.txt"]]},
        ):
            result = self.manager.import_local_folder(folder, install_dependencies=True)
        plugin = result["plugin"]
        self.assertNotEqual(plugin["status"], "ready")
        self.assertEqual(plugin.get("failure_state"), "dependency_failed")
        self.assertFalse(plugin["enabled"])

    def test_timeline_merges_events_and_calls(self) -> None:
        folder = self._write_plugin()
        result = self.manager.import_local_folder(folder, install_dependencies=False)
        plugin_id = result["plugin"]["id"]
        self.db.set_plugin_state(plugin_id, enabled=True)
        self.manager.invoke(plugin_id, "echo", {}, invocation_type="manual", approved_by_user=True)
        items = self.db.plugin_timeline(plugin_id)
        kinds = {item["kind"] for item in items}
        self.assertIn("event", kinds)
        self.assertIn("tool_call", kinds)

    def test_restart_reconcile_uses_service_state(self) -> None:
        folder = self._write_plugin("svc")
        result = self.manager.import_local_folder(folder, install_dependencies=False)
        plugin_id = result["plugin"]["id"]
        self.db.set_plugin_state(plugin_id, health="healthy")
        write_service_state(self.manager.runtimes, plugin_id, {"pid": 999999, "started_at": 1.0, "status": "running"})
        self.manager.reconcile_services()
        plugin = self.db.get_plugin(plugin_id)
        # No healthcheck → needs_attention + failure_state health_unverified
        self.assertEqual(plugin["health"], "needs_attention")
        self.assertEqual(plugin.get("failure_state"), "health_unverified")

    def test_discover_tools_includes_why_eligible_and_capabilities(self) -> None:
        folder = self._write_plugin("discover-me", network=False)
        result = self.manager.import_local_folder(folder, install_dependencies=False)
        plugin = result["plugin"]
        self.db.set_plugin_state(plugin["id"], enabled=True)
        plugin = self.db.get_plugin(plugin["id"])
        tools = self.db.plugin_tools(plugin["id"])
        discovered = discover_tools(
            query="echo demo",
            plugins=[plugin],
            tools=tools,
            permission_ok=lambda _p, _t: True,
            limit=5,
        )
        self.assertGreaterEqual(discovered["total"], 1)
        item = discovered["tools"][0]
        self.assertEqual(item["why_eligible"], "ok")
        self.assertIn("capabilities", item)
        self.assertIn("trust", item)

    def test_autonomous_blocked_until_trust(self) -> None:
        folder = self._write_plugin("low-trust", network=True)
        result = self.manager.import_local_folder(folder, install_dependencies=False)
        plugin = result["plugin"]
        self.db.set_plugin_state(plugin["id"], enabled=True, trust="manual")
        plugin = self.db.get_plugin(plugin["id"])
        tool = self.db.plugin_tools(plugin["id"])[0]
        ok, reason = eligible_for_autonomous(plugin, tool)
        self.assertFalse(ok)
        self.assertIn("trust=manual<verified", reason)

    def test_mcp_expand_registers_remote_tools(self) -> None:
        folder = self._write_plugin("mcp-demo", mcp=True)
        result = self.manager.import_local_folder(folder, install_dependencies=False)
        plugin_id = result["plugin"]["id"]
        # Convert may have already expanded; force again.
        expansion = self.manager.expand_mcp_tools(plugin_id)
        self.assertFalse(expansion.get("skipped"))
        names = {item["name"] for item in self.db.plugin_tools(plugin_id)}
        self.assertIn("list_tools", names)
        self.assertIn("call_tool", names)
        self.assertTrue(any(name.startswith("mcp__") for name in names))

    def test_restricted_env_strips_secrets(self) -> None:
        folder = self._write_plugin("iso")
        manifest = json.loads((folder / "hades-plugin.json").read_text(encoding="utf-8"))
        manifest["isolation"] = "restricted_env"
        (folder / "hades-plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        result = self.manager.import_local_folder(folder, install_dependencies=False)
        plugin = result["plugin"]
        tool = self.db.plugin_tools(plugin["id"])[0]
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "secret", "HADES_KEEP": "1"}, clear=False):
            env = self.manager._command_environment(plugin, tool)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertEqual(env.get("HADES_PLUGIN_ISOLATION"), "restricted_env")
        self.assertEqual(env.get("HADES_KEEP"), "1")

    def test_subprocess_block_never_spawns_even_privileged(self) -> None:
        folder = self._write_plugin("blocked-spawn")
        result = self.manager.import_local_folder(folder, install_dependencies=False)
        plugin_id = result["plugin"]["id"]
        self.db.set_plugin_state(plugin_id, enabled=True, trust="verified", status="ready")
        self.manager.set_policy_settings({"subprocess_policy": "block", "network_policy": "allow"})
        spawned: list[object] = []

        def _fake_run(*_a, **_k):
            spawned.append(1)

            class _R:
                stdout = "SHOULD_NOT"
                stderr = ""
                returncode = 0

            return _R()

        with mock.patch.object(psc.subprocess, "run", side_effect=_fake_run):
            blocked = self.manager.invoke(
                plugin_id,
                "echo",
                {},
                invocation_type="manual",
                approved_by_user=True,
            )
            privileged = self.manager.invoke(
                plugin_id,
                "echo",
                {},
                invocation_type="install",
                approved_by_user=True,
                privileged_policy_skip=True,
            )
        self.assertEqual(blocked.get("status"), "blocked")
        self.assertEqual(privileged.get("status"), "blocked")
        self.assertEqual(spawned, [])
        self.assertIn("block", str(blocked.get("error") or "").lower())

    def test_autonomous_ask_never_promotes_to_allow(self) -> None:
        folder = self._write_plugin("ask-spawn")
        result = self.manager.import_local_folder(folder, install_dependencies=False)
        plugin_id = result["plugin"]["id"]
        self.db.set_plugin_state(plugin_id, enabled=True, trust="verified", status="ready")
        self.manager.set_policy_settings({"subprocess_policy": "ask", "network_policy": "allow"})
        spawned: list[object] = []

        def _fake_run(*_a, **_k):
            spawned.append(1)

            class _R:
                stdout = "SHOULD_NOT"
                stderr = ""
                returncode = 0

            return _R()

        with mock.patch.object(psc.subprocess, "run", side_effect=_fake_run):
            # approved_by_user must not promote ask→allow on the autonomous path
            out = self.manager.invoke(
                plugin_id,
                "echo",
                {},
                invocation_type="autonomous",
                approved_by_user=True,
            )
        self.assertEqual(out.get("status"), "blocked")
        self.assertEqual(spawned, [])
        self.assertIn("ask", str(out.get("error") or "").lower())

    def test_discover_tools_dedupes_mcp_expand_and_host_mirror(self) -> None:
        plugins = [
            {
                "id": "plugin-expand",
                "name": "Expand MCP",
                "enabled": True,
                "status": "ready",
                "trust": "verified",
                "category": "MCP",
                "manifest": {"autonomous": True, "category": "MCP"},
            },
            {
                "id": "mcp:host-1",
                "name": "Host MCP",
                "enabled": True,
                "status": "ready",
                "trust": "verified",
                "plugin_type": "mcp-managed",
                "category": "MCP",
                "manifest": {"autonomous": True, "category": "MCP", "plugin_type": "mcp-managed"},
            },
        ]
        tools = [
            {
                "plugin_id": "plugin-expand",
                "name": "mcp__search",
                "description": "search docs via MCP",
                "enabled": True,
                "input_schema": {},
                "metadata": {"autonomous": True, "mcp_remote": True, "mcp_tool": "search"},
            },
            {
                "plugin_id": "mcp:host-1",
                "name": "mcp.search",
                "description": "search docs via MCP",
                "enabled": True,
                "input_schema": {},
                "metadata": {"autonomous": True, "mcp_managed": True, "mcp_tool": "search"},
            },
        ]
        discovered = discover_tools(
            query="search docs via MCP",
            plugins=plugins,
            tools=tools,
            permission_ok=lambda _p, _t: True,
            include_unscored=True,
        )
        self.assertEqual(discovered["total"], 1)
        self.assertEqual(len(discovered["tools"]), 1)
        self.assertEqual(discovered["tools"][0]["plugin_id"], "mcp:host-1")
        self.assertTrue(discovered["tools"][0].get("mcp_managed"))


class PluginRuntimeV2CatalogManifestTests(unittest.TestCase):
    def test_all_catalog_manifests_have_v2_fields(self) -> None:
        root = Path(__file__).resolve().parents[2] / "plugins"
        manifests = sorted(root.glob("*/hades-plugin.json"))
        self.assertGreaterEqual(len(manifests), 30)
        for path in manifests:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data.get("format"), 1, path)
            self.assertTrue(data.get("capabilities", {}).get("effects"), path)
            self.assertTrue(data.get("isolation"), path)
            self.assertTrue(data.get("trust_default"), path)
            self.assertTrue((data.get("marketplace") or {}).get("pinned_version"), path)


if __name__ == "__main__":
    unittest.main()
