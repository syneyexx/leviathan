from __future__ import annotations

import unittest

from reasoning.plan_scheduler import apply_blocked_statuses, evaluate_dependency_states, ready_steps


class PlanSchedulerBlockedDependencyPropagationTests(unittest.TestCase):
    def test_blocked_dependency_blocks_downstream_step(self) -> None:
        steps = [
            {
                "step_id": "upstream",
                "instruction": "cannot execute",
                "agent_id": "executor",
                "status": "blocked",
                "depends_on": [],
            },
            {
                "step_id": "downstream",
                "instruction": "must depend on upstream",
                "agent_id": "executor",
                "status": "pending",
                "depends_on": ["upstream"],
            },
        ]

        evaluation = evaluate_dependency_states(steps)
        downstream = evaluation["dependency_states"]["downstream"]
        self.assertTrue(downstream["blocked"])
        self.assertIn("upstream", downstream["deps_failed"])
        self.assertNotIn("downstream", ready_steps(steps))

        materialized = {row["step_id"]: row for row in apply_blocked_statuses(steps)}
        self.assertEqual(materialized["downstream"]["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
