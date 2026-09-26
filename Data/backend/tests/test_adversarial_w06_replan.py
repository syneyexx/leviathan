"""W06 — observation-linked replan (no blind adaptive restart)."""

from __future__ import annotations

import unittest
import uuid

from Data.modules.cognition.meta_controller import MetaController
from Data.modules.cognition.planner import CognitivePlanner
from Data.modules.cognition.task_model import TaskModelBuilder
from Data.modules.cognition.types import (
    CognitiveObservation,
    CognitiveObservationKind,
    EpistemicType,
)


class ObservationLinkedReplanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = CognitivePlanner()
        self.meta = MetaController()
        self.task = TaskModelBuilder().build("Investigate API outage with evidence")
        self.decision = self.meta.decide(self.task)

    def test_replan_links_observation_ids(self) -> None:
        previous = self.planner.plan(self.task, self.decision)
        obs = CognitiveObservation(
            kind=CognitiveObservationKind.TOOL_RESULT,
            observation_id=str(uuid.uuid4()),
            summary="health check returned 503",
            source_type=EpistemicType.TOOL_OBSERVATION,
            success=False,
        )
        plan = self.planner.replan(
            self.task,
            self.decision,
            previous=previous,
            reason="observation:tool_failed",
            observations=[obs],
        )
        self.assertTrue(plan.observation_linked)
        self.assertTrue(any(obs.observation_id in r for r in plan.observation_refs))
        self.assertTrue(any(a.startswith("observation_trace:") for a in plan.assumptions))
        self.assertGreater(plan.revision, previous.revision)
        pub = plan.public_dict()
        self.assertTrue(pub["observation_linked"])
        self.assertFalse(pub["truth"]["blind_restart_is_not_adaptive"])

    def test_adaptive_replan_without_observations_fails_closed(self) -> None:
        previous = self.planner.plan(self.task, self.decision)
        with self.assertRaises(ValueError) as ctx:
            self.planner.replan(
                self.task,
                self.decision,
                previous=previous,
                reason="observation:contradiction",
                observations=[],
                require_observation_trace=True,
            )
        self.assertIn("COGNITION_REPLAN_MISSING_OBSERVATION_TRACE", str(ctx.exception))

    def test_soft_path_marks_missing_trace_honestly(self) -> None:
        previous = self.planner.plan(self.task, self.decision)
        plan = self.planner.replan(
            self.task,
            self.decision,
            previous=previous,
            reason="observation:tool_failed",
            observations=[],
        )
        self.assertFalse(plan.observation_linked)
        self.assertIn("observation_trace:MISSING", plan.assumptions)
        self.assertTrue(plan.public_dict()["truth"]["blind_restart_is_not_adaptive"])


if __name__ == "__main__":
    unittest.main()
