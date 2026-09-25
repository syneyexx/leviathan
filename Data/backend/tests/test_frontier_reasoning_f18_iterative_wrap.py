"""F18 — Iterative tool↔native interleaving (R16) + wrap canonical/gates (R01/R30)."""

from __future__ import annotations

import unittest
from pathlib import Path

from Data.modules.cognition.action_selector import ActionSelector
from Data.modules.cognition.meta_controller import MetaController, MetaDecision
from Data.modules.cognition.neural_compute import (
    NativeEffort,
    NeuralComputeBudget,
    ReasoningCapabilityProfile,
)
from Data.modules.cognition.task_model import TaskModelBuilder
from Data.modules.cognition.tool_interleaving import (
    interleave_boost,
    interleaving_public_status,
    profile_supports_tool_interleaving,
    should_interleave_tool_after_native,
)
from Data.modules.cognition.types import (
    CognitiveAction,
    CognitiveActionKind,
    CognitiveBudgets,
    CognitiveObservation,
    CognitiveObservationKind,
    ReasoningMode,
    ReasoningStrategy,
)
from Data.modules.cognition.working_memory import WorkingMemory


ROOT = Path(__file__).resolve().parents[3]


def _profile(*, interleave: bool, native: bool = True) -> ReasoningCapabilityProfile:
    return ReasoningCapabilityProfile(
        supports_native_reasoning=native,
        supported_efforts=("LOW", "MEDIUM", "HIGH", "MAXIMUM") if native else (),
        supports_tool_interleaving=interleave,
        provider_family="openai_compatible" if native else "generic",
        resolution_source="settings_override",
    )


def _decision(*, interleave: bool) -> MetaDecision:
    profile = _profile(interleave=interleave)
    neural = NeuralComputeBudget(
        native_effort=NativeEffort.HIGH,
        max_reasoning_tokens=4096,
        candidate_count=2,
    )
    return MetaDecision(
        mode=ReasoningMode.DEEP,
        strategy=ReasoningStrategy.TOOL_DRIVEN,
        budgets=CognitiveBudgets(max_tool_calls=4, max_model_calls=6, max_iterations=8),
        value_scores={"invoke_capability": 0.5, "model_call": 0.4},
        notes=("test",),
        requested_mode=ReasoningMode.DEEP,
        effective_mode=ReasoningMode.DEEP,
        neural_budgets=neural,
        capability_profile=profile,
    )


class ToolInterleavingPolicyTests(unittest.TestCase):
    def test_requires_explicit_profile_support(self) -> None:
        self.assertFalse(profile_supports_tool_interleaving(None))
        self.assertFalse(profile_supports_tool_interleaving(_profile(interleave=False)))
        self.assertTrue(profile_supports_tool_interleaving(_profile(interleave=True)))
        # Never invent from bare model-name-like mappings.
        self.assertFalse(
            profile_supports_tool_interleaving({"model": "gpt-5-thinking-max"})
        )

    def test_should_interleave_after_native_model_call(self) -> None:
        actions = [
            CognitiveAction(
                kind=CognitiveActionKind.MODEL_CALL,
                action_id="a1",
                rationale="native reason",
            )
        ]
        self.assertTrue(
            should_interleave_tool_after_native(
                capability_profile=_profile(interleave=True),
                inference_path="native",
                native_effort="HIGH",
                actions=actions,
                observations=[],
                tool_budget_remaining=2,
                strategy="TOOL_DRIVEN",
            )
        )
        self.assertFalse(
            should_interleave_tool_after_native(
                capability_profile=_profile(interleave=False),
                inference_path="native",
                native_effort="HIGH",
                actions=actions,
                observations=[],
                tool_budget_remaining=2,
                strategy="TOOL_DRIVEN",
            )
        )
        self.assertEqual(
            interleave_boost(
                capability_profile=_profile(interleave=True),
                inference_path="native",
                native_effort="HIGH",
                actions=actions,
                observations=[],
                tool_budget_remaining=2,
                strategy="TOOL_DRIVEN",
            ),
            0.35,
        )

    def test_public_status_truth(self) -> None:
        status = interleaving_public_status(
            capability_profile=_profile(interleave=True),
            active=True,
            reason="pending_tool_after_native",
        )
        self.assertTrue(status["supports_tool_interleaving"])
        self.assertTrue(status["interleave_active"])
        self.assertTrue(status["truth"]["iterative_tools_exist_in_loop"])
        self.assertTrue(status["truth"]["never_invent_tool_interleaving_from_model_name"])


