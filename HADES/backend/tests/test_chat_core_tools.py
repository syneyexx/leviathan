"""P0: Chat always offers HADES core tools when autonomy is on.

Deterministic — no LM Studio required.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core_tools import (
    CORE_PLUGIN_ID,
    build_chat_tool_shortlist,
    core_tool_catalog,
    invoke_core_tool,
    is_core_tool,
)
from core_tools.catalog import CORE_TOOL_NAMES, FS_READ, WEB_FETCH
from reasoning.budgets import budget_from_profile
from reasoning.tool_engine import ToolEngineConfig, run_tool_engine
from reasoning.tool_protocol import (
    ResponseState,
    classify_model_response,
    encode_provider_function_name,
)
from reasoning.tool_registry import build_native_tools_payload
from reasoning.understanding import build_request_spec, build_route_decision


class AutonomyOnOffersCoreToolsTests(unittest.TestCase):
    def test_plain_question_is_direct_chat_without_tools(self) -> None:
        """Simple conversational answers must not receive tool schemas (Normal/fast budget)."""
        spec = build_request_spec("Wat is 2+2?")
        self.assertFalse(spec.needs_tools)
        route = build_route_decision(
            spec,
            requested_profile="adaptive",
            network_policy="block",
            plugin_tools_enabled=True,
        )
        self.assertEqual(route.target, "direct_chat")
        self.assertFalse(route.allow_tools)
        self.assertEqual(route.max_tool_rounds, 0)

        budget = budget_from_profile(
            profile_name=route.profile,
            settings_max_tool_rounds=3,
            route_max_tool_rounds=route.max_tool_rounds,
            tools_allowed=True and route.allow_tools,
        )
        self.assertEqual(int(budget.max_tool_rounds or 0), 0)

        shortlist = build_chat_tool_shortlist(
            query="Wat is 2+2?",
            plugins=[],
            tools=[],
            settings={"network_policy": "block", "plugin_autonomous_tools": True},
            permission_ok=lambda _p, _t: True,
            limit=8,
            allow_tools=route.allow_tools,
        )
        self.assertEqual(shortlist, [])

    def test_tool_required_turn_still_offers_core_tools(self) -> None:
        """Autonomy-on still exposes core tools for genuine tool-use turns."""
        spec = build_request_spec("Lees bestand notes.txt")
        self.assertTrue(spec.needs_tools)
        route = build_route_decision(
            spec,
            requested_profile="adaptive",
            network_policy="block",
            plugin_tools_enabled=True,
        )
        self.assertTrue(route.allow_tools)
        self.assertGreaterEqual(route.max_tool_rounds, 1)

        shortlist = build_chat_tool_shortlist(
            query="Lees bestand notes.txt",
            plugins=[],
            tools=[],
            settings={"network_policy": "block", "plugin_autonomous_tools": True},
            permission_ok=lambda _p, _t: True,
            limit=8,
        )
        names = {str(item.get("name")) for item in shortlist}
        self.assertIn(FS_READ, names)
        payload = build_native_tools_payload(shortlist, include_discover=False, query="Lees bestand notes.txt")
        encoded = {item["function"]["name"] for item in payload}
        self.assertIn(encode_provider_function_name(CORE_PLUGIN_ID, FS_READ), encoded)

    def test_gebruik_geen_tools_zeros_payload(self) -> None:
        spec = build_request_spec("gebruik geen tools, wat is 2+2?")
        route = build_route_decision(
            spec,
            requested_profile="adaptive",
            network_policy="block",
            plugin_tools_enabled=True,
        )
        self.assertFalse(route.allow_tools)
        self.assertEqual(route.max_tool_rounds, 0)

        shortlist = build_chat_tool_shortlist(
            query="gebruik geen tools, wat is 2+2?",
            plugins=[],
            tools=[],
            settings={"network_policy": "block", "plugin_autonomous_tools": True},
            permission_ok=lambda _p, _t: True,
            limit=8,
            allow_tools=False,
        )
        self.assertEqual(shortlist, [])

    def test_null_content_native_tool_calls_still_valid(self) -> None:
        response = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_fs",
                                "type": "function",
                                "function": {
                                    "name": encode_provider_function_name(CORE_PLUGIN_ID, FS_READ),
                                    "arguments": '{"path":"notes.txt"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
        classified = classify_model_response(response)
        self.assertEqual(classified.state, ResponseState.TOOL_CALLS)
        self.assertEqual(classified.tool_calls[0].plugin_id, CORE_PLUGIN_ID)
        # Provider names sanitize '.' → '_'; resolve_tool_row still matches.
        self.assertIn("fs_read", classified.tool_calls[0].tool_name.replace(".", "_"))


class CoreToolJailAndBlockedTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="hades-core-tools-")
        self.root = Path(self._tmpdir.name)
        (self.root / "inside.txt").write_text("hello inside", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_fs_read_outside_jail_blocked(self) -> None:
        result = invoke_core_tool(
            FS_READ,
            {"path": "/etc/passwd"},
            data_root=self.root,
            settings={"file_read_policy": "allow", "network_policy": "block"},
        )
        self.assertEqual(result.get("status"), "blocked")
        self.assertEqual(result.get("reason_code"), "path_outside_jail")

    def test_unknown_tool_blocked_observation(self) -> None:
        async def _run() -> None:
            tools = core_tool_catalog(settings={"network_policy": "block"})
            calls = {"n": 0}

            async def chat(payload: dict) -> dict:
                calls["n"] += 1
                if calls["n"] == 1:
                    return {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": None,
                                    "tool_calls": [
                                        {
                                            "id": "c1",
                                            "type": "function",
                                            "function": {
                                                "name": encode_provider_function_name("missing-plugin", "ghost"),
                                                "arguments": "{}",
                                            },
                                        }
                                    ],
                                },
                                "finish_reason": "tool_calls",
                            }
                        ]
                    }
                return {
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ]
                }

            rejected: list[dict] = []

            def record_rejected(plugin_id, tool_name, arguments, *, status, error):
                row = {
                    "id": "rej1",
                    "plugin_id": plugin_id,
                    "tool_name": tool_name,
                    "status": status,
                    "error": error,
                    "reason_code": "unknown_tool",
                }
                rejected.append(row)
                return row

            result = await run_tool_engine(
                messages=[{"role": "user", "content": "call ghost"}],
                query="call ghost",
                tools=tools,
                chat=chat,
                build_payload=lambda msgs, native: {
                    "model": "test",
                    "messages": msgs,
                    **({"tools": native} if native else {}),
                },
                invoke=lambda *_a, **_k: {"status": "completed"},
                record_rejected=record_rejected,
                config=ToolEngineConfig(autonomous=True, max_rounds=2, max_model_calls=4),
            )
            self.assertTrue(result.tool_log)
            row = result.tool_log[0]
            self.assertEqual(row.get("status"), "blocked")
            self.assertEqual(row.get("reason_code"), "unknown_tool")
            self.assertNotEqual(row.get("status"), "completed")

        asyncio.run(_run())

    def test_web_fetch_absent_when_network_blocked_and_blocked_if_called(self) -> None:
        catalog = core_tool_catalog(settings={"network_policy": "block"})
        names = {str(item.get("name")) for item in catalog}
        self.assertNotIn(WEB_FETCH, names)

        result = invoke_core_tool(
            WEB_FETCH,
            {"url": "https://example.com"},
            data_root=self.root,
            settings={"network_policy": "block"},
        )
        self.assertEqual(result.get("status"), "blocked")
        self.assertIn("network_policy", str(result.get("reason_code") or result.get("error") or ""))

    def test_autonomous_false_plugin_not_in_shortlist(self) -> None:
        plugin = {
            "id": "manual-only",
            "name": "Manual Only",
            "enabled": True,
            "status": "ready",
            "trust": "trusted",
            "permissions": ["subprocess"],
            "manifest": {"autonomous": False},
            "plugin_type": "Tool",
        }
        tool = {
            "plugin_id": "manual-only",
            "name": "echo",
            "enabled": True,
            "description": "echo",
            "input_schema": {"type": "object", "properties": {}},
            "metadata": {"autonomous": False},
            "capabilities": {"effects": ["subprocess"], "side_effect_class": "process"},
        }
        shortlist = build_chat_tool_shortlist(
            query="Gebruik manual-only echo",
            plugins=[plugin],
            tools=[tool],
            settings={"network_policy": "block", "plugin_autonomous_tools": True},
            permission_ok=lambda _p, _t: True,
            limit=8,
        )
        plugin_ids = {str(item.get("plugin_id")) for item in shortlist}
        self.assertNotIn("manual-only", plugin_ids)
        # Core tools still present.
        self.assertTrue(any(is_core_tool(str(item.get("name"))) for item in shortlist))

    def test_manual_plugin_invoke_still_plugin_manager(self) -> None:
        """Plugins-page path must keep using PluginManager.invoke (no second engine)."""
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        # Manual invoke route still delegates to plugin_manager.invoke.
        self.assertIn("plugin_manager.invoke(", source)
        self.assertIn('invocation_type="manual"', source)


class CoreCatalogContractTests(unittest.TestCase):
    def test_core_catalog_declares_effects_explicitly(self) -> None:
        for item in core_tool_catalog(settings={"network_policy": "allow"}):
            caps = item.get("capabilities") or {}
            self.assertIn("effects", caps, item.get("name"))
            self.assertIsInstance(caps["effects"], list)
        names = {item["name"] for item in core_tool_catalog(settings={"network_policy": "allow"})}
        # Model-visible kernel — legacy discover_plugins is an invoke alias, not listed.
        for required in CORE_TOOL_NAMES:
            if required == "hades.discover_plugins":
                continue
            self.assertIn(required, names)
        self.assertIn("hades.capabilities.search", names)
        self.assertIn("hades.capabilities.invoke", names)
        self.assertNotIn("hades.discover_plugins", names)

    def test_shortlist_caps_at_eight_core_first(self) -> None:
        plugins = []
        tools = []
        for i in range(10):
            pid = f"plug{i}"
            plugins.append(
                {
                    "id": pid,
                    "name": f"Plugin {i}",
                    "enabled": True,
                    "status": "ready",
                    "trust": "trusted",
                    "permissions": ["subprocess"],
                    "manifest": {"autonomous": True},
                    "plugin_type": "Tool",
                }
            )
            tools.append(
                {
                    "plugin_id": pid,
                    "name": "echo",
                    "enabled": True,
                    "description": f"echo {i}",
                    "input_schema": {"type": "object"},
                    "metadata": {},
                    "capabilities": {"effects": ["subprocess"]},
                }
            )
        shortlist = build_chat_tool_shortlist(
            query="Gebruik plug0 echo",
            plugins=plugins,
            tools=tools,
            settings={"network_policy": "block", "plugin_autonomous_tools": True},
            permission_ok=lambda _p, _t: True,
            limit=8,
        )
        self.assertLessEqual(len(shortlist), 8)
        core_count = sum(1 for item in shortlist if is_core_tool(str(item.get("name"))))
        self.assertGreaterEqual(core_count, 5)
        # Architecture: plugins are NEVER injected into the model-visible shortlist.
        plugin_count = sum(1 for item in shortlist if not is_core_tool(str(item.get("name"))))
        self.assertEqual(plugin_count, 0)
        names = {str(item.get("name")) for item in shortlist}
        self.assertIn("hades.capabilities.search", names)
        self.assertIn("hades.capabilities.invoke", names)


if __name__ == "__main__":
    unittest.main()
