"""WAVE 04 — temporal knowledge / epistemic firewall adversarial tests."""

from __future__ import annotations

import unittest

from Data.modules.market_sim.brain_hooks import BrainFacade
from Data.modules.market_sim.epistemic import (
    EpistemicFirewall,
    EvaluationWindow,
    TemporalClass,
    filter_hits_for_as_of,
    resolve_temporal_class,
)
from Data.modules.market_sim.trading_brain import TradingBrainAdapter, TradingRetrievalRequest


class _StaticKnowledge:
    def __init__(self, hits: list[dict]) -> None:
        self._hits = hits

    def search(self, query: str, *, limit: int = 3) -> list[dict]:
        return list(self._hits)[:limit]


class EpistemicFirewallW04Tests(unittest.TestCase):
    def test_2024_paper_unavailable_in_2020_simulation(self) -> None:
        hits = [
            {
                "source": "knowledge",
                "document_id": "paper-2024",
                "title": "2024 microstructure paper",
                "content": "new alpha idea",
                "available_at": "2024-06-01T00:00:00+00:00",
                "temporal_class": "TIME_SENSITIVE",
            }
        ]
        kept, receipts = filter_hits_for_as_of(
            hits, as_of="2020-01-01T00:00:00+00:00"
        )
        self.assertEqual(kept, [])
        self.assertEqual(receipts[0].reason, "available_at_after_as_of")

    def test_earnings_after_close_unavailable_before_publication(self) -> None:
        hits = [
            {
                "source": "knowledge",
                "title": "AAPL earnings",
                "content": "beat estimates",
                "published_at": "2024-01-01T21:05:00+00:00",
                "available_at": "2024-01-01T21:05:00+00:00",
            }
        ]
        kept, receipts = filter_hits_for_as_of(
            hits, as_of="2024-01-01T20:59:00+00:00"
        )
        self.assertEqual(kept, [])
        self.assertTrue(receipts)

    def test_revised_macro_requires_revision_timestamp(self) -> None:
        # Original release available; revision not yet.
        original = {
            "source": "knowledge",
            "title": "CPI release",
            "content": "CPI 3.0",
            "available_at": "2023-01-12T13:30:00+00:00",
            "revision_id": "v1",
        }
        revised = {
            "source": "knowledge",
            "title": "CPI release revised",
            "content": "CPI 3.1 revised",
            "available_at": "2023-02-01T13:30:00+00:00",
            "revision_id": "v2",
        }
        kept, _ = filter_hits_for_as_of(
            [original, revised], as_of="2023-01-15T00:00:00+00:00"
        )
        self.assertEqual(len(kept), 1)
        self.assertIn("3.0", kept[0]["content"])

    def test_timeless_sharpe_definition_remains_available(self) -> None:
        hits = [
            {
                "source": "knowledge",
                "title": "Sharpe ratio definition",
                "content": "excess return over volatility",
                "temporal_class": "TIMELESS_REFERENCE",
            }
        ]
        kept, receipts = filter_hits_for_as_of(
            hits, as_of="2010-01-01T00:00:00+00:00"
        )
        self.assertEqual(len(kept), 1)
        self.assertEqual(receipts, [])

    def test_unknown_timestamp_on_historical_news_blocked(self) -> None:
        hits = [
            {
                "source": "knowledge",
                "title": "breaking news headline",
                "content": "fed hike rumor",
                # no available_at
            }
        ]
        self.assertEqual(resolve_temporal_class(hits[0]), TemporalClass.TIME_SENSITIVE)
        kept, receipts = filter_hits_for_as_of(
            hits, as_of="2020-01-01T00:00:00+00:00"
        )
        self.assertEqual(kept, [])
        self.assertEqual(receipts[0].reason, "missing_available_at_blocked")

    def test_rename_reindex_preserves_available_at(self) -> None:
        # Provenance stamp survives rename-style metadata reshapes.
        original = {
            "document_id": "doc-1",
            "title": "filing",
            "content": "8-K",
            "metadata": {"available_at": "2022-03-01T00:00:00+00:00"},
        }
        renamed = {
            "documentId": "doc-1-renamed",
            "title": "filing",
            "content": "8-K",
            "metadata": {"available_at": "2022-03-01T00:00:00+00:00"},
        }
        kept, _ = filter_hits_for_as_of(
            [original, renamed], as_of="2022-06-01T00:00:00+00:00"
        )
        self.assertEqual(len(kept), 2)
        blocked, receipts = filter_hits_for_as_of(
            [renamed], as_of="2021-01-01T00:00:00+00:00"
        )
        self.assertEqual(blocked, [])
        self.assertEqual(receipts[0].available_at, "2022-03-01T00:00:00+00:00")

    def test_brain_facade_fail_closed_untimestamped(self) -> None:
        facade = BrainFacade(
            knowledge=_StaticKnowledge(
                [
                    {
                        "document_id": "n1",
                        "title": "news flash",
                        "content": "rumor",
                    }
                ]
            )
        )
        fw = EpistemicFirewall(as_of="2020-01-01T00:00:00+00:00", window=EvaluationWindow.RESEARCH)
        out = facade.retrieve("rumor", as_of=fw.as_of, firewall=fw, time_sensitive=True)
        self.assertTrue(out.miss)
        self.assertGreaterEqual(fw.violations, 1)

    def test_trading_adapter_blocks_future_docs(self) -> None:
        class _Searcher:
            def search(self, query: str, *, limit: int = 3):
                return [
                    {
                        "document_id": "future",
                        "title": "future paper",
                        "content": "secret",
                        "available_at": "2025-01-01T00:00:00+00:00",
                    }
                ]

        # Force lexical path via knowledge_store stub with search_lexical
        class _Store:
            def search_lexical(self, query: str, *, limit: int = 3):
                return _Searcher().search(query, limit=limit)

        adapter = TradingBrainAdapter(knowledge_store=_Store())
        fw = EpistemicFirewall(as_of="2021-01-01T00:00:00+00:00")
        result = adapter.retrieve(
            TradingRetrievalRequest(query="secret", decision_as_of=fw.as_of, max_hits=3),
            firewall=fw,
        )
        self.assertTrue(result.miss)
        self.assertTrue(any("as_of_filter_dropped" in n for n in result.notes))


if __name__ == "__main__":
    unittest.main()
