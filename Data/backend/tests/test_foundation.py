from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.backend.database import Database
from Data.backend.reasoning import ReasoningEngine


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "leviathan-test.db")
        self.db.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_conversation_and_messages_persist(self) -> None:
        conversation = self.db.create_conversation()
        self.db.add_message(conversation["id"], "user", "hello")
        self.db.add_message(conversation["id"], "assistant", "hi")

        messages = self.db.get_messages(conversation["id"])
        self.assertEqual([item["role"] for item in messages], ["user", "assistant"])
        self.assertEqual(messages[0]["content"], "hello")

    def test_knowledge_can_be_retrieved(self) -> None:
        self.db.upsert_knowledge(
            title="Leviathan architecture",
            content="The runtime uses SQLite knowledge retrieval and a small reasoning layer.",
            source="test",
        )
        matches = self.db.search_knowledge("SQLite reasoning", limit=5)
        self.assertTrue(matches)
        self.assertEqual(matches[0]["title"], "Leviathan architecture")


class ReasoningTests(unittest.TestCase):
    def test_coding_request_gets_coding_intent(self) -> None:
        plan = ReasoningEngine().analyze("Can you debug this Python function?", has_knowledge=True)
        self.assertEqual(plan.intent, "coding")
        self.assertTrue(plan.use_knowledge)
        self.assertIn("retrieve_relevant_knowledge", plan.steps)

    def test_short_conversation_does_not_force_knowledge(self) -> None:
        plan = ReasoningEngine().analyze("hello", has_knowledge=True)
        self.assertIn(plan.intent, {"conversation", "greeting", "casual_conversation"})
        self.assertFalse(plan.use_knowledge)


if __name__ == "__main__":
    unittest.main()
