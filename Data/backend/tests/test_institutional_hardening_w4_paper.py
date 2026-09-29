"""Wave 4 — paper causality / poison future quotes + LIVE_EXTERNAL honesty."""

from __future__ import annotations

import os
import unittest

from Data.modules.market_sim.paper_causality import (
    filter_quotes_as_of,
    live_external_alpaca_status,
    refuse_future_quote,
)
from Data.modules.market_sim.paper_broker import LocalPaperBroker, paper_fill_key_for_event
from Data.modules.market_sim.types import MarketSimError


class PaperPoisonLookaheadTests(unittest.TestCase):
    def test_future_quote_refused(self) -> None:
        with self.assertRaises(MarketSimError) as ctx:
            refuse_future_quote(
                quote_ts="2026-06-01T12:00:00+00:00",
                as_of="2026-01-01T00:00:00+00:00",
                symbol="BTCUSDT",
                price=99999.0,
            )
        self.assertEqual(ctx.exception.code, "LOOKAHEAD_REFUSED")

    def test_causal_quote_allowed(self) -> None:
        out = refuse_future_quote(
            quote_ts="2025-12-31T23:59:00+00:00",
            as_of="2026-01-01T00:00:00+00:00",
            symbol="BTCUSDT",
            price=100.0,
        )
        self.assertTrue(out["allowed"])
        self.assertEqual(out["status"], "ALLOW")
        self.assertTrue(out["truth"]["no_lookahead"])

    def test_missing_quote_ts_is_unmeasured_not_allow(self) -> None:
        out = refuse_future_quote(quote_ts=None, as_of="2026-01-01T00:00:00+00:00")
        self.assertFalse(out["allowed"])
        self.assertEqual(out["status"], "UNMEASURED")

    def test_poison_future_quotes_invisible_in_filter(self) -> None:
        quotes = [
            {"symbol": "BTC", "price": 100.0, "ts": "2026-01-01T00:00:00+00:00"},
            {"symbol": "BTC", "price": 99999.0, "ts": "2099-01-01T00:00:00+00:00"},  # poison
            {"symbol": "BTC", "price": 101.0, "ts": "2025-12-01T00:00:00+00:00"},
        ]
        out = filter_quotes_as_of(quotes, as_of="2026-01-01T00:00:00+00:00")
        self.assertEqual(out["visible_count"], 2)
        self.assertEqual(out["dropped_count"], 1)
        prices = {q["price"] for q in out["visible"]}
        self.assertNotIn(99999.0, prices)
        self.assertTrue(out["truth"]["poison_future_invisible"])

    def test_paper_fill_idempotent_under_replay(self) -> None:
        broker = LocalPaperBroker(fee_bps=0, slippage_bps=0)
        # Causal fence before fill.
        refuse_future_quote(
            quote_ts="2026-01-01T00:00:00+00:00",
            as_of="2026-01-01T00:00:00+00:00",
            symbol="BTCUSDT",
            price=100.0,
        )
        from Data.modules.market_sim.paper_broker import apply_paper_fill_from_feed_event

        o1 = apply_paper_fill_from_feed_event(
            broker,
            session_id="sess-w4",
            event_id="evt-1",
            symbol="BTCUSDT",
            side="BUY",
            qty=1,
            price=100.0,
        )
        o2 = apply_paper_fill_from_feed_event(
            broker,
            session_id="sess-w4",
            event_id="evt-1",
            symbol="BTCUSDT",
            side="BUY",
            qty=1,
            price=100.0,
        )
        self.assertEqual(o1.order_id, o2.order_id)
        self.assertEqual(
            paper_fill_key_for_event(session_id="sess-w4", event_id="evt-1"),
            o1.client_order_id,
        )


class LiveExternalUnmeasuredTests(unittest.TestCase):
    def test_alpaca_absent_is_unmeasured(self) -> None:
        out = live_external_alpaca_status(credentials_present=False)
        self.assertEqual(out["LIVE_EXTERNAL_TEST"], "UNMEASURED")
        self.assertEqual(out["status"], "UNMEASURED")
        self.assertTrue(out["truth"]["unmeasured_is_not_pass"])

    def test_alpaca_present_is_configured_not_pass(self) -> None:
        out = live_external_alpaca_status(credentials_present=True)
        self.assertEqual(out["LIVE_EXTERNAL_TEST"], "CONFIGURED")
        self.assertTrue(out["truth"]["credentials_present_is_not_measured_pass"])

    def test_env_credentials_probe_honest(self) -> None:
        # Without env secrets this environment cannot measure live Alpaca paper.
        key = (os.environ.get("LEVIATHAN_ALPACA_PAPER_KEY_ID") or "").strip()
        secret = (os.environ.get("LEVIATHAN_ALPACA_PAPER_SECRET") or "").strip()
        present = bool(key and secret)
        out = live_external_alpaca_status(credentials_present=present)
        if not present:
            self.assertEqual(out["LIVE_EXTERNAL_TEST"], "UNMEASURED")


if __name__ == "__main__":
    unittest.main()
