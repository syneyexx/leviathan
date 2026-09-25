"""F17 — Frontend reasoning controls + two-axis observability (R25/R26)."""

from __future__ import annotations

import unittest
from pathlib import Path

from Data.modules.cognition.meta_controller import MetaController
from Data.modules.cognition.task_model import TaskModelBuilder
from Data.modules.cognition.types import ReasoningMode
from Data.modules.observability import ObservabilityHub
from Data.modules.observability.cognition_compute import (
    attach_cognition_compute_provider,
    cognition_compute_snapshot,
)


ROOT = Path(__file__).resolve().parents[3]


class ReasoningDepthControlTests(unittest.TestCase):
    """R25 — AUTO/FAST/STANDARD/DEEP/MAXIMUM depth controls honor user request."""

    def test_auto_alias_uses_heuristics(self) -> None:
        task = TaskModelBuilder().build("hello there")
        ctrl = MetaController()
        auto = ctrl.decide(task, uncertainty=0.1, user_requested_depth="AUTO")
        adaptive = ctrl.decide(task, uncertainty=0.1, user_requested_depth="ADAPTIVE")
        self.assertEqual(auto.mode, adaptive.mode)
        self.assertIn(auto.mode, {ReasoningMode.FAST, ReasoningMode.STANDARD})

    def test_forced_depths(self) -> None:
        task = TaskModelBuilder().build("Investigate multi-hop research contradictions carefully")
        ctrl = MetaController()
        for depth, expected in (
            ("FAST", ReasoningMode.FAST),
            ("STANDARD", ReasoningMode.STANDARD),
            ("DEEP", ReasoningMode.DEEP),
            ("MAXIMUM", ReasoningMode.MAXIMUM),
        ):
            decision = ctrl.decide(task, uncertainty=0.7, user_requested_depth=depth)
            self.assertEqual(decision.requested_mode, expected, msg=depth)
            self.assertEqual(decision.mode, expected, msg=depth)
            self.assertIsNotNone(decision.neural_budgets)

    def test_frontend_depth_selector_present(self) -> None:
        chat = (ROOT / "Data" / "frontend" / "src" / "pages" / "ChatPage.tsx").read_text(
            encoding="utf-8"
        )
        cognition = (
            ROOT / "Data" / "frontend" / "src" / "pages" / "CognitionPage.tsx"
        ).read_text(encoding="utf-8")
        types = (ROOT / "Data" / "frontend" / "src" / "types" / "api.ts").read_text(
            encoding="utf-8"
        )
        client = (ROOT / "Data" / "frontend" / "src" / "api" / "client.ts").read_text(
            encoding="utf-8"
        )
        self.assertIn("REASONING_DEPTH_OPTIONS", types)
        self.assertIn("reasoningMode", types)
        self.assertIn("AUTO", types)
        self.assertIn("MAXIMUM", types)
        self.assertIn("REASONING_DEPTH_OPTIONS", chat)
        self.assertIn("reasoningMode", chat)
        self.assertIn("Reasoning depth", cognition)
        self.assertIn("user_requested_depth", cognition)
        self.assertIn("reasoning_mode", client)
        self.assertIn("cognitionCompute", client)


class CognitionComputeObservabilityTests(unittest.TestCase):
    """R26 — Two-axis cognition compute observability, no private CoT."""

    def test_snapshot_separates_axes(self) -> None:
        snap = cognition_compute_snapshot(
            run_status={
                "run_id": "run-1",
                "status": "COMPLETED_VERIFIED",
                "mode": "DEEP",
                "requested_mode": "MAXIMUM",
                "effective_mode": "DEEP",
                "clamp_reason": "GPU_RESOURCE_PRESSURE",
                "strategy": "RESEARCH_SYNTHESIS",
                "budgets": {"max_model_calls": 8},
                "usage": {"iterations": 3},
                "neural_budgets": {
                    "native_effort": "HIGH",
                    "max_reasoning_tokens": 4096,
                    "candidate_count": 4,
                    "max_parallel_candidates": 2,
                    "diversity_temperature": 0.8,
                },
                "expected_gain": 0.42,
                "neural_adaptation": "escalate",
                "reasoning_state": {
                    "native_effort_effective": "HIGH",
                    "reasoning_tokens_status": "budgeted",
                    "inference_path": "native",
                    "model_calls_consumed": 2,
                    "private_reasoning": "SECRET_COT_MUST_NOT_LEAK",
                },
            }
        )
        self.assertEqual(snap["orchestration"]["requested_mode"], "MAXIMUM")
        self.assertEqual(snap["orchestration"]["effective_mode"], "DEEP")
        self.assertEqual(snap["neural"]["native_effort"], "HIGH")
        self.assertEqual(snap["neural"]["max_reasoning_tokens"], 4096)
        self.assertEqual(snap["neural"]["candidate_count"], 4)
        self.assertTrue(snap["truth"]["two_axis_compute_observability"])
        self.assertTrue(snap["truth"]["no_private_cot"])
        self.assertTrue(snap["truth"]["orchestration_axis_separate_from_neural_axis"])
        blob = str(snap)
        self.assertNotIn("SECRET_COT_MUST_NOT_LEAK", blob)
        self.assertNotIn("private_reasoning", blob)

    def test_unmeasured_fields_remain_null(self) -> None:
        snap = cognition_compute_snapshot(run_status={"run_id": "empty"})
        self.assertIsNone(snap["orchestration"]["mode"])
        self.assertIsNone(snap["neural"]["native_effort"])
        self.assertIsNone(snap["neural"]["max_reasoning_tokens"])
        self.assertTrue(snap["truth"]["unmeasured_fields_remain_null"])

    def test_hub_provider_attachment(self) -> None:
        hub = ObservabilityHub(capacity=16)
        attach_cognition_compute_provider(
            hub,
            lambda: cognition_compute_snapshot(
                run_status={
                    "mode": "STANDARD",
                    "neural_budgets": {"native_effort": "MEDIUM", "candidate_count": 2},
                }
            ),
        )
        snap = hub.snapshot()
        self.assertIn("cognition_compute", snap)
        compute = snap["cognition_compute"]
        self.assertEqual(compute["orchestration"]["mode"], "STANDARD")
        self.assertEqual(compute["neural"]["native_effort"], "MEDIUM")

    def test_route_and_ui_surfaces_present(self) -> None:
        obs_route = (
            ROOT / "Data" / "backend" / "routes" / "observability.py"
        ).read_text(encoding="utf-8")
        status = (ROOT / "Data" / "frontend" / "src" / "pages" / "StatusPage.tsx").read_text(
            encoding="utf-8"
        )
        perf = (
            ROOT
            / "Data"
            / "frontend"
            / "src"
            / "pages"
            / "plugin-runtime"
            / "PerformancePage.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn("/api/observability/cognition-compute", obs_route)
        self.assertIn("cognitionCompute", status)
        self.assertIn("two-axis", status.lower())
        self.assertIn("cognitionCompute", perf)
        self.assertIn("Cognition Compute", perf)


if __name__ == "__main__":
    unittest.main()
