"""WAVE 05 — role-aware trading knowledge retrieval with citations."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.knowledge import KnowledgeStore
from Data.modules.knowledge.embeddings import NullEmbeddingProvider
from Data.modules.market_sim.role_knowledge import (
    RoleAwareTradingKnowledge,
    intent_for_role,
)
from Data.modules.market_sim.trading_brain import TradingBrainAdapter


class RoleKnowledgeW05Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "k.db"
        self.data_root = self.root / "data"
        self.data_root.mkdir()
        self.store = KnowledgeStore(
            self.db,
            data_root=self.data_root,
            embedding_provider=NullEmbeddingProvider(),
        )
        self.store.initialize()
        docs = {
            "momentum_structures.txt": (
                "Momentum strategy structures use lookback windows and known failure "
                "modes include transaction cost sensitivity and regime breaks."
            ),
            "overfitting_risks.txt": (
                "Data mining and overfitting concerns arise when many variants are tested "
                "without multiple-testing correction; contradictory research must be surfaced."
            ),
            "tail_risk_leverage.txt": (
                "Tail risk and leverage concentration can destroy portfolios during "
                "liquidity freezes and correlation spikes."
            ),
            "failed_trials_lessons.txt": (
                "Similar failed trials show regime break failure categories; validated lessons "
                "remain AGENT_PROPOSED until measured evidence supports them."
            ),
        }
        for name, text in docs.items():
            path = self.data_root / name
            path.write_text(text, encoding="utf-8")
            self.store.ingest_file(path, source=f"dataset:trading-knowledge:{name}")
        self.adapter = TradingBrainAdapter(knowledge_store=self.store)
        self.role_knowledge = RoleAwareTradingKnowledge(self.adapter)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _assert_cited(self, payload: dict, *, must_contain: str) -> None:
        self.assertTrue(payload["citations"], msg=payload)
        self.assertTrue(payload["truth"]["knowledge_is_hypothesis_source"])
        self.assertTrue(payload["truth"]["only_leviathan_measured_experiments_qualify"])
        blob = " ".join(
            str(c["hit"].get("contentExcerpt") or "") for c in payload["citations"]
        ).lower()
        self.assertIn(must_contain.lower(), blob)
        cite = payload["citations"][0]["citation"]
        self.assertTrue(cite.get("documentId") or cite.get("title"))

    def test_strategy_researcher_retrieves_structures(self) -> None:
        intent = intent_for_role("strategy_researcher")
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertIn("candidate strategy structures", intent.asks_for)
        out = self.role_knowledge.retrieve_for_role(
            "strategy_researcher",
            "propose a bounded momentum candidate",
        )
        self._assert_cited(out, must_contain="momentum")

    def test_critic_retrieves_counter_evidence(self) -> None:
        out = self.role_knowledge.retrieve_for_role(
            "critic",
            "challenge this attractive backtest",
        )
        self._assert_cited(out, must_contain="overfitting")

    def test_risk_agent_retrieves_tail_risk(self) -> None:
        out = self.role_knowledge.retrieve_for_role(
            "risk_agent",
            "assess portfolio risk before allocation",
        )
        self._assert_cited(out, must_contain="leverage")

    def test_postmortem_retrieves_lessons(self) -> None:
        out = self.role_knowledge.retrieve_for_role(
            "postmortem",
            "what failed before in similar regimes",
        )
        self._assert_cited(out, must_contain="failed")
        self.assertTrue(out["citations"][0]["hypothesisOnly"])


if __name__ == "__main__":
    unittest.main()
