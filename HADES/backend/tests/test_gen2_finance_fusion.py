"""Characterization tests for Gen2 Finance Fusion extraction."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.finance_fusion import (
    classify_catalyst,
    fuse_market_intelligence,
    guess_company,
    horizon_for,
)
from gen2.services import Gen2Services
from gen2.store import Gen2Store


class FinanceFusionModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "finance.db"))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_classify_catalyst_keywords(self) -> None:
        self.assertEqual(classify_catalyst("Major acquisition announced"), "m_and_a")
        self.assertEqual(classify_catalyst("Q2 earnings beat EPS"), "earnings")
        self.assertEqual(classify_catalyst("CEO resignation filed"), "management_change")
        self.assertEqual(classify_catalyst("SEC regulatory probe"), "regulation")
        self.assertEqual(classify_catalyst("Bitcoin rally continues"), "crypto")
        self.assertEqual(classify_catalyst("Random headline"), "general_market")

    def test_horizon_for_known_types(self) -> None:
        self.assertEqual(horizon_for("earnings"), "days")
        self.assertEqual(horizon_for("m_and_a"), "weeks")
        self.assertEqual(horizon_for("regulation"), "months")
        self.assertEqual(horizon_for("unknown_type"), "unknown")

    def test_guess_company_from_title(self) -> None:
        self.assertEqual(guess_company("NVIDIA announces product launch"), "NVIDIA")
        self.assertIsNone(guess_company("all lowercase no ticker"))

    def test_fuse_dedupes_and_persists(self) -> None:
        result = fuse_market_intelligence(
            self.store,
            articles=[
                {
                    "title": "Acme announces earnings beat",
                    "summary": "EPS above estimates",
                    "uri": "local://a",
                    "source": "wire",
                },
                {
                    "title": "Acme announces earnings beat",
                    "summary": "dup",
                    "uri": "local://b",
                },
                {
                    "title": "Acme CEO resignation rumor",
                    "summary": "management change",
                    "source_count": 2,
                },
            ],
            symbol="ACME",
        )
        self.assertEqual(result["count"], 2)
        self.assertTrue(result["hypothesis"]["paper_only"])
        types = {e["event_type"] for e in result["events"]}
        self.assertIn("earnings", types)
        self.assertIn("management_change", types)
        for event in result["events"]:
            self.assertIn("ACME", event["entities"])
            self.assertIn("likely_horizon", event)
        self.assertGreaterEqual(len(self.store.list_graph_edges(limit=50)), 1)

    def test_fuse_empty_articles_honest(self) -> None:
        result = fuse_market_intelligence(self.store, articles=[])
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["note"], "no_articles_to_fuse")
        self.assertEqual(result["events"], [])
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("error"), "no_articles_to_fuse")

    def test_services_delegate_and_private_helpers(self) -> None:
        svc = Gen2Services(self.store, data_root=Path(self.temp.name))
        self.assertEqual(svc._classify_catalyst("merger talks"), "m_and_a")
        self.assertEqual(svc._horizon_for("earnings"), "days")
        self.assertEqual(svc._guess_company("IBM expands cloud"), "IBM")
        out = svc.fuse_market_intelligence(
            articles=[{"title": "Oil supply chain disruption", "summary": "fabriek tekort"}],
            symbol="XOM",
        )
        self.assertEqual(out["count"], 1)
        self.assertIn(out["events"][0]["event_type"], {"supply_chain", "commodities"})


if __name__ == "__main__":
    unittest.main()
