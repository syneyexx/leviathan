"""Conversation research route: delegates to ResearchRunner; respects network_policy."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ConversationResearchRouteTests(unittest.TestCase):
    def test_route_exists_and_binds(self) -> None:
        main = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
        self.assertIn('/conversations/{conversation_id}/research', main)
        self.assertIn("bind_conversation_run", main)
        self.assertIn('run_type="research"', main)
        self.assertIn("network_policy=block", main)
        self.assertIn("ResearchRunner", main)

    def test_research_card_zero_sources_not_success(self) -> None:
        card = (ROOT / "components" / "hades" / "features" / "chat" / "ResearchCard.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("Geen bronnen gevonden — dit is geen succesvol onderzoek.", card)
        self.assertIn("completedEmpty", card)
        self.assertIn("sourceCount <= 0", card)


if __name__ == "__main__":
    unittest.main()
