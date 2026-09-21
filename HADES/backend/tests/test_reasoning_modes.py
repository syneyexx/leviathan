"""Behavior tests for Normal / Medium / High / Adaptive — written, not executed here."""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reasoning.atomic_budget import BudgetExhausted, SharedBudgetPool
from reasoning.budgets import ExecutionBudget, scale_execution_budget
from reasoning.contracts import TaskFeatures
from reasoning.mode_policy import (
    POLICY_VERSION,
    ModeValidationError,
    parse_mode_input,
    try_canonicalize_enum,
)
from reasoning.orchestration import ExecutedRoute, should_run_verification
from reasoning.profiles import resolve_reasoning_profile
from reasoning.steering import action_fingerprint, next_steering_action
from reasoning.understanding import (
    build_request_spec,
    build_route_decision,
    extract_task_features,
    maybe_escalate_profile,
    needs_structured_classification,
    parse_classifier_output,
    score_complexity,
    should_require_llm_critic,
)


class ModeMappingTests(unittest.TestCase):
    def test_legacy_values_map_to_product_modes(self) -> None:
        fast = parse_mode_input("fast", source="api")
        self.assertEqual(fast.selected_mode, "normal")
        self.assertEqual(fast.effective_policy, "fast")
        self.assertEqual(fast.compatibility, "legacy_fast_maps_to_normal")
        standard = parse_mode_input("standard", source="stored")
        self.assertEqual(standard.selected_mode, "medium")
        maximum = parse_mode_input("maximum", source="stored")
        self.assertEqual(maximum.selected_mode, "high")
        self.assertEqual(maximum.effective_policy, "maximum")
        self.assertEqual(maximum.persist_value, "maximum")
        self.assertEqual(maximum.policy_version, POLICY_VERSION)

    def test_explicit_product_modes_are_not_adaptive(self) -> None:
        for raw, policy in (("normal", "fast"), ("medium", "standard"), ("high", "high")):
            resolved = parse_mode_input(raw, source="api")
            self.assertTrue(resolved.explicit)
            self.assertEqual(resolved.effective_policy, policy)
            self.assertNotEqual(resolved.selected_mode, "adaptive")

    def test_invalid_api_mode_is_rejected(self) -> None:
        with self.assertRaises(ModeValidationError):
            parse_mode_input("turbo", source="api", allow_unknown=False)

    def test_invalid_stored_mode_falls_back_adaptively(self) -> None:
        resolved = parse_mode_input("turbo", source="stored", allow_unknown=True)
        self.assertEqual(resolved.selected_mode, "adaptive")
        self.assertIn("fallback_adaptive", resolved.decision_reason)

    def test_control_enum_canonicalizes_legacy(self) -> None:
        self.assertEqual(try_canonicalize_enum("reasoning_profile", "fast"), "normal")
        self.assertEqual(try_canonicalize_enum("reasoning_profile", "standard"), "medium")
        self.assertEqual(try_canonicalize_enum("reasoning_profile", "maximum"), "maximum")
        self.assertIsNone(try_canonicalize_enum("theme", "fast"))


