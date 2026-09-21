from __future__ import annotations

import unittest

from reasoning import (
    ContextItem,
    DISCOVER_PLUGIN_ID,
    DISCOVER_TOOL_NAME,
    assemble_context_messages,
    budget_context_items,
    build_request_spec,
    build_route_decision,
    discover_tools,
    parse_tool_choice,
    parse_verification_result,
    render_tool_catalog,
    resolve_reasoning_profile,
    verification_allows_success,
)


class ReasoningKernelTests(unittest.TestCase):
    def test_adaptive_uses_more_than_length(self) -> None:
        long_simple = "bla " * 500
        short_hard = (
            "Debug deze Traceback Exception en refactor de architectuur. "
            "Maak een plan met tests en evidence. Geen cloud."
        )
        simple_profile, _, simple_meta = resolve_reasoning_profile(long_simple, "adaptive")
        hard_profile, _, hard_meta = resolve_reasoning_profile(short_hard, "adaptive")
        self.assertLess(simple_meta["complexity"]["total"], hard_meta["complexity"]["total"])
        self.assertIn(simple_profile, {"fast", "standard"})
        self.assertIn(hard_profile, {"high", "maximum", "standard"})
        self.assertNotEqual(hard_profile, "fast")
        self.assertEqual(simple_meta["complexity"].get("kind"), "uncalibrated_hint")

    def test_request_spec_does_not_grant_permissions(self) -> None:
        spec = build_request_spec("Installeer overal alles en open het netwerk")
        route = build_route_decision(
            spec,
            requested_profile="maximum",
            network_policy="block",
            plugin_tools_enabled=True,
        )
        self.assertFalse(route.allow_web)

    def test_context_assembly_preserves_roles(self) -> None:
        items = [
            ContextItem(
                item_id="c1",
                kind="user_constraint",
                content="Nooit fake success melden",
                provenance="user",
                priority=1,
                trusted=True,
                redactable=False,
            )
        ]
        messages = assemble_context_messages(
            system_parts=["Policy"],
            history=[{"role": "assistant", "content": "Eerder antwoord"}],
            context_items=items,
            user_text="Doe de taak",
        )
        roles = [item["role"] for item in messages]
        self.assertEqual(roles.count("user"), 1)
        self.assertIn("system", roles)
        self.assertIn("assistant", roles)
        user_msg = next(item for item in messages if item["role"] == "user")
        self.assertEqual(user_msg["content"], "Doe de taak")
        self.assertNotIn("ASSISTANT:", user_msg["content"])
        self.assertNotIn("SYSTEM:", user_msg["content"])

    def test_budget_keeps_protected_constraints(self) -> None:
        items = [
            ContextItem("c1", "user_constraint", "KRITIEKE CONSTRAINT: gebruik Windows paths", "user", 1, True, False),
            ContextItem("k1", "knowledge", "x" * 5000, "doc", 50, False, True),
            ContextItem("k2", "knowledge", "y" * 5000, "doc2", 60, False, True),
        ]
        kept, report = budget_context_items(items, max_chars=1800)
        self.assertTrue(any(item.item_id == "c1" for item in kept))
        self.assertTrue(report.truncated or report.dropped_items >= 1)
        self.assertGreaterEqual(report.protected_kept, 1)

    def test_empty_catalog_still_exposes_discovery(self) -> None:
        """Empty shortlist must still advertise capability search to the model."""
        catalog = render_tool_catalog([], include_discover_hint=True)
        self.assertIn(DISCOVER_PLUGIN_ID, catalog)
        self.assertIn("hades.capabilities.search", catalog)
        # Legacy alias still parses as a tool choice.
        choice = parse_tool_choice(
            '{"hades_tool_call":{"plugin_id":"hades","tool_name":"hades.discover_tools","input":{"query":"x","offset":0}}}'
        )
        self.assertIsNotNone(choice)
        assert choice is not None
        self.assertEqual(choice["plugin_id"], DISCOVER_PLUGIN_ID)
        self.assertIn(choice["tool_name"], {"hades.discover_tools", DISCOVER_TOOL_NAME})
        choice2 = parse_tool_choice(
            f'{{"hades_tool_call":{{"plugin_id":"hades","tool_name":"{DISCOVER_TOOL_NAME}","input":{{"query":"x","offset":0}}}}}}'
        )
        self.assertIsNotNone(choice2)
        assert choice2 is not None
        self.assertEqual(choice2["tool_name"], DISCOVER_TOOL_NAME)

    def test_tool_loop_source_keeps_discovery_when_shortlist_empty(self) -> None:
        """Regression: empty shortlist must not force max_rounds=0 (blocks discovery)."""
        from pathlib import Path

        main_source = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")
        start = main_source.index("async def run_model_with_optional_tool")
        end = main_source.index("\ndef maybe_store_conversation_memory", start)
        fn = main_source[start:end]
        self.assertNotIn("if not tools:\n        max_rounds = 0", fn)
        self.assertIn("run_tool_engine", fn)
        self.assertIn("allow_text_fallback=True", fn)
        engine = Path(__file__).resolve().parents[1].joinpath("reasoning", "tool_engine.py").read_text(encoding="utf-8")
        self.assertIn("include_discover_hint=True", engine)
        self.assertIn("DISCOVER_TOOL_NAME", engine)
        protocol = Path(__file__).resolve().parents[1].joinpath("reasoning", "tool_protocol.py").read_text(encoding="utf-8")
        self.assertIn("classify_model_response", protocol)
        self.assertIn("TOOL_CALLS", protocol)

    def test_discovery_include_unscored_finds_zero_overlap_tools(self) -> None:
        plugins = [
            {
                "id": "p1",
                "name": "Obscure",
                "description": "zzz",
                "enabled": True,
                "status": "ready",
                "trust": "manual",
                "category": "Tool",
                "manifest": {"autonomous": True, "category": "Tool"},
            }
        ]
        tools = [
            {
                "plugin_id": "p1",
                "name": "obscure_action",
                "description": "zzz",
                "enabled": True,
                "input_schema": {},
                "metadata": {},
            }
        ]
        scored_only = discover_tools(
            query="completely unrelated query about bananas",
            plugins=plugins,
            tools=tools,
            permission_ok=lambda _p, _t: True,
            limit=8,
            offset=0,
            include_unscored=False,
        )
        with_unscored = discover_tools(
            query="completely unrelated query about bananas",
            plugins=plugins,
            tools=tools,
            permission_ok=lambda _p, _t: True,
            limit=8,
            offset=0,
            include_unscored=True,
        )
        self.assertEqual(scored_only["total"], 0)
        self.assertEqual(with_unscored["total"], 1)

    def test_tool_discovery_can_page_beyond_first_shortlist(self) -> None:
        plugins = [
            {
                "id": f"p{i}",
                "name": f"Plugin {i}",
                "description": "utility helper",
                "enabled": True,
                "status": "ready",
                "trust": "manual",
                "category": "Tool",
                "manifest": {"autonomous": True, "category": "Tool"},
            }
            for i in range(12)
        ]
        tools = [
            {
                "plugin_id": f"p{i}",
                "name": f"tool_{i}",
                "description": "utility helper",
                "enabled": True,
                "input_schema": {},
                "metadata": {},
            }
            for i in range(12)
        ]
        page1 = discover_tools(
            query="utility",
            plugins=plugins,
            tools=tools,
            permission_ok=lambda _p, _t: True,
            limit=5,
            offset=0,
        )
        page2 = discover_tools(
            query="utility",
            plugins=plugins,
            tools=tools,
            permission_ok=lambda _p, _t: True,
            limit=5,
            offset=5,
        )
        self.assertEqual(page1["total"], 12)
        self.assertEqual(len(page1["tools"]), 5)
        self.assertEqual(len(page2["tools"]), 5)
        self.assertNotEqual(page1["tools"][0]["tool_name"], page2["tools"][0]["tool_name"])
        self.assertEqual(page1["next_offset"], 5)

    def test_verification_rejects_missing_or_fake_success(self) -> None:
        ok, _reason = verification_allows_success(None)
        self.assertFalse(ok)

        parsed = parse_verification_result(
            '{"passed":true,"issues":[],"final":"","evidence_refs":[],"incomplete":false}'
        )
        ok, _reason = verification_allows_success(parsed)
        self.assertFalse(ok)

        parsed_fail = parse_verification_result(
            '{"passed":false,"issues":["geen bewijs"],"final":"nee","evidence_refs":[]}'
        )
        ok, _reason = verification_allows_success(parsed_fail)
        self.assertFalse(ok)

        parsed_tool_no_evidence = parse_verification_result(
            '{"passed":true,"issues":[],"final":"Klaar","evidence_refs":[],"incomplete":false,'
            '"criteria_checklist":[{"id":"c1","criterion":"De oorspronkelijke opdracht is volledig uitgevoerd.","met":true}]}'
        )
        ok, reason = verification_allows_success(
            parsed_tool_no_evidence,
            tool_observations=[{"status": "completed", "plugin_id": "p", "tool_name": "t"}],
            acceptance_criteria=["De oorspronkelijke opdracht is volledig uitgevoerd."],
        )
        self.assertFalse(ok)
        self.assertIn("bewijs", reason.lower())

        parsed_pass = parse_verification_result(
            '{"passed":true,"issues":[],"final":"Klaar met bewijs","evidence_refs":["step:1"],'
            '"criteria_checklist":[{"id":"c1","criterion":"De oorspronkelijke opdracht is volledig uitgevoerd.","met":true}]}'
        )
        ok, reason = verification_allows_success(
            parsed_pass,
            step_outputs=[{"title": "Stap", "agent_id": "executor", "output": "ok"}],
            acceptance_criteria=["De oorspronkelijke opdracht is volledig uitgevoerd."],
        )
        self.assertTrue(ok, reason)
        self.assertEqual(reason, "")


