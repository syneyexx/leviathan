"""Tool Kernel + Capability Broker architecture invariants (Tests A–R).

Deterministic — no LM Studio required. Proves:
- model-visible tool count stays bounded under plugin/MCP scale
- plugins/MCP are discovered via broker, not permanent Chat schemas
- MarkItDown / Puppeteer / MCP flows honor policy + approval
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from capability_intel.availability import (
    APPROVAL_REQUIRED,
    AVAILABLE,
    DISABLED,
    MCP_DISCONNECTED,
    NETWORK_BLOCKED,
    NOT_AUTONOMOUS,
    UNREGISTERED,
)
from capability_intel.broker import CapabilityBroker, reset_broker
from capability_intel.ids import make_capability_id, parse_capability_id
from capability_intel.registry import CapabilityRegistry, reset_registry
from core_tools import (
    CAPABILITIES_INSPECT,
    CAPABILITIES_INVOKE,
    CAPABILITIES_SEARCH,
    MAX_MODEL_VISIBLE_TOOLS,
    assert_no_dynamic_plugin_schemas,
    build_chat_tool_shortlist,
    core_tool_catalog,
    invoke_core_tool,
    is_core_tool,
)
from reasoning.tool_registry import build_native_tools_payload


def _plugin(
    pid: str,
    *,
    name: str | None = None,
    enabled: bool = True,
    status: str = "ready",
    trust: str = "verified",
    autonomous: bool = True,
    labels: list[str] | None = None,
    description: str = "",
    permissions: list[str] | None = None,
    plugin_type: str = "tool",
    health: str = "healthy",
    failure_state: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": pid,
        "name": name or pid,
        "enabled": enabled,
        "status": status,
        "trust": trust,
        "health": health,
        "failure_state": failure_state,
        "description": description or f"{name or pid} plugin",
        "labels": labels or [],
        "permissions": permissions or ["subprocess", "filesystem"],
        "plugin_type": plugin_type,
        "manifest": {
            "autonomous": autonomous,
            "category": "Test",
            "labels": labels or [],
            "description": description,
        },
        "metadata": metadata or {},
    }


def _tool(
    plugin_id: str,
    name: str,
    *,
    description: str = "",
    effects: list[str] | None = None,
    schema: dict[str, Any] | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    return {
        "plugin_id": plugin_id,
        "name": name,
        "enabled": enabled,
        "description": description or f"{name} on {plugin_id}",
        "input_schema": schema
        or {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        "metadata": {},
        "capabilities": {
            "effects": effects or ["read_files", "subprocess", "write_files"],
            "side_effect_class": "process",
            "cost_class": "cheap",
            "latency_class": "fast",
        },
    }


class ToolKernelBudgetTests(unittest.TestCase):
    """TEST A / L — stable model-visible tool count under scale."""

    def setUp(self) -> None:
        reset_broker()
        reset_registry()

    def tearDown(self) -> None:
        reset_broker()
        reset_registry()

    def _scale_plugins(self, n_plugins: int, tools_per: int = 1) -> tuple[list[dict], list[dict]]:
        plugins: list[dict] = []
        tools: list[dict] = []
        for i in range(n_plugins):
            pid = f"plug{i}"
            plugins.append(_plugin(pid, name=f"Plugin {i}", labels=[f"label{i}"]))
            for j in range(tools_per):
                tools.append(_tool(pid, f"action_{j}", description=f"utility action {j} for {pid}"))
        return plugins, tools

    def test_a_zero_to_hundreds_plugins_keeps_kernel_bounded(self) -> None:
        settings = {"network_policy": "block", "plugin_autonomous_tools": True}
        for n, tools_per in ((0, 0), (10, 2), (100, 5), (100, 5)):
            plugins, tools = self._scale_plugins(n, tools_per) if n else ([], [])
            if n == 100 and tools_per == 5:
                # 500 plugin tools
                self.assertEqual(len(tools), 500)
            shortlist = build_chat_tool_shortlist(
                query="Zet deze PDF om naar Markdown",
                plugins=plugins,
                tools=tools,
                settings=settings,
                permission_ok=lambda _p, _t: True,
                limit=MAX_MODEL_VISIBLE_TOOLS,
            )
            assert_no_dynamic_plugin_schemas(shortlist)
            self.assertLessEqual(len(shortlist), MAX_MODEL_VISIBLE_TOOLS)
            self.assertTrue(all(is_core_tool(str(item.get("name"))) for item in shortlist))
            names = {str(item.get("name")) for item in shortlist}
            self.assertIn(CAPABILITIES_SEARCH, names)
            self.assertIn(CAPABILITIES_INVOKE, names)
            payload = build_native_tools_payload(shortlist, include_discover=False, query="pdf")
            self.assertLessEqual(len(payload), MAX_MODEL_VISIBLE_TOOLS)
            # No plugin tool names in provider schemas.
            encoded = " ".join(item["function"]["name"] for item in payload)
            self.assertNotIn("plug0", encoded)
            self.assertNotIn("markitdown", encoded.lower())

    def test_l_mcp_scale_does_not_grow_model_tools(self) -> None:
        plugins = [_plugin("mcp:github", name="GitHub MCP", plugin_type="mcp", labels=["github", "issue"])]
        tools = [
            _tool(
                "mcp:github",
                f"tool_{i}",
                description=f"mcp github tool {i} create issue pull request",
                effects=["network", "mcp"],
                schema={"type": "object", "properties": {"title": {"type": "string"}}},
            )
            for i in range(120)
        ]
        shortlist = build_chat_tool_shortlist(
            query="maak een GitHub issue",
            plugins=plugins,
            tools=tools,
            settings={"network_policy": "allow", "plugin_autonomous_tools": True},
            permission_ok=lambda _p, _t: True,
            limit=MAX_MODEL_VISIBLE_TOOLS,
        )
        self.assertLessEqual(len(shortlist), MAX_MODEL_VISIBLE_TOOLS)
        assert_no_dynamic_plugin_schemas(shortlist)
        broker = CapabilityBroker(
            plugins_by_id={p["id"]: p for p in plugins},
            tools_by_key={(t["plugin_id"], t["name"]): t for t in tools},
            settings={"network_policy": "allow"},
        )
        self.assertGreaterEqual(broker.count(), 120)
        page = broker.search("create github issue", limit=5)
        self.assertTrue(page["matches"])


class CapabilityBrokerFlowTests(unittest.TestCase):
    """Tests B–R covering discovery, invoke, policy, approval, lifecycle."""

    def setUp(self) -> None:
        reset_broker()
        reset_registry()
        self.invocations: list[tuple[str, str, dict]] = []
        self.approvals: list[dict] = []

        def _invoke(pid: str, tname: str, args: dict, **kwargs: Any) -> dict[str, Any]:
            self.invocations.append((pid, tname, dict(args)))
            if pid == "broken":
                raise RuntimeError("simulated provider failure")
            return {
                "status": "completed",
                "stdout": f"ok:{pid}/{tname}",
                "output": f"ok:{pid}/{tname}:{args}",
                "exit_code": 0,
                "approved_by_user": kwargs.get("approved_by_user"),
                "invocation_type": kwargs.get("invocation_type"),
            }

        def _approval(**kwargs: Any) -> dict[str, Any]:
            row = {"id": f"appr-{len(self.approvals)+1}", "status": "pending", **kwargs}
            self.approvals.append(row)
            return row

        self.markitdown = _plugin(
            "markitdown",
            name="MarkItDown",
            labels=["markdown", "conversion", "documents", "pdf"],
            description="Convert documents (PDF, Office, HTML) to Markdown",
            trust="verified",
            autonomous=True,
            permissions=["subprocess", "filesystem"],
        )
        self.puppeteer = _plugin(
            "puppeteer",
            name="Puppeteer",
            labels=["puppeteer", "browser", "screenshot"],
            description="Headless Chromium automation for fetch and screenshot",
            trust="verified",
            autonomous=False,
            permissions=["subprocess", "network", "filesystem"],
        )
        self.mcp = _plugin(
            "mcp:github",
            name="GitHub",
            plugin_type="mcp",
            labels=["github", "issue"],
            description="GitHub MCP server",
            trust="verified",
            autonomous=True,
            permissions=["network"],
            metadata={"mcp_connected": True},
        )
        self.tools = [
            _tool(
                "markitdown",
                "convert",
                description="Convert a local PDF or Office file to Markdown via MarkItDown.",
                effects=["read_files", "subprocess", "write_files"],
                schema={
                    "type": "object",
                    "required": ["path"],
                    "properties": {"path": {"type": "string"}, "output": {"type": "string"}},
                    "additionalProperties": False,
                },
            ),
            _tool(
                "markitdown",
                "doctor",
                description="Check whether MarkItDown is importable.",
                effects=["subprocess"],
                schema={"type": "object", "properties": {}, "additionalProperties": False},
            ),
            _tool(
                "puppeteer",
                "screenshot",
                description="Open a website URL in headless Chromium and take a screenshot.",
                effects=["network", "subprocess", "write_files", "read_files"],
                schema={
                    "type": "object",
                    "required": ["url"],
                    "properties": {"url": {"type": "string"}},
                },
            ),
            _tool(
                "mcp:github",
                "create_issue",
                description="Create a GitHub issue on a repository.",
                effects=["network", "mcp"],
                schema={
                    "type": "object",
                    "required": ["title"],
                    "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
                },
            ),
        ]
        self.settings = {
            "network_policy": "allow",
            "file_read_policy": "allow",
            "file_write_policy": "allow",
            "subprocess_policy": "allow",
            "plugin_autonomous_tools": True,
        }
        self.mcp_state = {"mcp:github": True}

        self.broker = CapabilityBroker(
            registry=CapabilityRegistry(),
            plugins_by_id={
                "markitdown": self.markitdown,
                "puppeteer": self.puppeteer,
                "mcp:github": self.mcp,
            },
            tools_by_key={(t["plugin_id"], t["name"]): t for t in self.tools},
            settings=self.settings,
            invoke_fn=_invoke,
            approval_fn=_approval,
            permission_ok=lambda _p, _t: True,
            mcp_connected=lambda pid: bool(self.mcp_state.get(pid, False)),
        )

    def tearDown(self) -> None:
        reset_broker()
        reset_registry()

    def test_b_o_markitdown_natural_language_discover_and_invoke(self) -> None:
        page = self.broker.search("Zet deze PDF om naar Markdown", limit=5)
        ids = [m["capability_id"] for m in page["matches"]]
        self.assertIn("plugin:markitdown:convert", ids)
        match = next(m for m in page["matches"] if m["capability_id"] == "plugin:markitdown:convert")
        self.assertTrue(match["available"])
        self.assertEqual(match["availability_reason"], AVAILABLE)

        result = self.broker.invoke(
            "plugin:markitdown:convert",
            {"path": "/tmp/fixture.pdf", "output": "/tmp/out.md"},
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["provider"], "plugin")
        self.assertEqual(self.invocations[-1][0], "markitdown")
        self.assertEqual(self.invocations[-1][1], "convert")

    def test_n_explicit_markitdown_mention(self) -> None:
        page = self.broker.search("Gebruik MarkItDown", limit=5)
        ids = [m["capability_id"] for m in page["matches"]]
        self.assertIn("plugin:markitdown:convert", ids)

    def test_c_unknown_capability_search_honest(self) -> None:
        page = self.broker.search("teleporteer een spaceship naar mars met quantum foam", limit=5)
        # May return empty or low-relevance; must not invent markitdown as available for spaceship.
        for match in page["matches"]:
            self.assertNotEqual(match.get("capability_id"), "plugin:spaceship:teleport")

    def test_d_disabled_plugin_searchable_but_invoke_denied(self) -> None:
        self.markitdown["enabled"] = False
        self.broker.set_live_state(plugins_by_id=self.broker.plugins_by_id)
        page = self.broker.search("convert pdf to markdown", limit=5)
        hit = next(m for m in page["matches"] if "markitdown" in m["capability_id"])
        self.assertFalse(hit["available"])
        self.assertEqual(hit["availability_reason"], DISABLED)
        result = self.broker.invoke("plugin:markitdown:convert", {"path": "x.pdf"})
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason_code"], DISABLED)
        self.assertEqual(self.invocations, [])

    def test_e_puppeteer_restricted_discovery(self) -> None:
        page = self.broker.search("open website and take screenshot", limit=5)
        ids = [m["capability_id"] for m in page["matches"]]
        self.assertIn("plugin:puppeteer:screenshot", ids)
        hit = next(m for m in page["matches"] if m["capability_id"] == "plugin:puppeteer:screenshot")
        self.assertFalse(hit["available"])
        self.assertIn(hit["availability_reason"], {NOT_AUTONOMOUS, APPROVAL_REQUIRED})

        result = self.broker.invoke("plugin:puppeteer:screenshot", {"url": "https://example.com"})
        self.assertEqual(result["status"], "approval_required")
        self.assertTrue(self.approvals)
        self.assertEqual(self.invocations, [])

    def test_f_approval_then_execute(self) -> None:
        denied = self.broker.invoke("plugin:puppeteer:screenshot", {"url": "https://example.com"})
        self.assertEqual(denied["status"], "approval_required")
        approved = self.broker.invoke(
            "plugin:puppeteer:screenshot",
            {"url": "https://example.com"},
            approved_by_user=True,
        )
        self.assertEqual(approved["status"], "completed")
        self.assertEqual(self.invocations[-1][1], "screenshot")

    def test_g_network_block_fail_closed(self) -> None:
        self.broker.settings["network_policy"] = "block"
        result = self.broker.invoke("plugin:puppeteer:screenshot", {"url": "https://example.com"}, approved_by_user=True)
        # Even with approval, block wins.
        self.assertEqual(result["status"], "blocked")
        self.assertIn("network", str(result.get("reason_code") or result.get("error") or "").lower())

    def test_h_invalid_schema_rejected(self) -> None:
        result = self.broker.invoke("plugin:markitdown:convert", {"wrong": True})
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason_code"], "invalid_arguments")
        self.assertEqual(self.invocations, [])

    def test_i_provider_failure_observation(self) -> None:
        broken = _plugin("broken", name="Broken", trust="verified")
        tool = _tool("broken", "explode", description="always fails", schema={"type": "object", "properties": {}})
        self.broker.plugins_by_id["broken"] = broken
        self.broker.tools_by_key[("broken", "explode")] = tool
        self.broker.rebuild_index()
        result = self.broker.invoke("plugin:broken:explode", {})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason_code"], "provider_failure")

    def test_j_new_plugin_searchable_without_schema_change(self) -> None:
        before = build_chat_tool_shortlist(
            query="hypit something",
            plugins=list(self.broker.plugins_by_id.values()),
            tools=list(self.broker.tools_by_key.values()),
            settings=self.settings,
            limit=MAX_MODEL_VISIBLE_TOOLS,
        )
        new_plugin = _plugin(
            "hypit",
            name="Hypit",
            labels=["hypit", "audio"],
            description="Hypit audio utility",
            trust="verified",
        )
        new_tool = _tool("hypit", "transcribe", description="Transcribe audio with Hypit", effects=["subprocess", "read_files"])
        self.broker.refresh_from_plugins(
            [*self.broker.plugins_by_id.values(), new_plugin],
            [*self.broker.tools_by_key.values(), new_tool],
        )
        page = self.broker.search("transcribe audio with hypit", limit=5)
        self.assertTrue(any(m["capability_id"] == "plugin:hypit:transcribe" for m in page["matches"]))
        after = build_chat_tool_shortlist(
            query="hypit something",
            plugins=list(self.broker.plugins_by_id.values()),
            tools=list(self.broker.tools_by_key.values()),
            settings=self.settings,
            limit=MAX_MODEL_VISIBLE_TOOLS,
        )
        self.assertEqual(
            {item["name"] for item in before},
            {item["name"] for item in after},
        )

    def test_k_uninstall_removes_discovery(self) -> None:
        self.broker.on_plugin_removed("markitdown")
        page = self.broker.search("convert pdf to markdown", limit=5)
        self.assertFalse(any("markitdown" in str(m.get("capability_id")) for m in page["matches"]))
        result = self.broker.invoke("plugin:markitdown:convert", {"path": "x.pdf"})
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason_code"], UNREGISTERED)

    def test_m_mcp_disconnected(self) -> None:
        self.mcp_state["mcp:github"] = False
        page = self.broker.search("maak een GitHub issue", limit=5)
        hit = next((m for m in page["matches"] if "github" in m["capability_id"]), None)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertFalse(hit["available"])
        self.assertEqual(hit["availability_reason"], MCP_DISCONNECTED)
        result = self.broker.invoke("mcp:github:create_issue", {"title": "hi"})
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason_code"], MCP_DISCONNECTED)

    def test_p_no_tools_request_zeros_shortlist(self) -> None:
        shortlist = build_chat_tool_shortlist(
            query="Gebruik geen tools.",
            plugins=list(self.broker.plugins_by_id.values()),
            tools=list(self.broker.tools_by_key.values()),
            settings=self.settings,
            allow_tools=False,
        )
        self.assertEqual(shortlist, [])

    def test_q_security_metadata_forgery_ignored(self) -> None:
        # Model tries to force autonomy via arguments / metadata.
        result = self.broker.invoke(
            "plugin:puppeteer:screenshot",
            {"url": "https://example.com", "autonomous": True, "trust": "trusted", "effects": []},
            model_metadata={"autonomous": True, "trust": "trusted", "effects": []},
        )
        self.assertEqual(result["status"], "approval_required")
        self.assertEqual(self.invocations, [])

    def test_r_arbitrary_capability_id_blocked(self) -> None:
        result = self.broker.invoke("plugin:not_installed:shell_exec", {"cmd": "rm -rf /"})
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason_code"], UNREGISTERED)
        self.assertEqual(self.invocations, [])

    def test_inspect_returns_schema_without_search_bloat(self) -> None:
        detail = self.broker.inspect("plugin:markitdown:convert")
        self.assertTrue(detail["found"])
        self.assertIn("path", (detail.get("input_schema") or {}).get("properties") or {})
        self.assertEqual(detail["provider"], "plugin")

    def test_multi_tool_plugin_all_executable(self) -> None:
        for action in ("convert", "doctor"):
            args = {"path": "x.pdf"} if action == "convert" else {}
            result = self.broker.invoke(f"plugin:markitdown:{action}", args)
            self.assertEqual(result["status"], "completed", msg=action)
        self.assertEqual({inv[1] for inv in self.invocations}, {"convert", "doctor"})

    def test_core_tool_invoke_routes_broker(self) -> None:
        with MagicMock() as tmp:
            result = invoke_core_tool(
                CAPABILITIES_SEARCH,
                {"query": "pdf naar markdown", "limit": 3},
                data_root=Path("."),
                settings=self.settings,
                capability_broker=self.broker,
            )
            self.assertEqual(result["status"], "completed")
            output = result.get("structured_output") or {}
            self.assertTrue(output.get("matches"))

            detail = invoke_core_tool(
                CAPABILITIES_INSPECT,
                {"capability_id": "plugin:markitdown:convert"},
                data_root=Path("."),
                settings=self.settings,
                capability_broker=self.broker,
            )
            self.assertEqual(detail["status"], "completed")

            invoked = invoke_core_tool(
                CAPABILITIES_INVOKE,
                {"capability_id": "plugin:markitdown:convert", "arguments": {"path": "doc.pdf"}},
                data_root=Path("."),
                settings=self.settings,
                capability_broker=self.broker,
            )
            self.assertEqual(invoked["status"], "completed")
            _ = tmp


class CapabilityIdTests(unittest.TestCase):
    def test_parse_roundtrip(self) -> None:
        cid = make_capability_id("plugin", "markitdown", "convert")
        self.assertEqual(cid, "plugin:markitdown:convert")
        self.assertEqual(parse_capability_id(cid), ("plugin", "markitdown", "convert"))

    def test_mcp_strips_double_prefix(self) -> None:
        cid = make_capability_id("mcp", "mcp:github", "create_issue")
        self.assertEqual(cid, "mcp:github:create_issue")


class CatalogInvariantTests(unittest.TestCase):
    def test_catalog_under_budget(self) -> None:
        catalog = core_tool_catalog(settings={"network_policy": "allow", "plugin_autonomous_tools": True})
        self.assertLessEqual(len(catalog), MAX_MODEL_VISIBLE_TOOLS)
        names = {item["name"] for item in catalog}
        self.assertIn(CAPABILITIES_SEARCH, names)
        self.assertIn(CAPABILITIES_INSPECT, names)
        self.assertIn(CAPABILITIES_INVOKE, names)

    def test_existing_shortlist_no_longer_injects_plugins(self) -> None:
        plugins = [_plugin(f"p{i}", name=f"P{i}") for i in range(20)]
        tools = [_tool(f"p{i}", "echo", description="echo") for i in range(20)]
        shortlist = build_chat_tool_shortlist(
            query="Gebruik p0 echo",
            plugins=plugins,
            tools=tools,
            settings={"network_policy": "block", "plugin_autonomous_tools": True},
            permission_ok=lambda _p, _t: True,
            limit=8,
        )
        plugin_count = sum(1 for item in shortlist if not is_core_tool(str(item.get("name"))))
        self.assertEqual(plugin_count, 0)


if __name__ == "__main__":
    unittest.main()