class StructuredDecisionTests(unittest.TestCase):
    def test_simple_greeting_stays_direct_without_extra_calls(self) -> None:
        chosen, spec, meta = resolve_reasoning_profile("Hoi, hoe gaat het?", "adaptive")
        route = build_route_decision(
            spec,
            requested_profile="adaptive",
            network_policy="block",
            plugin_tools_enabled=True,
        )
        self.assertEqual(chosen, "fast")
        self.assertEqual(route.target, "direct_chat")
        self.assertFalse(route.require_verification)
        self.assertFalse(route.allow_tools)
        self.assertEqual(route.max_tool_rounds, 0)
        self.assertEqual(meta["selected_mode"], "adaptive")
        self.assertFalse(meta["needs_classifier"])

    def test_long_simple_explanation_does_not_force_high(self) -> None:
        text = "Leg uit wat een list in Python is. " + ("voorbeeld " * 400)
        chosen, spec, meta = resolve_reasoning_profile(text, "adaptive")
        features = extract_task_features(spec)
        self.assertNotEqual(chosen, "high")
        self.assertNotEqual(chosen, "maximum")
        self.assertIn(chosen, {"fast", "standard"})
        self.assertTrue(features.speech_act in {"explain", "inform", "question"} or spec.kind in {"analysis", "question"})
        self.assertLess(meta["complexity"]["length_hint"], 1.0)

    def test_short_hard_task_does_not_force_normal(self) -> None:
        text = (
            "Debug deze Traceback Exception en refactor de architectuur. "
            "Maak een plan met tests en evidence. Geen cloud."
        )
        chosen, spec, _meta = resolve_reasoning_profile(text, "adaptive")
        self.assertIn(chosen, {"high", "maximum", "standard"})
        self.assertNotEqual(chosen, "fast")
        self.assertIn(spec.kind, {"debug", "code", "planning"})

    def test_explicit_modes_are_stored_and_applied(self) -> None:
        for requested, expected_policy in (("normal", "fast"), ("medium", "standard"), ("high", "high"), ("fast", "fast")):
            chosen, spec, meta = resolve_reasoning_profile("Hoi", requested)
            self.assertEqual(chosen, expected_policy)
            self.assertEqual(meta["selected_mode"], parse_mode_input(requested).selected_mode)
            self.assertTrue(meta["explicit"] or requested == "adaptive")
            route = build_route_decision(
                spec,
                requested_profile=requested,
                network_policy="block",
                plugin_tools_enabled=True,
            )
            self.assertEqual(route.selected_mode, meta["selected_mode"])
            self.assertEqual(route.effective_policy, expected_policy)

    def test_explicit_high_simple_question_skips_critic(self) -> None:
        spec = build_request_spec("Wat is een list in Python?")
        route = build_route_decision(
            spec,
            requested_profile="high",
            network_policy="block",
            plugin_tools_enabled=True,
        )
        self.assertEqual(route.profile, "high")
        self.assertEqual(route.target, "direct_chat")
        self.assertFalse(route.require_verification)
        self.assertFalse(should_require_llm_critic(spec, "high", extract_task_features(spec)))

    def test_adaptive_escalates_only_on_evidence(self) -> None:
        self.assertEqual(maybe_escalate_profile("fast", observed_failure=True, selected_mode="adaptive"), "standard")
        self.assertEqual(
            maybe_escalate_profile("fast", tool_failure=True, selected_mode="normal", signal="invalid_tool_argument"),
            "fast",
        )
        self.assertEqual(
            maybe_escalate_profile("fast", tool_failure=True, selected_mode="adaptive", signal="invalid_tool_argument"),
            "fast",
        )
        scaled = maybe_escalate_profile(
            "fast",
            evidence_gap=True,
            selected_mode="adaptive",
            signal="acceptance_unmet",
        )
        self.assertEqual(scaled, "standard")

    def test_negations_and_quoted_tools_do_not_execute(self) -> None:
        spec = build_request_spec('Wat betekent de tekst "verwijder alle bestanden nu"?')
        self.assertNotEqual(spec.speech_act, "execute")
        self.assertFalse(spec.needs_tools)
        route = build_route_decision(spec, requested_profile="high", network_policy="allow", plugin_tools_enabled=True)
        self.assertFalse(route.allow_tools)
        self.assertEqual(route.max_tool_rounds, 0)

    def test_blocked_network_is_not_bypassed_for_freshness(self) -> None:
        spec = build_request_spec("Zoek de actuele prijs van BTC vandaag")
        route = build_route_decision(
            spec,
            requested_profile="adaptive",
            network_policy="block",
            plugin_tools_enabled=True,
        )
        self.assertFalse(route.allow_web)
        self.assertTrue(spec.needs_research)

    def test_invalid_classifier_output_uses_bounded_fallback(self) -> None:
        self.assertIsNone(parse_classifier_output("not-json"))
        self.assertIsNone(parse_classifier_output('{"intent":"hack_the_planet"}'))
        parsed = parse_classifier_output(
            '{"intent":"explain","independent_outcomes":1,"has_dependencies":false,'
            '"ambiguity":"low","freshness":false,"tools":false,"evidence_kind":"explanation"}'
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["intent"], "explain")
        self.assertFalse(parsed["tools"])

    def test_heuristic_score_is_labeled_uncalibrated(self) -> None:
        spec = build_request_spec("Hoi")
        scored = score_complexity(spec)
        self.assertEqual(scored["kind"], "uncalibrated_hint")
        features = extract_task_features(spec)
        self.assertEqual(features.heuristic_score_kind, "uncalibrated_hint")


