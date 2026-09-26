"""W18 — paper restart reuse + T09 feed reconnect without duplicate fills."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from Data.modules.market_sim.accounting import WalletLedger, money
from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.feed.ordering import EventOrderer
from Data.modules.market_sim.feed.types import OrderingDisposition
from Data.modules.market_sim.market_event import MarketEvent, MarketEventType
from Data.modules.market_sim.feed.runtime import FeedSession
from Data.modules.market_sim.feed.types import FeedSubscription
from Data.modules.market_sim.paper_broker import (
    LocalPaperBroker,
    apply_paper_fill_from_feed_event,
)
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore


class FeedDuplicateT09Tests(unittest.TestCase):
    def test_feed_event_fill_key_idempotent_across_reconnect(self) -> None:
        broker = LocalPaperBroker(fee_bps=0, slippage_bps=0)
        broker.wallet_for_session("sess-feed", initial_cash=10_000.0)
        first = apply_paper_fill_from_feed_event(
            broker,
            session_id="sess-feed",
            event_id="evt-42",
            symbol="BTCUSDT",
            side="BUY",
            qty=1,
            price=100.0,
        )
        second = apply_paper_fill_from_feed_event(
            broker,
            session_id="sess-feed",
            event_id="evt-42",
            symbol="BTCUSDT",
            side="BUY",
            qty=1,
            price=100.0,
        )
        self.assertEqual(first.order_id, second.order_id)
        self.assertEqual(len(broker.wallet_for_session("sess-feed").transactions), 1)

        sub = FeedSubscription(
            feed_id="f1",
            provider_id="binance_public",
            connection_id="conn-old",
            symbols=["BTCUSDT"],
        )
        session = FeedSession(sub=sub)
        event = MarketEvent(
            event_id="evt-42",
            provider_id="binance_public",
            connection_id="conn-old",
            symbol="BTCUSDT",
            event_type=MarketEventType.TRADE,
            price=100.0,
            size=1.0,
            sequence=1,
        )
        self.assertTrue(session.ingest(event).get("accepted"))
        recon = session.begin_reconnect(reason="socket_drop")
        self.assertTrue(recon["truth"]["seen_ids_preserved"])
        replay = session.ingest(event)
        self.assertFalse(replay.get("accepted"))
        self.assertEqual(replay.get("disposition"), OrderingDisposition.DUPLICATE_DROPPED.value)

    def test_reconnect_replay_drops_duplicate_event_and_fill(self) -> None:
        orderer = EventOrderer()
        event = MarketEvent(
            event_id="evt-trade-1",
            provider_id="binance_public",
            connection_id="conn-a",
            symbol="BTCUSDT",
            event_type=MarketEventType.TRADE,
            price=100.0,
            size=1.0,
            sequence=1,
            exchange_ts="2026-01-01T00:00:00+00:00",
        )
        first = orderer.accept(event)
        self.assertNotEqual(first.disposition, OrderingDisposition.DUPLICATE_DROPPED)
        second = orderer.accept(event)
        self.assertEqual(second.disposition, OrderingDisposition.DUPLICATE_DROPPED)

        broker = LocalPaperBroker(fee_bps=0, slippage_bps=0)
        wallet = broker.wallet_for_session("sess-1", initial_cash=10_000.0)
        o1 = broker.place(
            symbol="BTCUSDT",
            side="BUY",
            qty=1,
            client_order_id="cid-reconnect-1",
            price_hint=100.0,
            session_id="sess-1",
        )
        o2 = broker.place(
            symbol="BTCUSDT",
            side="BUY",
            qty=1,
            client_order_id="cid-reconnect-1",
            price_hint=100.0,
            session_id="sess-1",
        )
        self.assertEqual(o1.order_id, o2.order_id)
        self.assertEqual(o1.status, "filled")
        self.assertEqual(len(wallet.transactions), 1)
        self.assertEqual(float(wallet.position_qty), 1.0)


class PaperRestartReuseTests(unittest.TestCase):
    def test_wallet_ledger_roundtrip(self) -> None:
        wal = WalletLedger(
            wallet_id="wal-1",
            owner_id="sess",
            owner_kind="paper_session",
            cash=money(9_000),
            position_qty=money(1),
            avg_entry=money(100),
            primary_symbol="AAPL",
        )
        wal.transactions.append({"tx_id": "t1", "side": "BUY", "qty": "1", "fee": "0"})
        restored = WalletLedger.from_public_dict(wal.public_dict())
        self.assertEqual(restored.cash, money(9_000))
        self.assertEqual(restored.position_qty, money(1))
        self.assertEqual(restored.transactions[0]["tx_id"], "t1")

    def test_broker_restore_preserves_position_and_idempotency(self) -> None:
        broker = LocalPaperBroker(fee_bps=0, slippage_bps=0)
        wal = broker.wallet_for_session("sess-r", initial_cash=10_000.0)
        order = broker.place(
            symbol="AAPL",
            side="BUY",
            qty=2,
            client_order_id="cid-persist-1",
            price_hint=50.0,
            session_id="sess-r",
        )
        payload = wal.public_dict()
        orders = [order.public_dict()]

        broker2 = LocalPaperBroker(fee_bps=0, slippage_bps=0)
        restored = broker2.restore_session(
            "sess-r", wallet_payload=payload, orders=orders
        )
        self.assertEqual(restored.position_qty, money(2))
        self.assertEqual(money(restored.cash), money(payload["cash"]))
        again = broker2.place(
            symbol="AAPL",
            side="BUY",
            qty=2,
            client_order_id="cid-persist-1",
            price_hint=50.0,
            session_id="sess-r",
        )
        self.assertEqual(again.order_id, order.order_id)
        self.assertEqual(len(restored.transactions), 1)

    def test_control_plane_hydrates_paper_session_after_broker_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = root / "markets"
            markets.mkdir()
            store = MarketSimStore(root / "lev.db")
            store.initialize()
            data = MarketDataStore(store, markets)
            plane = MarketSimControlPlane(store=store, data=data, enabled=True)
            provider = MagicMock()
            provider.status.return_value = MagicMock(reachable=True, latency_ms=1.0)
            provider.fetch_quote.return_value = {"price": 25.0, "symbol": "AAPL"}
            plane.providers = MagicMock()
            plane.providers.get.return_value = provider

            session = plane.start_paper_session(
                symbol="AAPL",
                broker_id="local_paper",
                initial_cash=5_000.0,
            )
            placed = plane.paper_place_order(
                session["session_id"],
                side="BUY",
                qty=1,
                client_order_id="cid-svc-1",
            )
            self.assertEqual(placed["order"]["status"], "filled")
            sid = session["session_id"]
            cash_after = money(placed["session"]["wallet"]["cash"])

            plane._paper_brokers.clear()
            revived = plane.paper_session_state(sid)
            wallet = revived["wallet"]
            self.assertEqual(money(wallet["cash"]), cash_after)
            self.assertEqual(money(wallet["position_qty"]), money(1))

            again = plane.paper_place_order(
                sid, side="BUY", qty=1, client_order_id="cid-svc-1"
            )
            self.assertEqual(again["order"]["order_id"], placed["order"]["order_id"])
            self.assertEqual(money(again["session"]["wallet"]["cash"]), cash_after)


if __name__ == "__main__":
    unittest.main()
