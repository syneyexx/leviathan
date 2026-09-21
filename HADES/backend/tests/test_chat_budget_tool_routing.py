"""Regression: per-run budgets + direct-chat tool routing.

Deterministic — no LM Studio required.

Protects:
- simple direct chat does not expose tools / burn Normal budget
- new turns after partial/blocked get a fresh execution budget
- true same-run resume restores consumed counters
- genuine tool turns and no-tools constraints still work
- budget exhaustion remains honest (no false success)
- verification reserve accounting stays valid
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core_tools import build_chat_tool_shortlist
from core_tools.catalog import FS_READ
from reasoning.budgets import (
    ExecutionBudget,
    budget_from_profile,
    should_restore_execution_budget,
)
from reasoning.orchestration import ExecutedRoute, should_run_verification
from reasoning.profiles import resolve_reasoning_profile
from reasoning.understanding import (
    build_request_spec,
    build_route_decision,
    extract_task_features,
)


def _route(text: str, *, profile: str = "adaptive", network: str = "block", tools_on: bool = True):
    chosen, spec, _meta = resolve_reasoning_profile(text, profile)
    features = extract_task_features(spec)
    route = build_route_decision(
        spec,
        requested_profile=profile,
        network_policy=network,
        plugin_tools_enabled=tools_on,
        features=features,
    )
    budget = budget_from_profile(
        profile_name=route.profile or chosen,
        settings_max_tool_rounds=3,
        route_max_tool_rounds=route.max_tool_rounds,
        tools_allowed=tools_on and route.allow_tools,
    )
    return chosen, spec, features, route, budget


class DirectChatRoutingTests(unittest.TestCase):
    def test_simple_greeting_routes_direct_without_tools(self) -> None:
        _chosen, spec, features, route, budget = _route("Hoe gaat het met jou?")
        self.assertTrue(features.direct_answer)
        self.assertFalse(spec.needs_tools)
        self.assertEqual(route.target, "direct_chat")
        self.assertFalse(route.require_verification)
        self.assertFalse(route.allow_tools)
        self.assertEqual(route.max_tool_rounds, 0)
        self.assertEqual(int(budget.max_tool_rounds or 0), 0)
        shortlist = build_chat_tool_shortlist(
            query="Hoe gaat het met jou?",
            plugins=[],
            tools=[],
            settings={"plugin_autonomous_tools": True},
            allow_tools=route.allow_tools,
        )
        self.assertEqual(shortlist, [])

    def test_hi_greeting_no_false_tool_budget(self) -> None:
        _chosen, _spec, _features, route, budget = _route("Hoi")
        self.assertEqual(route.target, "direct_chat")
        self.assertFalse(route.allow_tools)
        self.assertEqual(int(budget.max_tool_rounds or 0), 0)
        # A normal direct answer consumes one model call and must not look exhausted.
        budget.record_model_call()
        self.assertFalse(budget.exhausted_without_success())
        self.assertFalse(budget.can_tool_round())


class BudgetLifecycleTests(unittest.TestCase):
    def test_new_turn_after_partial_gets_fresh_budget(self) -> None:
        prior = ExecutionBudget(max_model_calls=2, max_tool_rounds=1)
        prior.model_calls = 2
        prior.tool_rounds = 1
        prior.stop_reason = "budget_exhausted"
        self.assertTrue(prior.exhausted_without_success())

        self.assertFalse(
            should_restore_execution_budget(
                prior_resume_run_id="run-a",
                current_client_request_id="run-b",
            )
        )
        # Status-based guessing must not restore — only explicit same-run identity.
        fresh = budget_from_profile(
            profile_name="fast",
            settings_max_tool_rounds=3,
            route_max_tool_rounds=0,
            tools_allowed=False,
        )
        self.assertEqual(fresh.model_calls, 0)
        self.assertEqual(fresh.tool_rounds, 0)
        self.assertFalse(fresh.exhausted_without_success())

    def test_new_turn_after_blocked_gets_fresh_budget(self) -> None:
        self.assertFalse(
            should_restore_execution_budget(
                prior_resume_run_id="blocked-run",
                current_client_request_id="next-user-turn",
            )
        )

    def test_same_run_resume_restores_consumed_budget(self) -> None:
        self.assertTrue(
            should_restore_execution_budget(
                prior_resume_run_id="same-run-id",
                current_client_request_id="same-run-id",
            )
        )
        prior = ExecutionBudget(max_model_calls=6, max_tool_rounds=3)
        prior.model_calls = 2
        prior.tool_rounds = 1
        prior.notes.append("mid_run")
        baseline = ExecutionBudget(max_model_calls=6, max_tool_rounds=3)
        restored = ExecutionBudget.from_dict(prior.to_dict(), baseline=baseline)
        self.assertEqual(restored.model_calls, 2)
        self.assertEqual(restored.tool_rounds, 1)
        self.assertIn("mid_run", restored.notes)

    def test_empty_ids_are_not_treated_as_same_run(self) -> None:
        self.assertFalse(
            should_restore_execution_budget(
                prior_resume_run_id="",
                current_client_request_id="",
            )
        )
        self.assertFalse(
            should_restore_execution_budget(
                prior_resume_run_id=None,
                current_client_request_id=None,
            )
        )

    def test_send_message_budget_restore_uses_run_identity_only(self) -> None:
        """Mirrors main.py contract: partial status alone must not restore."""
        prior_state = {
            "resume_run_id": "run-a",
            "run_budget": {
                "max_model_calls": 2,
                "max_tool_rounds": 1,
                "model_calls": 2,
                "tool_rounds": 1,
                "reserved_verification_calls": 0,
                "reserved_finalize_calls": 1,
            },
            "last_executed": {"status": "partial"},
        }
        fresh = budget_from_profile(
            profile_name="fast",
            settings_max_tool_rounds=3,
            route_max_tool_rounds=0,
            tools_allowed=False,
        )
        restore = should_restore_execution_budget(
            prior_resume_run_id=prior_state.get("resume_run_id"),
            current_client_request_id="run-b",
        )
        self.assertFalse(restore)
        used = (
            ExecutionBudget.from_dict(prior_state["run_budget"], baseline=fresh)
            if restore
            else fresh
        )
        self.assertEqual(used.model_calls, 0)
        self.assertFalse(used.exhausted_without_success())


class ToolAutonomyTests(unittest.TestCase):
    def test_tool_required_turn_still_allows_tools(self) -> None:
        for text in (
            "Lees bestand notes.txt",
            "Run de tests",
            "Gebruik plugin echo",
            "Controleer deze repository",
        ):
            _chosen, spec, _features, route, budget = _route(text)
            self.assertTrue(spec.needs_tools, text)
            self.assertTrue(route.allow_tools, text)
            self.assertGreaterEqual(route.max_tool_rounds, 1, text)
            self.assertGreaterEqual(int(budget.max_tool_rounds or 0), 1, text)
            shortlist = build_chat_tool_shortlist(
                query=text,
                plugins=[],
                tools=[],
                settings={"plugin_autonomous_tools": True, "network_policy": "block"},
                allow_tools=route.allow_tools,
            )
            self.assertIn(FS_READ, {str(item.get("name")) for item in shortlist}, text)

    def test_document_conversion_nl_keeps_tool_plane(self) -> None:
        """Actionable PDF/attachment/file NL must not lose tools via simple_direct."""
        from core_tools.catalog import CAPABILITIES_SEARCH

        actionable = (
            "Zet deze PDF om naar markdown",
            "Maak van dit document een .md bestand",
            "Lees deze bijlage en sla de inhoud op",
            "Pas dit bestand aan",
            "Download de pagina en zet hem in Knowledge",
            "Gebruik de beste beschikbare converter hiervoor",
            "Run de tests en vertel wat stuk is",
        )
        for text in actionable:
            _chosen, spec, features, route, budget = _route(text)
            self.assertFalse(features.direct_answer, text)
            self.assertTrue(spec.needs_tools, text)
            self.assertTrue(route.allow_tools, text)
            self.assertGreaterEqual(route.max_tool_rounds, 1, text)
            self.assertGreaterEqual(int(budget.max_tool_rounds or 0), 1, text)
            self.assertNotEqual(route.target, "direct_chat", text)
            shortlist = build_chat_tool_shortlist(
                query=text,
                plugins=[],
                tools=[],
                settings={"plugin_autonomous_tools": True, "network_policy": "block"},
                allow_tools=route.allow_tools,
            )
            names = {str(item.get("name")) for item in shortlist}
            self.assertTrue(names, text)
            # First-party capability broker (or fs_read) must be model-visible.
            self.assertTrue(
                CAPABILITIES_SEARCH in names or FS_READ in names,
                f"{text}: shortlist={names}",
            )

    def test_trivial_chat_still_skips_tool_schemas(self) -> None:
        _chosen, spec, features, route, budget = _route("Wat is 2+2?")
        self.assertTrue(features.direct_answer)
        self.assertFalse(spec.needs_tools)
        self.assertEqual(route.target, "direct_chat")
        self.assertFalse(route.allow_tools)
        self.assertEqual(route.max_tool_rounds, 0)
        self.assertEqual(int(budget.max_tool_rounds or 0), 0)

    def test_no_tools_constraint_suppresses_tools(self) -> None:
        _chosen, spec, _features, route, _budget = _route("gebruik geen tools, leg caching uit")
        self.assertTrue(
            "Geen tools gebruiken" in spec.constraints
            or bool((spec.interpretation or {}).get("wants_no_tools"))
        )
        self.assertFalse(route.allow_tools)
        self.assertEqual(route.max_tool_rounds, 0)

    def test_no_tools_still_suppresses_conversion_intent(self) -> None:
        _chosen, spec, _features, route, budget = _route(
            "gebruik geen tools — zet deze PDF om naar markdown"
        )
        self.assertTrue(bool((spec.interpretation or {}).get("wants_no_tools")))
        self.assertFalse(spec.needs_tools)
        self.assertFalse(route.allow_tools)
        self.assertEqual(route.max_tool_rounds, 0)
        self.assertEqual(int(budget.max_tool_rounds or 0), 0)
        shortlist = build_chat_tool_shortlist(
            query="gebruik geen tools — zet deze PDF om naar markdown",
            plugins=[],
            tools=[],
            settings={"plugin_autonomous_tools": True, "network_policy": "block"},
            allow_tools=route.allow_tools,
        )
        self.assertEqual(shortlist, [])

    def test_research_route_keeps_tool_autonomy_when_not_simple_direct(self) -> None:
        _chosen, spec, features, route, budget = _route(
            "Zoek actuele informatie over Python 3.13",
            network="allow",
        )
        self.assertTrue(spec.needs_research)
        self.assertFalse(features.direct_answer)
        self.assertTrue(route.allow_tools)
        self.assertGreaterEqual(int(budget.max_tool_rounds or 0), 1)


class ExecutionTruthBudgetTests(unittest.TestCase):
    def test_actual_exhaustion_prevents_false_success(self) -> None:
        budget = ExecutionBudget(
            max_model_calls=1,
            max_tool_rounds=0,
            reserved_verification_calls=0,
            reserved_finalize_calls=0,
        )
        budget.record_model_call()
        self.assertTrue(budget.exhausted_without_success())
        executed = ExecutedRoute(
            intended_target="direct_chat",
            actual_target="direct_chat",
            status="finished_unchecked",
        )
        if budget.exhausted_without_success() and executed.status in {
            "completed",
            "finished_unchecked",
            "running",
        }:
            executed.status = "partial"
            executed.notes.append("budget_exhausted_no_false_success")
        self.assertEqual(executed.status, "partial")
        self.assertIn("budget_exhausted_no_false_success", executed.notes)

    def test_verification_reserve_still_blocks_overspend(self) -> None:
        budget = ExecutionBudget(
            max_model_calls=3,
            max_tool_rounds=1,
            reserved_verification_calls=1,
            reserved_finalize_calls=1,
        )
        budget.record_model_call()  # answer draft
        # With reserve, only 3 - 1 - 2 = 0 remaining for further non-verify calls.
        self.assertFalse(budget.can_model_call(reserve_verification=True))
        self.assertTrue(budget.can_model_call(reserve_verification=False))
        # Direct-chat simple route must not steal the reserve: verification still gated.
        spec = build_request_spec("Hoi")
        features = extract_task_features(spec)
        route = build_route_decision(
            spec,
            requested_profile="high",
            network_policy="block",
            plugin_tools_enabled=True,
            features=features,
        )
        self.assertFalse(route.require_verification)
        self.assertFalse(should_run_verification(route, profile_name="high", spec=spec))


class MainBudgetRestoreIntegrationShapeTests(unittest.TestCase):
    def test_helper_matches_intended_main_gate(self) -> None:
        """Document the gate that main.py must use (identity, not status)."""
        values = MagicMock(client_request_id="client-2")
        prior_state = {
            "resume_run_id": "client-1",
            "last_executed": {"status": "partial"},
            "run_budget": {"model_calls": 2, "max_model_calls": 2, "tool_rounds": 1, "max_tool_rounds": 1},
        }
        # Old buggy condition would have restored here because status was partial.
        legacy_would_restore = str(prior_state.get("resume_run_id") or "") == str(
            values.client_request_id or ""
        ) or str((prior_state.get("last_executed") or {}).get("status") or "") in {
            "partial",
            "blocked",
            "running",
        }
        self.assertTrue(legacy_would_restore)
        self.assertFalse(
            should_restore_execution_budget(
                prior_resume_run_id=prior_state.get("resume_run_id"),
                current_client_request_id=values.client_request_id,
            )
        )


if __name__ == "__main__":
    unittest.main()
