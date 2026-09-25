"""F4 — Test-time compute multi-candidate generate / select."""

from __future__ import annotations

import asyncio
import unittest

from Data.modules.cognition.inference_compute import InferenceComputeController
from Data.modules.cognition.neural_compute import (
    NativeEffort,
    NeuralComputeBudget,
    ReasoningCapabilityProfile,
)
from Data.modules.cognition.ttc import (
    TTCCandidate,
    TTCExecutor,
    candidate_temperatures,
    normalize_answer_key,
    select_ttc_candidate,
)
from Data.modules.cognition.types import ReasoningMode


class TTCSelectionTests(unittest.TestCase):
    def test_majority_normalized_wins(self) -> None:
        candidates = [
            TTCCandidate(0, "Paris.", 0.2),
            TTCCandidate(1, "london", 0.4),
            TTCCandidate(2, "paris", 0.6),
        ]
        selection = select_ttc_candidate(candidates)
        self.assertEqual(selection.method, "majority_normalized")
        self.assertEqual(normalize_answer_key(selection.chosen_text), "paris")
        self.assertGreaterEqual(selection.agreement_ratio or 0, 0.66)

    def test_longest_when_all_unique(self) -> None:
        candidates = [
            TTCCandidate(0, "short", 0.2),
            TTCCandidate(1, "a somewhat longer answer", 0.4),
            TTCCandidate(2, "mid", 0.6),
        ]
        selection = select_ttc_candidate(candidates)
        self.assertEqual(selection.method, "longest_valid")
        self.assertIn("longer", selection.chosen_text)

    def test_never_fabricates_when_all_empty(self) -> None:
        candidates = [
            TTCCandidate(0, "", 0.2, error="empty_response"),
            TTCCandidate(1, "  ", 0.4, error="empty_response"),
        ]
        selection = select_ttc_candidate(candidates)
        self.assertEqual(selection.method, "none_valid")
        self.assertEqual(selection.chosen_text, "")
        self.assertEqual(selection.valid_count, 0)

    def test_public_selection_has_no_cot_keys(self) -> None:
        selection = select_ttc_candidate([TTCCandidate(0, "ok", 0.2)])
        blob = str(selection.public_dict()).lower()
        self.assertNotIn("chain of thought", blob)
        self.assertTrue(selection.public_dict()["truth"]["no_private_cot_in_selection"])


class TTCExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_fan_out_consumes_n_calls_and_selects(self) -> None:
        calls: list[float] = []

        async def complete(*, temperature: float, **_kwargs):
            calls.append(temperature)
            # Two answers agree on "alpha"
            mapping = {0.2: "alpha", 0.4: "beta", 0.55: "alpha"}
            # Snap to nearest for test stability
            nearest = min(mapping.keys(), key=lambda t: abs(t - temperature))
            return {
                "text": mapping[nearest],
                "usage": {"output_tokens": 1},
                "usage_source": "provider",
                "finish_reason": "stop",
            }

        executor = TTCExecutor()
        run = await executor.run(
            candidate_count=3,
            max_parallel=2,
            diversity_temperature=0.35,
            base_temperature=0.2,
            complete=complete,
        )
        self.assertEqual(run.model_calls_consumed, 3)
        self.assertEqual(len(calls), 3)
        self.assertEqual(normalize_answer_key(run.selection.chosen_text), "alpha")
        self.assertEqual(run.selection.method, "majority_normalized")
        # No provider hints smuggled
        self.assertTrue(run.public_dict()["truth"]["no_unknown_provider_knobs"])

    async def test_controller_execute_ttc_clamps_to_remaining_calls(self) -> None:
        ctrl = InferenceComputeController()
        plan = ctrl.prepare(
            mode=ReasoningMode.DEEP,
            neural_budget=NeuralComputeBudget(
                native_effort=NativeEffort.HIGH,
                candidate_count=6,
                max_parallel_candidates=2,
                diversity_temperature=0.3,
            ),
            capability_profile=ReasoningCapabilityProfile(
                supports_native_reasoning=False,
                provider_family="generic",
            ),
            provider_family="generic",
            remaining_model_calls=2,
        )
        self.assertEqual(plan.path, "ttc")
        self.assertEqual(plan.ttc_candidate_budget, 2)
        self.assertEqual(plan.primary_candidate_count, 1)

        async def complete(*, temperature: float, **_kwargs):
            return {"text": f"ans-{temperature}", "usage_source": "unavailable"}

        normalized, run = await ctrl.execute_ttc(plan=plan, complete=complete)
        self.assertEqual(normalized.model_calls_consumed, 2)
        self.assertEqual(run.model_calls_consumed, 2)
        self.assertIsNotNone(normalized.ttc)
        self.assertEqual(normalized.path, "ttc")
        self.assertEqual(normalized.provider_hints_sent, ())

    def test_temperatures_spread(self) -> None:
        temps = candidate_temperatures(3, diversity_temperature=0.4, base_temperature=0.1)
        self.assertEqual(len(temps), 3)
        self.assertAlmostEqual(temps[0], 0.1)
        self.assertGreater(temps[2], temps[0])


class NativeVsTTCPathTests(unittest.TestCase):
    def test_native_path_stays_single_call(self) -> None:
        ctrl = InferenceComputeController()
        plan = ctrl.prepare(
            neural_budget=NeuralComputeBudget(
                native_effort=NativeEffort.HIGH,
                candidate_count=5,
            ),
            capability_profile=ReasoningCapabilityProfile(
                supports_native_reasoning=True,
                supported_efforts=("HIGH",),
                provider_family="openai_compatible",
            ),
            provider_family="openai_compatible",
        )
        self.assertEqual(plan.path, "native")
        self.assertEqual(plan.ttc_candidate_budget, 1)
        self.assertEqual(plan.primary_candidate_count, 1)
        self.assertIn("reasoning_effort", plan.provider_hints)


if __name__ == "__main__":
    unittest.main()
