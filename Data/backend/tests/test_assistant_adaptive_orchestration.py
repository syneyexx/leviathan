"""GI4/GI5/GI12 — adaptive orchestration, orchestra selection, context regressions."""

from __future__ import annotations

import unittest

from Data.modules.agents.general_orchestra import (
    GENERAL_INTELLIGENCE_ORCHESTRA_KEY,
    general_intelligence_orchestra_seed,
    select_gi_specialists,
)
from Data.modules.cognition.task_model import TaskModelBuilder
from Data.modules.compute.numeric import NumericComputeEngine
from Data.modules.context.builder import ContextBuilder
from Data.modules.reasoning import ReasoningPlan


class AdaptiveTaskModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = TaskModelBuilder()

    def test_greeting_is_direct_fast_path(self) -> None:
        task = self.builder.build("hoi")
        self.assertEqual(task.execution_class, "DIRECT")
        self.assertEqual(task.verification_mode, "NONE")
        self.assertFalse(task.needs_specialists)

    def test_current_info_routes_to_web_class(self) -> None:
        task = self.builder.build("Wat is de nieuwste Python-versie vandaag?")
        self.assertTrue(task.requires_current_information)
        self.assertEqual(task.freshness_requirement, "required")
        self.assertIn(task.execution_class, {"CURRENT_INFO", "WORK"})
        self.assertEqual(task.verification_mode, "REQUIRED")

    def test_self_inspect_requires_tools_not_guess(self) -> None:
        task = self.builder.build("Welk model gebruik je nu?")
        self.assertEqual(task.execution_class, "TOOL_REQUIRED")
        self.assertEqual(task.verification_mode, "REQUIRED")

    def test_calculation_prefers_tool_path(self) -> None:
        task = self.builder.build("Wat is 17 * 23?")
        self.assertTrue(task.needs_calculation)
        self.assertEqual(task.execution_class, "TOOL_REQUIRED")


class OrchestraSelectionTests(unittest.TestCase):
    def test_seed_includes_gi_orchestra(self) -> None:
        seeds = general_intelligence_orchestra_seed()
        keys = {str((s.get("metadata") or {}).get("systemKey")) for s in seeds}
        self.assertIn(GENERAL_INTELLIGENCE_ORCHESTRA_KEY, keys)
        self.assertIn("gi_system_inspector", keys)

    def test_direct_selects_no_specialists(self) -> None:
        task = TaskModelBuilder().build("dankjewel")
        selected = select_gi_specialists(task.public_dict())
        self.assertEqual(selected, [])

    def test_complex_research_selects_bounded_specialists(self) -> None:
        task = TaskModelBuilder().build("Onderzoek onderwerp X uitgebreid en vergelijk bronnen")
        selected = select_gi_specialists(task.public_dict(), max_specialists=4)
        self.assertLessEqual(len(selected), 4)
        self.assertTrue(selected)
        self.assertIn("gi_web_research", selected)


class ContextLatestTurnAndRetrievalTests(unittest.TestCase):
    def test_latest_user_turn_survives_duplicate_earlier_content(self) -> None:
        builder = ContextBuilder(token_budget=800, auto_budget=False)
        marker = "UNIQUE_LATEST_TURN_MARKER_42"
        history = [
            {"role": "user", "content": marker},
            {"role": "assistant", "content": "earlier reply"},
            {"role": "user", "content": "filler " + ("x" * 200)},
            {"role": "assistant", "content": "more " + ("y" * 200)},
            {"role": "user", "content": marker},  # duplicate text — must still be present as latest
        ]
        pack = builder.build(
            history=history,
            knowledge=[],
            plan=ReasoningPlan(
                intent="question",
                complexity="low",
                use_knowledge=False,
                steps=("answer",),
            ),
        )
        user_contents = [m["content"] for m in pack.messages if m.get("role") == "user"]
        self.assertTrue(user_contents)
        self.assertTrue(
            any(marker in c for c in user_contents),
            f"latest user marker missing from pack messages: {user_contents!r}",
        )
        last_user = None
        for m in pack.messages:
            if m.get("role") == "user":
                last_user = m
        self.assertIsNotNone(last_user)
        self.assertIn(marker, str(last_user.get("content") or ""))

    def test_large_retrieval_degrades_gracefully_not_all_or_nothing(self) -> None:
        builder = ContextBuilder(token_budget=1200, auto_budget=False, max_knowledge_chars=2000)
        huge = "ALPHA_CHUNK " + ("knowledge-block " * 400)
        medium = "BETA_CHUNK " + ("mid-size evidence " * 40)
        small = "GAMMA_CHUNK small evidence piece"
        pack = builder.build(
            history=[{"role": "user", "content": "Summarize the sources."}],
            knowledge=[
                {"title": "huge", "source": "test", "content": huge, "id": "d1"},
                {"title": "medium", "source": "test", "content": medium, "id": "d2"},
                {"title": "small", "source": "test", "content": small, "id": "d3"},
            ],
            plan=ReasoningPlan(
                intent="knowledge",
                complexity="medium",
                use_knowledge=True,
                steps=("retrieve", "answer"),
            ),
            behavior_profile_prompt="You are LEVIATHAN.",
        )
        joined = " ".join(m.get("content") or "" for m in pack.messages)
        self.assertTrue(
            ("ALPHA_CHUNK" in joined) or ("BETA_CHUNK" in joined) or ("GAMMA_CHUNK" in joined),
            "expected partial retrieval retention under budget pressure",
        )
        self.assertGreater(pack.knowledge_count, 0)
        # Prefer keeping the small piece when the huge source does not fit whole.
        self.assertIn("GAMMA_CHUNK", joined)


class SafeCalculatorTests(unittest.TestCase):
    def test_expression_ast_no_eval(self) -> None:
        result = NumericComputeEngine().evaluate_expression("2 + 3 * 4")
        self.assertEqual(result.value, 14.0)

    def test_rejects_names_and_calls(self) -> None:
        with self.assertRaises(ValueError):
            NumericComputeEngine().evaluate_expression("__import__('os').system('x')")
        with self.assertRaises(ValueError):
            NumericComputeEngine().evaluate_expression("pow(2, 10)")


if __name__ == "__main__":
    unittest.main()
