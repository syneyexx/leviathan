"""Phase 3D: in-thread approvals + work binding markers."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ConversationWorkApprovalTests(unittest.TestCase):
    def test_work_bind_on_chat_route(self) -> None:
        main = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
        self.assertIn('run_type="work"', main)
        self.assertIn("Chat routeerde naar Work Runtime", main)

    def test_in_thread_approval_card(self) -> None:
        cards = (ROOT / "components" / "hades" / "features" / "chat" / "ApprovalWorkCards.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("Approve", cards)
        self.assertIn("Reject", cards)
        self.assertIn("nooit auto-allow", cards)
        chat = (ROOT / "components" / "hades" / "pages" / "chat-page.tsx").read_text(encoding="utf-8")
        self.assertIn("chat-approval-cards", chat)
        self.assertIn("ApprovalCard", chat)
        self.assertIn("WorkCard", chat)


if __name__ == "__main__":
    unittest.main()