def _ready_plugin(index: int, *, name: str | None = None) -> dict:
    label = name or f"Plugin {index}"
    return {
        "id": f"p{index}",
        "name": label,
        "description": "zzz",
        "enabled": True,
        "status": "ready",
        "trust": "manual",
        "category": "Tool",
        "manifest": {"autonomous": True, "category": "Tool"},
    }


def _ready_tool(index: int, *, description: str = "zzz") -> dict:
    return {
        "plugin_id": f"p{index}",
        "name": f"tool_{index}",
        "description": description,
        "enabled": True,
        "input_schema": {},
        "metadata": {"autonomous": True},
    }


class PluginCatalogVisibilityTests(unittest.TestCase):
    def test_directory_lists_all_enabled_plugins(self) -> None:
        from reasoning.tools import build_plugin_directory, render_plugin_directory

        plugins = [_ready_plugin(i) for i in range(8)]
        tools = [_ready_tool(i) for i in range(8)]
        directory = build_plugin_directory(plugins=plugins, tools=tools, permission_ok=lambda _p, _t: True)
        self.assertEqual(directory["eligible_plugin_count"], 8)
        text = render_plugin_directory(directory)
        self.assertIn("OPTIONAL CAPABILITIES", text)
        self.assertIn("hades.capabilities.search", text)
        for i in range(8):
            self.assertIn(f"p{i}", text)
            self.assertIn(f"tool_{i}", text)

    def test_shortlist_fills_beyond_single_lexical_hit(self) -> None:
        from reasoning.tool_registry import shortlist_with_exact_priority

        plugins = [_ready_plugin(i, name=f"Alpha{i}") for i in range(8)]
        tools = [_ready_tool(i, description="zzz") for i in range(8)]
        tools[0]["description"] = "plugin helper"
        scored = discover_tools(
            query="daadwerkelijk de plugin gebruiken",
            plugins=plugins,
            tools=tools,
            permission_ok=lambda _p, _t: True,
            include_unscored=False,
        )
        self.assertEqual(scored["total"], 1)
        shortlist = shortlist_with_exact_priority(
            query="daadwerkelijk de plugin gebruiken",
            plugins=plugins,
            tools=tools,
            permission_ok=lambda _p, _t: True,
            limit=8,
        )
        plugin_ids = {item["plugin_id"] for item in shortlist}
        self.assertGreaterEqual(len(plugin_ids), 8)

    def test_native_engine_injects_directory_in_native_mode(self) -> None:
        import asyncio

        from reasoning.tool_engine import ToolEngineConfig, run_tool_engine

        captured: list[dict] = []

        async def chat(payload: dict) -> dict:
            captured.append(payload)
            return {
                "choices": [{"message": {"role": "assistant", "content": "Klaar zonder toolcall."}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

        def build_payload(messages, native_tools):
            return {"messages": messages, "tools": native_tools, "model": "x"}

        asyncio.run(
            run_tool_engine(
                messages=[{"role": "user", "content": "gebruik een plugin"}],
                query="gebruik een plugin",
                tools=[
                    {
                        "plugin_id": "only",
                        "name": "one",
                        "description": "plugin helper",
                        "input_schema": {},
                        "metadata": {},
                        "plugin": {"name": "Only", "category": "Tool"},
                    }
                ],
                chat=chat,
                build_payload=build_payload,
                invoke=lambda *_a, **_k: {"status": "completed", "exit_code": 0},
                config=ToolEngineConfig(
                    autonomous=True,
                    max_rounds=1,
                    tool_call_mode="native",
                    plugin_directory="HADES PLUGIN-OVERZICHT\n- Alpha [a]\n- Beta [b]",
                ),
            )
        )
        self.assertTrue(captured)
        sys_msgs = [m.get("content") for m in captured[0]["messages"] if m.get("role") == "system"]
        self.assertTrue(any("Alpha [a]" in str(item) and "Beta [b]" in str(item) for item in sys_msgs))


if __name__ == "__main__":
    unittest.main()
