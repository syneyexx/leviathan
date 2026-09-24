from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.run import EventType, RunState, RunStore, validate_transition
from Data.modules.run.states import InvalidRunTransition


class RunTransitionTests(unittest.TestCase):
    def test_failed_cannot_become_completed_directly(self) -> None:
        with self.assertRaises(InvalidRunTransition):
            validate_transition(RunState.FAILED, RunState.COMPLETED)

    def test_completed_is_terminal(self) -> None:
        with self.assertRaises(InvalidRunTransition):
            validate_transition(RunState.COMPLETED, RunState.EXECUTING)

    def test_created_to_planning_allowed(self) -> None:
        validate_transition(RunState.CREATED, RunState.PLANNING)

    def test_retrieving_to_completed_remains_illegal(self) -> None:
        """Chat lifecycle bug guard: retrieval success must go via EXECUTING."""
        with self.assertRaises(InvalidRunTransition):
            validate_transition(RunState.RETRIEVING, RunState.COMPLETED)
        validate_transition(RunState.RETRIEVING, RunState.EXECUTING)
        validate_transition(RunState.EXECUTING, RunState.COMPLETED)


class RunStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RunStore(Path(self.tmp.name) / "runs.db")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_create_and_complete_run(self) -> None:
        run = self.store.create_run(user_request="hello", conversation_id="c1")
        self.assertEqual(run.state, RunState.CREATED)
        self.store.transition(run.run_id, RunState.PLANNING, intent="conversation", complexity="low")
        self.store.transition(run.run_id, RunState.EXECUTING)
        self.store.append_event(run.run_id, EventType.MODEL_STARTED, {})
        completed = self.store.transition(
            run.run_id,
            RunState.COMPLETED,
            selected_model="test-model",
            output="hi",
        )
        self.assertEqual(completed.state, RunState.COMPLETED)
        self.assertEqual(completed.output, "hi")
        events = self.store.list_events(run.run_id)
        types = [item.event_type for item in events]
        self.assertIn(EventType.RUN_CREATED, types)
        self.assertIn(EventType.RUN_COMPLETED, types)

    def test_illegal_transition_is_rejected_and_state_unchanged(self) -> None:
        run = self.store.create_run(user_request="x")
        self.store.transition(run.run_id, RunState.FAILED, error="boom")
        with self.assertRaises(InvalidRunTransition):
            self.store.transition(run.run_id, RunState.COMPLETED)
        current = self.store.get_run(run.run_id)
        assert current is not None
        self.assertEqual(current.state, RunState.FAILED)


if __name__ == "__main__":
    unittest.main()
