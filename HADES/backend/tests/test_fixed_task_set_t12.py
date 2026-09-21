"""T12: fixed task set + measured agent quality can fail the release gate."""

from __future__ import annotations

import unittest

from evals.fixed_task_set import (
    FIXED_TASK_SET_MAX,
    FIXED_TASK_SET_MIN,
    FIXED_TASK_SET_VERSION,
    assert_fixed_task_set_bounds,
    fixed_task_set_manifest,
    list_fixed_tasks,
)
from evals.release_thresholds import RELEASE_THRESHOLDS, THRESHOLD_VERSION, evaluate_thresholds
from evals.agent_eval import aggregate_agent_metrics


class FixedTaskSetT12Tests(unittest.TestCase):
    def test_fixed_set_within_bounds(self) -> None:
        tasks = list_fixed_tasks(split="holdout")
        assert_fixed_task_set_bounds(tasks)
        manifest = fixed_task_set_manifest()
        self.assertEqual(manifest["fixed_task_set_version"], FIXED_TASK_SET_VERSION)
        self.assertTrue(manifest["within_bounds"])
        self.assertGreaterEqual(manifest["task_count"], FIXED_TASK_SET_MIN)
        self.assertLessEqual(manifest["task_count"], FIXED_TASK_SET_MAX)
        self.assertFalse(manifest["llm_as_judge"])
        self.assertIn("tool_success_ratio", manifest["metrics"])

    def test_thresholds_require_agent_task_when_measured(self) -> None:
        self.assertEqual(THRESHOLD_VERSION, "a01_release_thresholds_v2")
        self.assertTrue(RELEASE_THRESHOLDS["layers"]["agent_task"]["required"])
        self.assertTrue(RELEASE_THRESHOLDS["layers"]["model_answer"]["required"])
        self.assertTrue(
            RELEASE_THRESHOLDS["layers"]["agent_task"]["unmeasured_allowed_when_unavailable"]
        )

        unmeasured_ok = evaluate_thresholds(
            {
                "software": {"status": "measured", "pass_rate": 1.0, "false_success_rate": 0.0},
                "infra_smoke": {"status": "UNMEASURED"},
                "model_answer": {"status": "UNMEASURED"},
                "agent_task": {"status": "UNMEASURED"},
            }
        )
        self.assertTrue(unmeasured_ok["overall_software_release_ok"])

        measured_fail = evaluate_thresholds(
            {
                "software": {"status": "measured", "pass_rate": 1.0, "false_success_rate": 0.0},
                "infra_smoke": {"status": "measured"},
                "model_answer": {
                    "status": "measured",
                    "first_attempt_success": 0.1,
                    "false_success_rate": 0.0,
                },
                "agent_task": {
                    "status": "measured",
                    "first_attempt_success": 0.1,
                    "repeated_reliability": 0.0,
                    "false_success_rate": 0.0,
                    "policy_violation_rate": 0.0,
                },
            }
        )
        self.assertFalse(measured_fail["overall_software_release_ok"])
        agent_row = next(r for r in measured_fail["layers"] if r["layer"] == "agent_task")
        self.assertFalse(agent_row["passed_gate"])

    def test_aggregate_reports_t12_metric_fields(self) -> None:
        attempts = [
            {
                "task_id": "T1",
                "attempt": 1,
                "passed": True,
                "false_success": False,
                "policy_violation": False,
                "measurement_status": "measured",
                "duration_seconds": 1.5,
                "tokens": {"total": 20},
                "error_category": None,
                "route_invoked": True,
                "stages": ["tool_execution", "verification"],
                "model_invoked": True,
                "model_calls": 2,
            },
            {
                "task_id": "T2",
                "attempt": 1,
                "passed": False,
                "false_success": False,
                "policy_violation": False,
                "measurement_status": "measured",
                "duration_seconds": 0.5,
                "tokens": None,
                "error_category": "incorrect",
                "route_invoked": True,
                "stages": ["planning"],
                "model_invoked": False,
            },
        ]
        metrics = aggregate_agent_metrics(attempts)
        for key in RELEASE_THRESHOLDS["metrics_required_fields"]:
            self.assertIn(key, metrics, key)
        self.assertEqual(metrics["task_completion"], 0.5)
        self.assertEqual(metrics["model_calls"]["total"], 2)
        self.assertIsNotNone(metrics["latency_ms"]["mean"])


if __name__ == "__main__":
    unittest.main()
