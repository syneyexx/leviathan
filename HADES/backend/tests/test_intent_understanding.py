"""Intent understanding: explain vs execute, negations, quotes, follow-ups."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reasoning.understanding import (
    build_request_spec,
    build_route_decision,
    choose_adaptive_profile,
    maybe_early_stop,
    maybe_escalate_profile,
)


class ExplainVsExecuteTests(unittest.TestCase):
    def test_explain_delete_is_not_execute(self) -> None:
        spec = build_request_spec("Leg uit wat deze delete-opdracht doet")
        self.assertEqual(spec.speech_act, "explain")
        self.assertNotEqual(spec.kind, "tool_use")
        self.assertFalse(spec.needs_tools)
        self.assertEqual(spec.risk_level, "low")
        self.assertIn(spec.kind, {"analysis", "question"})

    def test_remember_not_is_not_memory_write(self) -> None:
        spec = build_request_spec("Onthoud dit niet")
        self.assertFalse(spec.needs_memory_write)
        self.assertNotEqual(spec.kind, "memory_write")

    def test_no_tools_constraint(self) -> None:
        spec = build_request_spec("Gebruik geen tools, leg uit hoe caching werkt")
        self.assertFalse(spec.needs_tools)
        self.assertTrue(any("geen tools" in c.lower() for c in spec.constraints))
        route = build_route_decision(
            spec,
            requested_profile="adaptive",
            network_policy="block",
            plugin_tools_enabled=True,
        )
        self.assertFalse(route.allow_tools)

    def test_quoted_delete_not_execute(self) -> None:
        spec = build_request_spec('Wat betekent de tekst "verwijder alle bestanden nu"?')
        self.assertNotEqual(spec.speech_act, "execute")
        self.assertNotEqual(spec.kind, "tool_use")
        self.assertFalse(spec.needs_tools)

    def test_raw_text_preserved_when_goal_truncated(self) -> None:
        long = "X" * 400
        spec = build_request_spec(long)
        self.assertEqual(spec.raw_text, long)
        self.assertLessEqual(len(spec.goal), 240)

    def test_choice_question_not_auto_block(self) -> None:
        spec = build_request_spec("A of B?")
        route = build_route_decision(
            spec,
            requested_profile="fast",
            network_policy="block",
            plugin_tools_enabled=False,
        )
        self.assertFalse(route.stop_and_ask)

    def test_follow_up_uses_conversation_state(self) -> None:
        spec = build_request_spec(
            "Waarom faalt dit?",
            conversation_state={"last_assistant": "deploy failed", "recent_failures": ["timeout"]},
        )
        self.assertTrue(spec.interpretation.get("follow_up"))
        self.assertEqual(spec.kind, "debug")

    def test_gebruik_named_plugin_is_tool_use(self) -> None:
        for text in (
            "Gebruik multi-echo voor een taak met meerdere stappen",
            "Gebruik available-echo voor deze taak",
            "Gebruik Humanizer om dit antwoord natuurlijker te maken: Hallo wereld.",
        ):
            with self.subTest(text=text):
                spec = build_request_spec(text)
                self.assertEqual(spec.kind, "tool_use", text)
                self.assertTrue(spec.needs_tools, text)
                route = build_route_decision(
                    spec,
                    requested_profile="adaptive",
                    network_policy="block",
                    plugin_tools_enabled=True,
                )
                self.assertTrue(route.allow_tools, text)
                self.assertGreater(route.max_tool_rounds, 0, text)
                self.assertEqual(route.target, "tool_loop", text)

    def test_followup_plugin_gebruiken_enables_tools(self) -> None:
        """Dutch follow-ups must not stay a question with tools disabled."""
        for text in (
            "kan jij het maken? maar daadwerkelijk de plugin gebruiken.",
            "Maak de type story en gebruik een plugin.",
            "Please actually use a plugin to do this.",
        ):
            with self.subTest(text=text):
                spec = build_request_spec(text)
                self.assertTrue(spec.needs_tools, text)
                self.assertEqual(spec.kind, "tool_use", text)
                self.assertEqual(spec.speech_act, "execute", text)
                route = build_route_decision(
                    spec,
                    requested_profile="adaptive",
                    network_policy="block",
                    plugin_tools_enabled=True,
                )
                self.assertTrue(route.allow_tools, text)
                self.assertGreater(route.max_tool_rounds, 0, text)

    def test_explain_plugin_is_direct_chat_without_tools(self) -> None:
        """Simple explain turns stay direct_chat; user must request tools or use an actionable route."""
        spec = build_request_spec("Leg uit wat een plugin doet")
        self.assertFalse(spec.needs_tools)
        route = build_route_decision(
            spec,
            requested_profile="high",
            network_policy="block",
            plugin_tools_enabled=True,
        )
        self.assertEqual(route.target, "direct_chat")
        self.assertFalse(route.allow_tools)
        self.assertEqual(route.max_tool_rounds, 0)


class AdaptiveDepthTests(unittest.TestCase):
    def test_simple_question_fast(self) -> None:
        spec = build_request_spec("Wat is een list in Python?")
        self.assertEqual(choose_adaptive_profile(spec), "fast")

    def test_escalate_on_failure(self) -> None:
        self.assertEqual(maybe_escalate_profile("fast", observed_failure=True), "standard")
        self.assertEqual(maybe_escalate_profile("high", tool_failure=True), "maximum")

    def test_early_stop_when_sufficient(self) -> None:
        self.assertTrue(maybe_early_stop("maximum", checklist_all_met=True, evidence_sufficient=True))
        self.assertFalse(maybe_early_stop("maximum", checklist_all_met=False, evidence_sufficient=True))


if __name__ == "__main__":
    unittest.main()
