"""W127 paper-forward drift + W128 trading research bridge."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.market_sim.paper_forward_drift import (
    paper_forward_drift_review,
    persist_drift_lesson,
)
from Data.modules.market_sim.trading_research_bridge import request_trading_research
from Data.modules.research.store import ResearchStore
from Data.modules.research.service import ResearchService
from Data.modules.research.web import UnconfiguredWebProvider


class PaperForwardDriftTests(unittest.TestCase):
    def test_insufficient_sample_is_unmeasured(self) -> None:
        out = paper_forward_drift_review(
            baseline_metrics={"sharpe": 1.0},
            observed_metrics={"sharpe": 0.1},
            sample_size=2,
        )
        self.assertEqual(out["status"], "UNMEASURED")
        self.assertEqual(out["driftCount"], 0)
        self.assertIsNone(out["continualResearch"])

    def test_drift_opens_research_ticket_without_auto_disable(self) -> None:
        out = paper_forward_drift_review(
            baseline_metrics={"sharpe": 1.0, "max_dd": -0.05},
            observed_metrics={"sharpe": 0.1, "max_dd": -0.4},
            strategy_id="mom",
            strategy_version="3",
            sample_size=20,
        )
        self.assertEqual(out["status"], "DRIFT_DETECTED")
        self.assertGreaterEqual(out["driftCount"], 1)
        ticket = out["continualResearch"]
        self.assertIsNotNone(ticket)
        self.assertTrue(ticket["truth"]["does_not_auto_disable"])
        self.assertTrue(ticket["truth"]["live_trading_blocked"])

        saved: list[dict] = []
        research_calls: list[str] = []
        persist = persist_drift_lesson(
            out,
            strategy_memory_writer=lambda m: saved.append(m) or m,
            research_requester=lambda q: research_calls.append(q) or {"queued": True},
        )
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["metadata"]["origin"], "PAPER_FORWARD_DRIFT")
        self.assertEqual(saved[0]["metadata"]["epistemic_state"], "PAPER_OBSERVED")
        self.assertTrue(research_calls)
        self.assertIsNotNone(persist.get("memoryId") or saved[0].get("memory_id"))


class TradingResearchBridgeTests(unittest.TestCase):
    def test_urgent_gap_returns_hold_hint_without_sync_crawl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ResearchStore(Path(tmp) / "r.db")
            store.initialize()
            service = ResearchService(
                store,
                web=UnconfiguredWebProvider(),
                allow_outbound=False,
            )
            with mock.patch.object(service, "run", return_value=None) as run_mock:
                out = request_trading_research(
                    service,
                    question="Do funding-rate extremes predict BTC reversal?",
                    instrument="BTC-USD",
                    urgency="urgent",
                    allow_web=False,
                )
            self.assertIn(out["status"], {"WAITING", "QUEUED"})
            self.assertEqual(out["decisionHint"], "HOLD")
            self.assertEqual(out["decisionCode"], "INSUFFICIENT_EVIDENCE")
            self.assertTrue(out["truth"]["synchronous_web_research_forbidden_here"])
            self.assertTrue(out.get("projectId"))
            run_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
