"""F2 — Two-axis compute: NeuralComputeBudget + ReasoningCapabilityProfile."""

from __future__ import annotations

import unittest

from Data.backend.config import Settings
from Data.modules.cognition.meta_controller import MetaController
from Data.modules.cognition.neural_compute import (
    ClampReason,
    NativeEffort,
    NeuralComputeBudget,
    ReasoningCapabilityProfile,
    apply_capability_to_budget,
    neural_budget_for_mode,
    resolve_reasoning_capability_profile,
)
from Data.modules.cognition.task_model import TaskModelBuilder
from Data.modules.cognition.types import ReasoningMode
from Data.modules.intelligence.policy import ReasoningPolicy
from Data.modules.settings.catalog import build_catalog


class NeuralBudgetTests(unittest.TestCase):
    def test_mode_presets_two_axis(self) -> None:
        fast = neural_budget_for_mode(ReasoningMode.FAST)
        deep = neural_budget_for_mode(ReasoningMode.DEEP)
        maximum = neural_budget_for_mode(ReasoningMode.MAXIMUM)
        self.assertEqual(fast.native_effort, NativeEffort.LOW)
        self.assertEqual(fast.candidate_count, 1)
        self.assertEqual(deep.native_effort, NativeEffort.HIGH)
        self.assertGreaterEqual(deep.candidate_count, 2)
        self.assertEqual(maximum.native_effort, NativeEffort.MAXIMUM)
        self.assertGreaterEqual(maximum.candidate_count, 4)
        self.assertTrue(fast.public_dict()["truth"]["neural_budget_is_not_provider_payload"])

    def test_policy_neural_override(self) -> None:
        policy = ReasoningPolicy(
            mode_neural_budgets={
                "DEEP": {"candidate_count": 4, "native_effort": "HIGH"},
            }
        )
        budget = neural_budget_for_mode(
            ReasoningMode.DEEP,
            policy_budgets=policy.mode_neural_budgets,
        )
        self.assertEqual(budget.candidate_count, 4)


class CapabilityProfileTests(unittest.TestCase):
    def test_never_guess_from_model_name(self) -> None:
        profile = resolve_reasoning_capability_profile(
            model_id="gpt-5-thinking-max",
            provider_family="generic",
        )
        self.assertFalse(profile.supports_native_reasoning)
        self.assertEqual(profile.resolution_source, "unresolved")
        self.assertTrue(
            profile.public_dict()["truth"]["never_guess_capability_from_model_name_alone"]
        )

    def test_settings_override_requires_apply(self) -> None:
        ignored = resolve_reasoning_capability_profile(
            settings_override={
                "supports_native_reasoning": True,
                "supported_efforts": ["HIGH"],
            }
        )
        self.assertFalse(ignored.supports_native_reasoning)
        applied = resolve_reasoning_capability_profile(
            settings_override={
                "apply": True,
                "supports_native_reasoning": True,
                "supported_efforts": ["LOW", "HIGH"],
                "provider_family": "openai_compatible",
            }
        )
        self.assertTrue(applied.supports_native_reasoning)
        self.assertEqual(applied.resolution_source, "settings_override")
        self.assertIn("HIGH", applied.supported_efforts)

    def test_metadata_structured_block(self) -> None:
        profile = resolve_reasoning_capability_profile(
            model_metadata={
                "reasoning_capabilities": {
                    "supports_native_reasoning": True,
                    "supported_efforts": ["MEDIUM", "HIGH"],
                    "supports_reasoning_token_budget": True,
                    "provider_family": "openai_compatible",
                }
            }
        )
        self.assertTrue(profile.supports_native_reasoning)
        self.assertTrue(profile.supports_reasoning_token_budget)
        self.assertEqual(profile.resolution_source, "metadata")

    def test_apply_capability_clears_unsupported_tokens(self) -> None:
        budget = NeuralComputeBudget(
            native_effort=NativeEffort.HIGH,
            max_reasoning_tokens=8000,
            candidate_count=3,
        )
        generic = ReasoningCapabilityProfile(supports_native_reasoning=False)
        adjusted = apply_capability_to_budget(budget, generic)
        # Semantic effort retained for TTC/observability; tokens not sendable.
        self.assertEqual(adjusted.native_effort, NativeEffort.HIGH)
        self.assertIsNone(adjusted.max_reasoning_tokens)
        self.assertEqual(adjusted.candidate_count, 3)
        self.assertEqual(generic.map_effort(NativeEffort.HIGH), NativeEffort.UNSUPPORTED)


class MetaTwoAxisTests(unittest.TestCase):
    def test_decision_includes_neural_axis(self) -> None:
        task = TaskModelBuilder().build("hi")
        decision = MetaController().decide(task)
        self.assertIsNotNone(decision.neural_budgets)
        self.assertIsNotNone(decision.capability_profile)
        payload = decision.public_dict()
        self.assertTrue(payload["truth"]["two_axis_compute"])
        self.assertEqual(payload["requested_mode"], payload["effective_mode"])
        self.assertIn("neural_budgets", payload)
        self.assertEqual(decision.mode, ReasoningMode.FAST)
        self.assertEqual(decision.neural_budgets.native_effort, NativeEffort.LOW)

    def test_deep_has_higher_neural_than_fast(self) -> None:
        task = TaskModelBuilder().build(
            "Debug and fix the MCP reconnect race that drops pending calls; add regression tests"
        )
        decision = MetaController().decide(task, uncertainty=0.8, user_requested_depth="DEEP")
        self.assertEqual(decision.requested_mode, ReasoningMode.DEEP)
        self.assertEqual(decision.effective_mode, ReasoningMode.DEEP)
        self.assertGreaterEqual(decision.neural_budgets.candidate_count, 2)
        self.assertEqual(decision.neural_budgets.native_effort, NativeEffort.HIGH)

    def test_resource_pressure_clamps_maximum(self) -> None:
        task = TaskModelBuilder().build(
            "Research the latest evidence on local agent runtimes and compare sources carefully"
        )
        decision = MetaController().decide(
            task,
            user_requested_depth="MAXIMUM",
            resource_pressure=0.95,
        )
        self.assertEqual(decision.requested_mode, ReasoningMode.MAXIMUM)
        self.assertEqual(decision.effective_mode, ReasoningMode.DEEP)
        self.assertIn(
            decision.clamp_reason,
            {ClampReason.GPU_RESOURCE_PRESSURE.value, ClampReason.RESOURCE_PRESSURE.value},
        )
        self.assertNotEqual(decision.requested_mode, decision.effective_mode)

    def test_policy_from_settings_includes_neural(self) -> None:
        settings = Settings.from_env()
        policy = ReasoningPolicy.from_settings(settings)
        self.assertIn("DEEP", policy.mode_neural_budgets)
        self.assertEqual(policy.mode_neural_budgets["DEEP"]["native_effort"], "HIGH")
        self.assertGreaterEqual(policy.resource_clamp_pressure_threshold, 0.5)


class SettingsCatalogTwoAxisTests(unittest.TestCase):
    def test_catalog_has_neural_keys(self) -> None:
        catalog = build_catalog()
        keys = {d.key for d in catalog}
        self.assertIn("reasoning.deep_neural_candidate_count", keys)
        self.assertIn("reasoning.resource_clamp_pressure_threshold", keys)
        self.assertIn("reasoning.minimum_information_gain", keys)
        self.assertIn("reasoning.reasoning_capability_override_apply", keys)


if __name__ == "__main__":
    unittest.main()
