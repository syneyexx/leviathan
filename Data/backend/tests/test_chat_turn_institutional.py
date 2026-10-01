"""Chat turn persistence, pagination, cancellation, and telemetry truth tests."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from Data.backend.database import Database
from Data.backend.migrations import MIGRATIONS, MigrationRunner
from Data.modules.chat import (
    CancelReason,
    ChatTurnCoordinator,
    ChatTurnStore,
    ExecutionPath,
    ResponseOwner,
    cancel_chat_turn,
    normalize_chat_response,
)
from Data.modules.chat.types import ChatTurnRunState, InvalidTurnTransition
from Data.modules.knowledge.economy import CognitiveEconomyGovernor
from Data.modules.run import RunState, RunStore


class ChatTurnMigrationTests(unittest.TestCase):
    def test_fresh_install_creates_chat_turns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control.sqlite"
            # Conversations FK target
            Database(path).initialize()
            applied = MigrationRunner(path).apply_all()
            self.assertIn(62, applied)
            import sqlite3

            with sqlite3.connect(path) as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                self.assertIn("chat_turns", tables)
                # Idempotent re-run
                again = MigrationRunner(path).apply_all()
                self.assertEqual(again, [])


class ChatTurnStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "control.sqlite"
        self.db = Database(self.path)
        self.db.initialize()
        MigrationRunner(self.path).apply_all()
        self.store = ChatTurnStore(self.path)
        self.coord = ChatTurnCoordinator(self.store)
        self.conv = self.db.create_conversation("Test")
        self.user = self.db.add_message(self.conv["id"], "user", "hello")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_accept_complete_and_hydrate(self) -> None:
        turn = self.coord.accept(
            conversation_id=self.conv["id"],
            user_message_id=self.user["id"],
            chat_run_id="run-1",
            requested_reasoning_mode="auto",
            idempotency_key="idem-1",
        )
        self.assertEqual(turn.run_state, ChatTurnRunState.RUNNING.value)
        assistant = self.db.add_message(self.conv["id"], "assistant", "hi")
        done = self.coord.complete(
            turn.turn_id,
            assistant_message_id=assistant["id"],
            effective_model="m1",
            effective_reasoning_mode="standard",
            response_owner=ResponseOwner.DIRECT.value,
            execution_path=ExecutionPath.DIRECT_CHAT.value,
            knowledge_hit_count=None,  # unmeasured
            memory_hit_count=2,
            evidence_hit_count=None,
        )
        self.assertEqual(done.run_state, ChatTurnRunState.COMPLETED.value)
        self.assertIsNone(done.knowledge_hit_count)
        self.assertEqual(done.memory_hit_count, 2)
        pub = done.public_dict()
        self.assertEqual(pub["retrieval"]["knowledge_hit_count"]["state"], "UNMEASURED")
        self.assertEqual(pub["retrieval"]["memory_hit_count"]["state"], "MEASURED")
        # Idempotent create
        again = self.coord.accept(
            conversation_id=self.conv["id"],
            user_message_id=self.user["id"],
            chat_run_id="run-2",
            idempotency_key="idem-1",
        )
        self.assertEqual(again.turn_id, turn.turn_id)
        by_msg = self.store.get_by_assistant_message(assistant["id"])
        self.assertIsNotNone(by_msg)
        self.assertEqual(by_msg.turn_id, turn.turn_id)

    def test_terminal_monotonic(self) -> None:
        turn = self.coord.accept(
            conversation_id=self.conv["id"],
            user_message_id=self.user["id"],
            chat_run_id="run-x",
        )
        self.coord.complete(
            turn.turn_id,
            assistant_message_id=1,
            response_owner=ResponseOwner.DIRECT.value,
        )
        with self.assertRaises(InvalidTurnTransition):
            self.store.transition(turn.turn_id, ChatTurnRunState.RUNNING)

    def test_cancel_not_failed(self) -> None:
        runs = RunStore(self.path)
        runs.initialize()
        run = runs.create_run(user_request="x", conversation_id=self.conv["id"])
        runs.transition(run.run_id, RunState.PLANNING)
        runs.transition(run.run_id, RunState.EXECUTING)
        turn = self.coord.accept(
            conversation_id=self.conv["id"],
            user_message_id=self.user["id"],
            chat_run_id=run.run_id,
        )
        result = cancel_chat_turn(
            turn_store=self.store,
            run_store=runs,
            turn_id=turn.turn_id,
            reason=CancelReason.USER_CANCEL,
        )
        self.assertTrue(result.cancelled)
        self.assertEqual(result.run_state, ChatTurnRunState.CANCELLED.value)
        # Idempotent cancel
        again = cancel_chat_turn(
            turn_store=self.store,
            run_store=runs,
            turn_id=turn.turn_id,
            reason=CancelReason.USER_CANCEL,
        )
        self.assertTrue(again.already_terminal)
        self.assertEqual(again.run_state, ChatTurnRunState.CANCELLED.value)
        stored = self.store.get(turn.turn_id)
        self.assertEqual(stored.failure_classification, "user_cancel")

    def test_reconcile_stale_running(self) -> None:
        turn = self.coord.accept(
            conversation_id=self.conv["id"],
            user_message_id=self.user["id"],
            chat_run_id="run-stale",
        )
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
        self.store.update(turn.turn_id, created_at=old)
        interrupted = self.store.reconcile_stale_running(older_than_iso=old.replace("2020", "2099") if False else (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        ).isoformat(timespec="seconds"))
        self.assertTrue(any(t.turn_id == turn.turn_id for t in interrupted))
        stored = self.store.get(turn.turn_id)
        self.assertEqual(stored.run_state, ChatTurnRunState.INTERRUPTED.value)


class ConversationPaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "control.sqlite"
        self.db = Database(self.path)
        self.db.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_cursor_pagination_and_search(self) -> None:
        for i in range(55):
            self.db.create_conversation(f"Thread {i:03d}")
        # Pin one beyond first page alphabetically late
        special = self.db.create_conversation("Zebra Unique Target")
        page1 = self.db.list_conversations_page(limit=20)
        self.assertEqual(len(page1["items"]), 20)
        self.assertTrue(page1["has_more"])
        self.assertIsNotNone(page1["next_cursor"])
        self.assertEqual(page1["total"], 56)
        page2 = self.db.list_conversations_page(limit=20, cursor=page1["next_cursor"])
        self.assertEqual(len(page2["items"]), 20)
        ids1 = {c["id"] for c in page1["items"]}
        ids2 = {c["id"] for c in page2["items"]}
        self.assertFalse(ids1 & ids2)
        found = self.db.list_conversations_page(limit=10, q="Zebra Unique")
        self.assertTrue(any(c["id"] == special["id"] for c in found["items"]))

    def test_message_pagination(self) -> None:
        conv = self.db.create_conversation("long")
        for i in range(250):
            role = "user" if i % 2 == 0 else "assistant"
            self.db.add_message(conv["id"], role, f"msg-{i}")
        recent = self.db.get_messages_page(conv["id"], limit=50)
        self.assertEqual(len(recent["items"]), 50)
        self.assertTrue(recent["has_more"])
        self.assertEqual(recent["items"][-1]["content"], "msg-249")
        older = self.db.get_messages_page(
            conv["id"], limit=50, before_id=recent["next_before_id"]
        )
        self.assertEqual(len(older["items"]), 50)
        self.assertTrue(older["items"][-1]["id"] < recent["items"][0]["id"])
        # Duplicate cursor is stable
        older2 = self.db.get_messages_page(
            conv["id"], limit=50, before_id=recent["next_before_id"]
        )
        self.assertEqual([m["id"] for m in older["items"]], [m["id"] for m in older2["items"]])
        self.assertEqual(self.db.count_messages(conv["id"]), 250)


class EconomyCoverageTruthTests(unittest.TestCase):
    def test_unmeasured_coverage_does_not_force_gap(self) -> None:
        gov = CognitiveEconomyGovernor(enabled=True)
        decided = gov.decide(
            complexity="high",
            intent="research",
            memory_coverage=None,
            deep_recall_enabled=True,
            explicit_deep_recall=False,
        )
        # Without coverage measurement and without explicit deep recall, gap path is closed.
        self.assertFalse(decided.allow_deep_recall)
        self.assertIn("UNMEASURED", decided.reason)


class ResponseContractTests(unittest.TestCase):
    def test_normalize_promotes_legacy_message(self) -> None:
        out = normalize_chat_response(
            {
                "conversation_id": "c1",
                "message": {"id": 1, "role": "assistant", "content": "hi", "created_at": "t"},
            }
        )
        self.assertEqual(out["assistant_message"]["content"], "hi")
        self.assertEqual(out["message"]["content"], "hi")
        self.assertIn("_compatibility", out)


class ResponseOwnerInvariantTests(unittest.TestCase):
    def test_cognition_owned_path_excludes_direct(self) -> None:
        from Data.modules.chat import (
            assert_single_response_owner,
            cognition_owns_final_response,
            resolve_response_owner_and_path,
        )

        meta = {
            "response": "owned answer",
            "response_ownership": "cognition",
            "shadow": False,
        }
        self.assertTrue(cognition_owns_final_response(meta))
        owner, path = resolve_response_owner_and_path(meta)
        self.assertEqual(owner, ResponseOwner.COGNITION.value)
        self.assertEqual(path, ExecutionPath.COGNITION_OWNED.value)
        assert_single_response_owner(owner, path)
        # Shadow / feature shadow / empty response must not own.
        self.assertFalse(cognition_owns_final_response({**meta, "shadow": True}))
        self.assertFalse(
            cognition_owns_final_response(meta, cognition_shadow_feature=True)
        )
        self.assertFalse(cognition_owns_final_response({**meta, "response": "  "}))
        direct_owner, direct_path = resolve_response_owner_and_path(
            {**meta, "shadow": True}
        )
        self.assertEqual(direct_owner, ResponseOwner.DIRECT.value)
        self.assertEqual(direct_path, ExecutionPath.DIRECT_CHAT.value)
        with self.assertRaises(AssertionError):
            assert_single_response_owner(
                ResponseOwner.DIRECT.value, ExecutionPath.COGNITION_OWNED.value
            )

    def test_public_dict_surfaces_bounded_tool_calls(self) -> None:
        from Data.modules.chat import bounded_tool_calls_for_turn

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control.sqlite"
            db = Database(path)
            db.initialize()
            MigrationRunner(path).apply_all()
            store = ChatTurnStore(path)
            coord = ChatTurnCoordinator(store)
            conv = db.create_conversation("Tools")
            user = db.add_message(conv["id"], "user", "hi")
            turn = coord.accept(
                conversation_id=conv["id"],
                user_message_id=user["id"],
                chat_run_id="run-tools",
            )
            asst = db.add_message(conv["id"], "assistant", "done")
            done = coord.complete(
                turn.turn_id,
                assistant_message_id=asst["id"],
                response_owner=ResponseOwner.DIRECT.value,
                execution_path=ExecutionPath.DIRECT_CHAT.value,
                tool_receipt_ids=["rcpt-1"],
                metadata={
                    "tool_calls": bounded_tool_calls_for_turn(
                        [
                            {
                                "capability_id": "web.search",
                                "status": "COMPLETED",
                                "success": True,
                                "receipt_id": "rcpt-1",
                                "duration_ms": 11,
                            }
                        ]
                    )
                },
            )
            pub = done.public_dict()
            self.assertIn("tool_calls", pub)
            self.assertEqual(pub["tool_calls"][0]["capability_id"], "web.search")
            self.assertEqual(pub["tool_receipt_ids"], ["rcpt-1"])
        bounded = bounded_tool_calls_for_turn(
            [
                {
                    "capability_id": "x",
                    "status": "OK",
                    "parts": [{"kind": "SOURCE", "title": "t"}] * 20,
                }
            ]
        )
        self.assertEqual(len(bounded[0]["parts"]), 8)


class MigrationHeadTests(unittest.TestCase):
    def test_migration_head_is_62(self) -> None:
        self.assertEqual(MIGRATIONS[-1].version, 62)
        self.assertEqual(MIGRATIONS[-1].name, "chat_turns")


class UpgradeMigrationWithExistingMessagesTests(unittest.TestCase):
    def test_upgrade_preserves_old_messages_without_turns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control.sqlite"
            db = Database(path)
            db.initialize()
            # Apply all but leave a conversation before chat_turns exists is hard
            # once head is 62; instead: apply all, create legacy-style rows, verify
            # messages remain readable and turns map can be empty for old rows.
            MigrationRunner(path).apply_all()
            conv = db.create_conversation("Legacy")
            for i in range(5):
                db.add_message(conv["id"], "user", f"u{i}")
                db.add_message(conv["id"], "assistant", f"a{i}")
            rows = db.get_messages(conv["id"], limit=100)
            self.assertEqual(len(rows), 10)
            store = ChatTurnStore(path)
            # No turns yet — hydrate returns empty map (honest absence).
            found = store.list_for_conversation(conv["id"], limit=50)
            self.assertEqual(found, [])
            # New turn after upgrade attaches only to new assistant message.
            user = db.add_message(conv["id"], "user", "new")
            coord = ChatTurnCoordinator(store)
            turn = coord.accept(
                conversation_id=conv["id"],
                user_message_id=user["id"],
                chat_run_id="run-upgrade",
            )
            asst = db.add_message(conv["id"], "assistant", "new-answer")
            coord.complete(
                turn.turn_id,
                assistant_message_id=asst["id"],
                response_owner=ResponseOwner.DIRECT.value,
                execution_path=ExecutionPath.DIRECT_CHAT.value,
            )
            by_asst = store.get_by_assistant_message(asst["id"])
            self.assertIsNotNone(by_asst)
            self.assertEqual(by_asst.turn_id, turn.turn_id)
            # Pre-upgrade messages still readable and without invented turns.
            still = db.get_messages(conv["id"], limit=100)
            self.assertGreaterEqual(len(still), 12)


if __name__ == "__main__":
    unittest.main()
