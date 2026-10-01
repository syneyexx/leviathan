"""Failure-injection and concurrency tests for Chat institutional paths."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from Data.backend.database import Database
from Data.backend.migrations import MigrationRunner
from Data.modules.chat import (
    CancelReason,
    ChatTurnCoordinator,
    ChatTurnStore,
    cancel_chat_turn,
)
from Data.modules.chat.cognition_stream import (
    CognitionPublicSink,
    map_cognition_events_to_public_sink,
)
from Data.modules.chat.types import ChatTurnRunState
from Data.modules.run import RunState, RunStore


class ChatCancelRaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "control.sqlite"
        self.db = Database(self.path)
        self.db.initialize()
        MigrationRunner(self.path).apply_all()
        self.store = ChatTurnStore(self.path)
        self.coord = ChatTurnCoordinator(self.store)
        self.runs = RunStore(self.path)
        self.runs.initialize()
        self.conv = self.db.create_conversation("race")
        self.user = self.db.add_message(self.conv["id"], "user", "hi")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_cancel_after_completed_keeps_completed(self) -> None:
        run = self.runs.create_run(user_request="x", conversation_id=self.conv["id"])
        self.runs.transition(run.run_id, RunState.PLANNING)
        self.runs.transition(run.run_id, RunState.EXECUTING)
        turn = self.coord.accept(
            conversation_id=self.conv["id"],
            user_message_id=self.user["id"],
            chat_run_id=run.run_id,
        )
        self.runs.transition(run.run_id, RunState.COMPLETED, output="done")
        self.coord.complete(turn.turn_id, assistant_message_id=99)
        result = cancel_chat_turn(
            turn_store=self.store,
            run_store=self.runs,
            turn_id=turn.turn_id,
            reason=CancelReason.USER_CANCEL,
        )
        self.assertTrue(result.already_terminal)
        self.assertEqual(result.run_state, ChatTurnRunState.COMPLETED.value)
        stored = self.store.get(turn.turn_id)
        self.assertEqual(stored.run_state, ChatTurnRunState.COMPLETED.value)

    def test_duplicate_cancel_safe(self) -> None:
        run = self.runs.create_run(user_request="x", conversation_id=self.conv["id"])
        self.runs.transition(run.run_id, RunState.PLANNING)
        self.runs.transition(run.run_id, RunState.EXECUTING)
        turn = self.coord.accept(
            conversation_id=self.conv["id"],
            user_message_id=self.user["id"],
            chat_run_id=run.run_id,
        )
        for _ in range(3):
            cancel_chat_turn(
                turn_store=self.store,
                run_store=self.runs,
                turn_id=turn.turn_id,
                reason=CancelReason.USER_CANCEL,
            )
        stored = self.store.get(turn.turn_id)
        self.assertEqual(stored.run_state, ChatTurnRunState.CANCELLED.value)

    def test_cognition_cancel_propagates(self) -> None:
        run = self.runs.create_run(user_request="x", conversation_id=self.conv["id"])
        self.runs.transition(run.run_id, RunState.PLANNING)
        self.runs.transition(run.run_id, RunState.EXECUTING)
        turn = self.coord.accept(
            conversation_id=self.conv["id"],
            user_message_id=self.user["id"],
            chat_run_id=run.run_id,
        )
        self.store.update(turn.turn_id, cognition_run_id="cog-1")
        cognition = MagicMock()
        cognition.cancel.return_value = {"run_id": "cog-1", "status": "CANCELLED"}
        result = cancel_chat_turn(
            turn_store=self.store,
            run_store=self.runs,
            cognition_runtime=cognition,
            turn_id=turn.turn_id,
            reason=CancelReason.USER_CANCEL,
        )
        cognition.cancel.assert_called_once_with("cog-1")
        self.assertEqual(result.cognition_cancel["status"], "CANCELLED")
        self.assertTrue(result.cancelled)


class CognitionPublicSinkTests(unittest.TestCase):
    def test_drops_private_reasoning(self) -> None:
        sink = CognitionPublicSink()
        sink.emit("private.cot", text="secret")
        sink.emit("tool.started", capability_id="web.search")
        sink.append_public_token("Hello")
        events = sink.events()
        types = [e["event_type"] for e in events]
        self.assertNotIn("private.cot", types)
        self.assertIn("tool.started", types)
        self.assertIn("model.output", types)
        payloads = list(sink.iter_sse_payloads())
        self.assertTrue(any(name == "token" for name, _ in payloads))

    def test_map_operational_events(self) -> None:
        sink = CognitionPublicSink()
        map_cognition_events_to_public_sink(
            [
                {"event_type": "tool.completed", "payload": {"capability_id": "x"}},
                {"event_type": "hidden.internal", "payload": {}},
            ],
            sink,
        )
        types = [e["event_type"] for e in sink.events()]
        self.assertEqual(types, ["tool.completed"])


class InvalidCursorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "control.sqlite"
        self.db = Database(self.path)
        self.db.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_invalid_cursor_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.db.list_conversations_page(limit=10, cursor="not-a-cursor")


class MessageSwitchMidFetchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "control.sqlite"
        self.db = Database(self.path)
        self.db.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_pages_are_conversation_scoped(self) -> None:
        a = self.db.create_conversation("A")
        b = self.db.create_conversation("B")
        for i in range(30):
            self.db.add_message(a["id"], "user", f"a-{i}")
            self.db.add_message(b["id"], "user", f"b-{i}")
        page_a = self.db.get_messages_page(a["id"], limit=10)
        page_b = self.db.get_messages_page(b["id"], limit=10)
        self.assertTrue(all(m["conversation_id"] == a["id"] for m in page_a["items"]))
        self.assertTrue(all(m["conversation_id"] == b["id"] for m in page_b["items"]))
        self.assertTrue(all(m["content"].startswith("a-") for m in page_a["items"]))


if __name__ == "__main__":
    unittest.main()
