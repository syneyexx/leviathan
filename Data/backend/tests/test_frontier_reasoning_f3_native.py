"""F3 — Native reasoning adapters + InferenceComputeController."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock

from Data.modules.cognition.inference_compute import InferenceComputeController
from Data.modules.cognition.neural_compute import (
    NativeEffort,
    NeuralComputeBudget,
    ReasoningCapabilityProfile,
)
from Data.modules.cognition.types import ReasoningMode
from Data.modules.model_runtime.openai_compatible import OpenAICompatibleLLM
from Data.modules.models.native_reasoning import (
    build_native_reasoning_hints,
    parse_reasoning_usage,
    strip_private_reasoning_fields,
)
from Data.modules.models.providers.openai_compatible import OpenAICompatibleAdapter


class NativeHintsTests(unittest.TestCase):
    def test_generic_sends_no_unknown_knobs(self) -> None:
        hints = build_native_reasoning_hints(
            provider_family="generic",
            supports_native_reasoning=False,
            native_effort="HIGH",
            max_reasoning_tokens=8000,
        )
        self.assertEqual(hints.path, "ttc")
        self.assertEqual(hints.provider_hints, {})
        for key in hints.forbidden_keys:
            self.assertNotIn(key, hints.provider_hints)

    def test_openai_compatible_native_when_supported(self) -> None:
        hints = build_native_reasoning_hints(
            provider_family="openai_compatible",
            supports_native_reasoning=True,
            supported_efforts=("LOW", "MEDIUM", "HIGH"),
            supports_reasoning_token_budget=True,
            native_effort="HIGH",
            max_reasoning_tokens=7421,
        )
        self.assertEqual(hints.path, "native")
        self.assertEqual(hints.provider_hints.get("reasoning_effort"), "high")
        self.assertEqual(hints.provider_hints.get("max_reasoning_tokens"), 7421)
        self.assertNotIn("thinking", hints.provider_hints)
        self.assertNotIn("think", hints.provider_hints)

    def test_fast_maps_to_low_effort(self) -> None:
        hints = build_native_reasoning_hints(
            provider_family="openai_compatible",
            supports_native_reasoning=True,
            supported_efforts=("low", "medium", "high"),
            native_effort="LOW",
        )
        self.assertEqual(hints.effective_effort, "low")

    def test_maximum_maps_to_high_when_max_unsupported_string(self) -> None:
        hints = build_native_reasoning_hints(
            provider_family="openai_compatible",
            supports_native_reasoning=True,
            supported_efforts=("low", "medium", "high"),
            native_effort="MAXIMUM",
        )
        self.assertEqual(hints.effective_effort, "high")

    def test_completion_payload_attaches_hints_only_when_provided(self) -> None:
        from Data.modules.context import ContextBuilder

        settings = MagicMock()
        settings.llm_timeout_seconds = 30.0
        settings.llm_model = "m"
        settings.llm_api_key = ""
        settings.llm_base_url = "http://127.0.0.1:8080/v1"
        llm = OpenAICompatibleLLM(
            settings,
            context_builder=ContextBuilder(token_budget=2000),
        )
        bare = llm._completion_payload(
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.2,
            max_tokens=16,
            top_p=None,
            stream=False,
        )
        self.assertNotIn("reasoning_effort", bare)
        with_hints = llm._completion_payload(
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.2,
            max_tokens=16,
            top_p=None,
            stream=False,
            provider_hints={"reasoning_effort": "high"},
        )
        self.assertEqual(with_hints["reasoning_effort"], "high")


class InferenceControllerTests(unittest.TestCase):
    def test_ttc_path_for_unsupported(self) -> None:
        ctrl = InferenceComputeController()
        plan = ctrl.prepare(
            mode=ReasoningMode.DEEP,
            neural_budget=NeuralComputeBudget(
                native_effort=NativeEffort.HIGH,
                candidate_count=3,
                max_reasoning_tokens=4096,
            ),
            capability_profile=ReasoningCapabilityProfile(
                supports_native_reasoning=False,
                provider_family="generic",
            ),
            provider_family="generic",
        )
        self.assertEqual(plan.path, "ttc")
        self.assertEqual(plan.provider_hints, {})
        self.assertEqual(plan.ttc_candidate_budget, 3)
        self.assertEqual(plan.primary_candidate_count, 1)

    def test_native_path_when_capability_affirmed(self) -> None:
        ctrl = InferenceComputeController()
        plan = ctrl.prepare(
            mode=ReasoningMode.DEEP,
            neural_budget=NeuralComputeBudget(native_effort=NativeEffort.HIGH),
            capability_profile=ReasoningCapabilityProfile(
                supports_native_reasoning=True,
                supported_efforts=("LOW", "MEDIUM", "HIGH"),
                provider_family="openai_compatible",
                resolution_source="settings_override",
            ),
            provider_family="openai_compatible",
        )
        self.assertEqual(plan.path, "native")
        self.assertIn("reasoning_effort", plan.provider_hints)

    def test_normalize_unmeasured_reasoning_tokens(self) -> None:
        ctrl = InferenceComputeController()
        plan = ctrl.prepare(
            capability_profile=ReasoningCapabilityProfile(supports_native_reasoning=False),
        )
        result = ctrl.normalize_result(
            plan=plan,
            raw_result={"text": "hello", "usage": {"output_tokens": 3}, "usage_source": "provider"},
        )
        self.assertEqual(result.reasoning_tokens_status, "UNMEASURED")
        self.assertIsNone(result.reasoning_tokens)
        self.assertEqual(result.text, "hello")

    def test_normalize_provider_reported_reasoning_tokens(self) -> None:
        ctrl = InferenceComputeController()
        plan = ctrl.prepare(
            capability_profile=ReasoningCapabilityProfile(
                supports_native_reasoning=True,
                supported_efforts=("HIGH",),
                provider_family="openai_compatible",
            ),
            provider_family="openai_compatible",
            neural_budget=NeuralComputeBudget(native_effort=NativeEffort.HIGH),
        )
        result = ctrl.normalize_result(
            plan=plan,
            raw_result={
                "text": "answer",
                "usage": {
                    "output_tokens": 10,
                    "completion_tokens_details": {"reasoning_tokens": 7421},
                },
                "usage_source": "provider",
            },
        )
        self.assertEqual(result.reasoning_tokens, 7421)
        self.assertEqual(result.reasoning_tokens_status, "provider")

    def test_strip_private_cot_from_message(self) -> None:
        cleaned = strip_private_reasoning_fields(
            {
                "role": "assistant",
                "content": "public answer",
                "reasoning": "SECRET CHAIN OF THOUGHT",
                "thinking": "more secret",
            }
        )
        self.assertEqual(cleaned.get("content"), "public answer")
        self.assertNotIn("reasoning", cleaned)
        self.assertNotIn("thinking", cleaned)


class AdapterHonestyTests(unittest.TestCase):
    def test_openai_adapter_does_not_claim_native_by_default(self) -> None:
        adapter = OpenAICompatibleAdapter(
            provider_id="local",
            endpoint="http://127.0.0.1:8080/v1",
        )
        profile = adapter.reasoning_capability_profile()
        self.assertFalse(profile["supports_native_reasoning"])
        self.assertEqual(profile["provider_family"], "openai_compatible")

    def test_ollama_adapter_does_not_claim_native_by_default(self) -> None:
        from Data.modules.models.providers.ollama import OllamaAdapter

        adapter = OllamaAdapter(
            provider_id="ollama",
            endpoint="http://127.0.0.1:11434",
        )
        profile = adapter.reasoning_capability_profile()
        self.assertFalse(profile["supports_native_reasoning"])
        self.assertEqual(profile["provider_family"], "ollama")

    def test_parse_reasoning_usage_never_invents(self) -> None:
        tokens, source = parse_reasoning_usage({"output_tokens": 5})
        self.assertIsNone(tokens)
        self.assertEqual(source, "unavailable")

    def test_controller_public_plan_has_no_cot_keys(self) -> None:
        ctrl = InferenceComputeController()
        plan = ctrl.prepare(
            capability_profile=ReasoningCapabilityProfile(
                supports_native_reasoning=True,
                supported_efforts=("HIGH",),
                provider_family="openai_compatible",
            ),
            provider_family="openai_compatible",
            neural_budget=NeuralComputeBudget(native_effort=NativeEffort.HIGH),
        )
        public = plan.public_dict()
        blob = str(public).lower()
        self.assertNotIn("chain of thought", blob)
        self.assertTrue(public["truth"]["private_cot_not_in_plan"])


if __name__ == "__main__":
    unittest.main()