class ActionSelectorInterleaveTests(unittest.TestCase):
    def test_forces_capability_invoke_after_native_when_supported(self) -> None:
        task = TaskModelBuilder().build("use tools to inspect the repo layout")
        wm = WorkingMemory()
        wm.upsert(
            "capability",
            "fs.list_dir workspace root listing",
            priority=1.0,
            item_id="c1",
        )
        decision = _decision(interleave=True)
        prior = [
            CognitiveAction(
                kind=CognitiveActionKind.MODEL_CALL,
                action_id="m1",
                rationale="native",
            )
        ]
        from Data.modules.cognition.belief_state import BeliefState

        action = ActionSelector().select(
            task=task,
            decision=decision,
            plan=None,
            beliefs=BeliefState(),
            working_memory=wm,
            observations=[],
            budgets_remaining={
                "tool_calls": 3,
                "model_calls": 4,
                "iterations": 5,
                "retrieval_rounds": 1,
                "agent_delegations": 0,
                "replans": 1,
            },
            actions=prior,
            inference_path="native",
        )
        self.assertEqual(action.kind, CognitiveActionKind.INVOKE_CAPABILITY)
        self.assertTrue(action.arguments.get("tool_interleave"))
        self.assertIn("interleave", (action.rationale or "").lower())

    def test_no_force_without_profile_support(self) -> None:
        task = TaskModelBuilder().build("hello")
        wm = WorkingMemory()
        wm.upsert("capability", "fs.list_dir workspace", priority=1.0, item_id="c1")
        decision = _decision(interleave=False)
        prior = [
            CognitiveAction(
                kind=CognitiveActionKind.MODEL_CALL,
                action_id="m1",
                rationale="native",
            )
        ]
        from Data.modules.cognition.belief_state import BeliefState

        # Without interleave support, selector must NOT mark tool_interleave.
        action = ActionSelector().select(
            task=task,
            decision=decision,
            plan=None,
            beliefs=BeliefState(),
            working_memory=wm,
            observations=[
                CognitiveObservation(
                    kind=CognitiveObservationKind.MODEL_RESULT,
                    observation_id="o1",
                    summary="draft",
                    success=True,
                )
            ],
            budgets_remaining={
                "tool_calls": 3,
                "model_calls": 4,
                "iterations": 5,
                "retrieval_rounds": 1,
                "agent_delegations": 0,
                "replans": 1,
            },
            actions=prior,
            inference_path="native",
        )
        self.assertFalse(bool((action.arguments or {}).get("tool_interleave")))


class CanonicalRuntimeAndWrapTests(unittest.TestCase):
    """R01 + R30 structural honesty for F18 wrap."""

    def test_cognitive_runtime_sole_orch_symbols(self) -> None:
        runtime = (ROOT / "Data" / "modules" / "cognition" / "runtime.py").read_text(
            encoding="utf-8"
        )
        main = (ROOT / "Data" / "backend" / "main.py").read_text(encoding="utf-8")
        self.assertIn("class CognitiveRuntime", runtime)
        self.assertIn("cognition_runtime.submit", main)
        # Build forbidden names without embedding the banned "class X" literals.
        for stem in ("CognitionV2", "FrontierRuntime", "ReasoningRuntime2", "BrainV2"):
            banned = f"class {stem}"
            self.assertNotIn(banned, runtime)
            self.assertNotIn(banned, main)

    def test_frontend_build_scripts_present(self) -> None:
        pkg = (ROOT / "Data" / "frontend" / "package.json").read_text(encoding="utf-8")
        for script in ('"typecheck"', '"lint"', '"test"', '"build"'):
            self.assertIn(script, pkg)

    def test_tool_interleaving_module_wired(self) -> None:
        selector = (
            ROOT / "Data" / "modules" / "cognition" / "action_selector.py"
        ).read_text(encoding="utf-8")
        runtime = (ROOT / "Data" / "modules" / "cognition" / "runtime.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("should_interleave_tool_after_native", selector)
        self.assertIn("tool_interleaving", runtime)
        self.assertIn("inference_path=", runtime)


if __name__ == "__main__":
    unittest.main()
