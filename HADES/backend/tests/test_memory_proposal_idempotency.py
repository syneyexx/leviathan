"""Memory proposal idempotency + unified Stop markers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from database import Database


class MemoryProposalIdempotencyTests(unittest.TestCase):
    def test_same_source_message_does_not_duplicate_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(str(Path(tmp) / "hades.db"))
            db.initialize()
            first = db.create_memory_proposal(
                {
                    "title": "Voorkeur",
                    "content": "Gebruiker wil Nederlands",
                    "origin_kind": "model_inference",
                    "source_message_id": "msg_abc",
                    "source_conversation_id": "conv_1",
                }
            )
            second = db.create_memory_proposal(
                {
                    "title": "Voorkeur opnieuw",
                    "content": "Gebruiker wil Nederlands (opnieuw gescand)",
                    "origin_kind": "model_inference",
                    "source_message_id": "msg_abc",
                    "source_conversation_id": "conv_1",
                }
            )
            self.assertEqual(first["id"], second["id"])
            pending = db.list_memory_proposals("pending")
            self.assertEqual(len(pending), 1)


class UnifiedCancelMarkersTests(unittest.TestCase):
    def test_chat_stop_cancels_linked_engines(self) -> None:
        chat = Path(__file__).resolve().parents[2] / "components" / "hades" / "pages" / "chat-page.tsx"
        source = chat.read_text(encoding="utf-8")
        self.assertIn("Unified Stop", source)
        self.assertIn("buildJobCancel", source)
        self.assertIn("cancelResearch", source)
        self.assertIn("cancelTask", source)


if __name__ == "__main__":
    unittest.main()
