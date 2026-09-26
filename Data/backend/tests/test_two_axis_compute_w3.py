"""W3 — Two-axis inference compute + real resource pressure."""

from __future__ import annotations

import unittest

from Data.modules.cognition.compute_axes import (
    assert_modes_measurably_different,
    neural_for_mode,
    neural_presets,
)
from Data.modules.cognition.meta_controller import MetaController
from Data.modules.cognition.resource_pressure import (
    build_resource_pressure_fn,
    measure_resource_pressure,
)
from Data.modules.cognition.task_model import TaskModelBuilder
from Data.modules.cognition.types import ReasoningMode


class TwoAxisComputeTests(unittest.TestCase):
    def test_modes_differ_on_both_axes(self) -> None:
        ctrl = MetaController()
        orch = ctrl._hardcoded_presets()
        report = assert_modes_measurably_different(orch)
        self.assertTrue(report["ok"], report["violations"])

        fast = ctrl.decide(
            TaskModelBuilder().build("hi"),
            user_requested_depth="FAST",
        )
        deep = ctrl.decide(
            TaskModelBuilder().build(
                "Research and compare local agent runtimes with citations and contradictions"
            ),
            user_requested_depth="DEEP",
            uncertainty=0.8,
        )
        self.assertEqual(fast.effective_mode, ReasoningMode.FAST)
        self.assertEqual(deep.requested_mode, ReasoningMode.DEEP)
        self.assertEqual(deep.effective_mode, ReasoningMode.DEEP)
        self.assertLess(fast.budgets.max_model_calls, deep.budgets.max_model_calls)
        self.assertLess(fast.neural.max_output_tokens, deep.neural.max_output_tokens)
        self.assertLess(fast.neural.candidate_count, deep.neural.candidate_count)
        self.assertLess(fast.budgets.max_critic_passes, deep.budgets.max_critic_passes)

        pub = deep.public_dict()
        self.assertTrue(pub["truth"]["two_axis_compute"])
        self.assertEqual(pub["requested_mode"], "DEEP")
        self.assertEqual(pub["effective_mode"], "DEEP")
        self.assertIn("orchestration", pub)
        self.assertIn("neural", pub)

    def test_maximum_exceeds_deep_neural(self) -> None:
        n = neural_presets()
        self.assertGreater(n[ReasoningMode.MAXIMUM].candidate_count, n[ReasoningMode.DEEP].candidate_count)
        self.assertGreater(
            n[ReasoningMode.MAXIMUM].max_output_tokens,
            n[ReasoningMode.DEEP].max_output_tokens,
        )

    def test_pressure_shrinks_neural_axis(self) -> None:
        task = TaskModelBuilder().build(
            "Debug and fix reconnect race with tests across the agent fleet"
        )
        low = MetaController().decide(task, user_requested_depth="DEEP", resource_pressure=0.0)
        high = MetaController().decide(task, user_requested_depth="DEEP", resource_pressure=0.9)
        self.assertGreater(low.neural.max_output_tokens, high.neural.max_output_tokens)
        self.assertGreaterEqual(low.neural.candidate_count, high.neural.candidate_count)
        self.assertLessEqual(high.budgets.max_parallel_workers, low.budgets.max_parallel_workers)


class ResourcePressureTests(unittest.TestCase):
    def test_not_a_fake_constant_when_signals_present(self) -> None:
        a = measure_resource_pressure(
            telemetry_snapshot={"cpuPct": 10, "ramPct": 20, "vramPct": 5}
        )
        b = measure_resource_pressure(
            telemetry_snapshot={"cpuPct": 90, "ramPct": 95, "vramPct": 88},
            queue_depth=20,
            queue_capacity=32,
        )
        self.assertLess(a.pressure, b.pressure)
        self.assertTrue(a.public_dict()["truth"]["not_a_fake_constant"])
        self.assertEqual(a.provenance["cpu"], "MEASURED")
        self.assertEqual(b.components["queue"], round(20 / 32, 4))

    def test_unavailable_signals_omit_not_invent_load(self) -> None:
        sample = measure_resource_pressure()
        self.assertEqual(sample.pressure, 0.0)
        self.assertEqual(sample.components, {})
        self.assertIn("UNAVAILABLE", sample.provenance.values())

    def test_pressure_fn_callback(self) -> None:
        calls = {"n": 0}

        def tel() -> dict:
            calls["n"] += 1
            return {"cpuPct": 50, "ramPct": 50}

        fn = build_resource_pressure_fn(telemetry_provider=tel)
        p1 = fn()
        p2 = fn()
        self.assertGreater(p1, 0.0)
        self.assertEqual(p1, p2)
        self.assertEqual(calls["n"], 2)

    def test_neural_for_adaptive_maps_to_standard_table(self) -> None:
        adaptive = neural_for_mode(ReasoningMode.ADAPTIVE)
        standard = neural_for_mode(ReasoningMode.STANDARD)
        self.assertEqual(adaptive.max_output_tokens, standard.max_output_tokens)


if __name__ == "__main__":
    unittest.main()
