"""W7 — Async cognition resume / steering / durable ReasoningState."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.cognition import (
    CognitionStore,
    CognitiveRuntime,
    CognitiveRunStatus,
    SteerKind,
    classify_steer,
)


class SteerVocabularyTests(unittest.TestCase):
    def test_program_aliases(self) -> None:
        goal = classify_steer("Forget the previous goal and do X instead")
        self.assertEqual(goal.kind, SteerKind.GOAL_REPLACEMENT)
        self.assertEqual(goal.public_dict()["program_kind"], "goal_change")
        constraint = classify_steer("You must never write outside /tmp")
        self.assertEqual(constraint.kind, SteerKind.NEW_CONSTRAINT)
        self.assertEqual(constraint.public_dict()["program_kind"], "constraint_add")
        status = classify_steer("What is the status of the run?")
        self.assertEqual(status.public_dict()["program_kind"], "status_request")
        self.assertTrue(status.public_dict()["truth"]["pinned_constraints_survive_compaction"])


class ResumeHydrationTests(unittest.TestCase):
    def test_checkpoint_roundtrip_restores_hypotheses_and_constraints(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "c.db"
        MigrationRunner(db).apply_all()
        store = CognitionStore(db)

        def model_caller(**kwargs):
            return "answer"

        runtime = CognitiveRuntime(
            enabled=True,
            shadow=False,
            iterative=False,
            belief_enabled=True,
            store=store,
            model_caller=model_caller,
        )
        submitted = runtime.submit(
            "hello",
            constraints=["must use Dutch"],
            run=True,
        )
        run_id = submitted["run_id"]
        state = runtime._runs[run_id]
        state.hypotheses.add("pending calls drop on reconnect", prior_plausibility=0.6)
        runtime.steer(run_id, "You must never expose secrets")
        runtime._persist_update(state, final=False)

        # Simulate process restart — drop in-memory runs.
        runtime2 = CognitiveRuntime(
            enabled=True,
            shadow=False,
            iterative=False,
            belief_enabled=True,
            store=store,
            model_caller=model_caller,
        )
        hydrated = runtime2.hydrate(run_id)
        live = runtime2._runs[run_id]
        self.assertTrue(live.hypotheses.items)
        constraint_texts = " ".join(
            i.content for i in live.working_memory.list_by_kind("constraint")
        )
        self.assertIn("must use Dutch", constraint_texts + " ".join(live.task.constraints))
        self.assertTrue(
            any("never expose secrets" in c for c in live.task.constraints)
            or "never expose secrets" in constraint_texts
        )
        self.assertIn(hydrated["status"], {s.value for s in CognitiveRunStatus})


if __name__ == "__main__":
    unittest.main()