class SteeringAndBudgetTests(unittest.TestCase):
    def test_missing_capability_stops_instead_of_looping(self) -> None:
        decision = next_steering_action(
            "capability_missing",
            profile="fast",
            selected_mode="adaptive",
            fingerprint="abc",
        )
        self.assertTrue(decision.terminal)
        self.assertEqual(decision.action, "report_block")

    def test_identical_failure_is_not_repeated(self) -> None:
        fp = action_fingerprint("p", "t", {"x": 1})
        from reasoning.steering import AttemptRecord

        decision = next_steering_action(
            "invalid_tool_argument",
            attempts=[AttemptRecord(kind="tool", fingerprint=fp, outcome="failed", signal="invalid_tool_argument")],
            profile="standard",
            selected_mode="adaptive",
            fingerprint=fp,
        )
        self.assertEqual(decision.action, "stop")
        self.assertEqual(decision.signal, "repeated_no_new_info")

    def test_concurrent_leases_cannot_overspend(self) -> None:
        pool = SharedBudgetPool(max_model_calls=3)
        successes: list[int] = []
        errors: list[int] = []

        def worker() -> None:
            try:
                pool.lease("model", 1)
                pool.commit_lease("model", 1)
                successes.append(1)
            except BudgetExhausted:
                errors.append(1)

        threads = [threading.Thread(target=worker) for _ in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(successes), 3)
        self.assertEqual(sum(errors), 9)
        snap = pool.snapshot()
        self.assertEqual(snap["model_calls"], 3)
        self.assertEqual(snap["leased_model_calls"], 0)

    def test_unused_lease_is_released(self) -> None:
        pool = SharedBudgetPool(max_model_calls=1)
        pool.lease("model", 1)
        pool.release_lease("model", 1)
        pool.lease("model", 1)
        pool.commit_lease("model", 1)
        self.assertEqual(pool.snapshot()["model_calls"], 1)

    def test_missing_provider_usage_stays_unknown_not_zero(self) -> None:
        budget = ExecutionBudget(max_model_calls=4, max_tool_rounds=1)
        budget.apply_provider_usage(None)
        self.assertEqual(budget.usage_kind, "unavailable")
        self.assertIsNone(budget.input_tokens)
        self.assertFalse(budget.monetary_known)
        self.assertIsNone(budget.monetary_cost)
        budget.apply_provider_usage({}, estimated={"completion_tokens": 12})
        self.assertEqual(budget.usage_kind, "estimate")
        budget.apply_provider_usage({"prompt_tokens": 10, "completion_tokens": 4})
        self.assertEqual(budget.usage_kind, "exact")

    def test_scale_execution_budget_raises_ceiling_without_resetting_usage(self) -> None:
        budget = ExecutionBudget(max_model_calls=2, max_tool_rounds=1, max_replans=0)
        budget.record_model_call()
        changed = scale_execution_budget(budget, "standard")
        self.assertTrue(changed)
        self.assertGreaterEqual(int(budget.max_model_calls or 0), 6)
        self.assertGreaterEqual(int(budget.max_tool_rounds or 0), 3)
        self.assertEqual(budget.model_calls, 1)
        self.assertIn("adaptive_scaled:standard", budget.notes)

    def test_classifier_is_not_a_toll_for_explicit_modes(self) -> None:
        spec = build_request_spec("Misschien iets uitvoeren of alleen uitleggen")
        features = TaskFeatures(material_uncertainty=True, direct_answer=False)
        self.assertFalse(needs_structured_classification(spec, features, selected_mode="normal"))
        self.assertFalse(needs_structured_classification(spec, features, selected_mode="medium"))
        self.assertFalse(needs_structured_classification(spec, features, selected_mode="high"))
        self.assertTrue(needs_structured_classification(spec, features, selected_mode="adaptive"))

    def test_completed_simple_task_skips_critic(self) -> None:
        spec = build_request_spec("Hoi")
        route = build_route_decision(
            spec,
            requested_profile="high",
            network_policy="block",
            plugin_tools_enabled=True,
        )
        self.assertFalse(should_run_verification(route, profile_name="high", spec=spec))

    def test_cancel_status_is_not_success(self) -> None:
        executed = ExecutedRoute(intended_target="direct_chat", actual_target="direct_chat", status="cancelled")
        self.assertEqual(executed.status, "cancelled")
        self.assertNotEqual(executed.status, "completed")

    def test_resume_restores_consumed_budget(self) -> None:
        baseline = ExecutionBudget(max_model_calls=6, max_tool_rounds=3)
        restored = ExecutionBudget.from_dict(
            {"model_calls": 2, "tool_rounds": 1, "usage_kind": "exact", "input_tokens": 40},
            baseline=baseline,
        )
        self.assertEqual(restored.model_calls, 2)
        self.assertEqual(restored.max_model_calls, 6)
        self.assertEqual(restored.remaining_model_calls(), 4)

    def test_exhausted_budget_is_not_success(self) -> None:
        budget = ExecutionBudget(max_model_calls=1, max_tool_rounds=0, reserved_verification_calls=0, reserved_finalize_calls=0)
        budget.record_model_call()
        self.assertTrue(budget.exhausted_without_success())


class ApiSurfaceTests(unittest.TestCase):
    def test_chat_input_rejects_invalid_mode(self) -> None:
        from pydantic import ValidationError

        import main

        with self.assertRaises(ValidationError):
            main.ChatInput(content="Hoi", reasoning_profile="turbo")

    def test_chat_input_accepts_legacy_and_product(self) -> None:
        import main

        self.assertEqual(main.ChatInput(content="Hoi", reasoning_profile="fast").reasoning_profile, "fast")
        self.assertEqual(main.ChatInput(content="Hoi", reasoning_profile="normal").reasoning_profile, "normal")
        self.assertEqual(main.ChatInput(content="Hoi", reasoning_profile="maximum").reasoning_profile, "maximum")

    def test_settings_input_rejects_invalid_mode(self) -> None:
        from pydantic import ValidationError

        import main

        with self.assertRaises(ValidationError):
            main.SettingsInput(reasoning_profile="turbo")


if __name__ == "__main__":
    unittest.main()
