"""W18 — paper restart reuse + T09 feed reconnect without duplicate fills."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from Data.modules.market_sim.accounting import WalletLedger, money
from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.feed.runtime import FeedRuntime
from Data.modules.market_sim.feed.types import FeedConnectionState
from Data.modules.market_sim.market_event import MarketEvent, MarketEventType
from Data.modules.market_sim.paper_broker import (
    LocalPaperBroker,
    apply_paper_fill_from_feed_event,
    paper_fill_key_for_event,
)
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore


def _trade_event(event_id: str, *, seq: int = 1, price: float = 100.0) -> MarketEvent:
    return MarketEvent(
        event_id=event_id,
        provider_id="binance_public",
        connection_id="conn-a",
        symbol="BTCUSDT",
        event_type=MarketEventType.TRADE,
        price=price,
        size=1.0,
        sequence=seq,
        exchange_ts="2026-01-01T00:00:00+00:00",
    )


class FeedDuplicateT09Tests(unittest.TestCase):
    def test_reconnect_replay_drops_duplicate_event_and_fill(self) -> None:
        runtime = FeedRuntime()
        feed = runtime.create_subscription(
            provider_id="binance_public",
            symbols=["BTCUSDT"],
        )
        feed.set_status(FeedConnectionState.LIVE)
        event = _trade_event("evt-trade-1", seq=1)
        self.assertTrue(feed.ingest(event)["accepted"])

        broker = LocalPaperBroker(fee_bps=0, slippage_bps=0)
        wallet = broker.wallet_for_session("sess-1", initial_cash=10_000.0)
        o1 = apply_paper_fill_from_feed_event(
            broker,
            session_id="sess-1",
            event_id=event.event_id,
            symbol="BTCUSDT",
            side="BUY",
            qty=1,
            price=100.0,
        )
        self.assertEqual(o1.status, "filled")

        # Transport reconnect must preserve orderer seen_ids (T09).
        recon = feed.begin_reconnect(reason="ws_drop")
        self.assertEqual(recon["reconnect_count"], 1)
        self.assertTrue(recon["truth"]["seen_ids_preserved"])
        replay = feed.ingest(event)
        self.assertFalse(replay["accepted"])
        self.assertEqual(replay["disposition"], "DUPLICATE_DROPPED")

        # Even if a strategy re-fires on the same event_id, no second fill.
        o2 = apply_paper_fill_from_feed_event(
            broker,
            session_id="sess-1",
            event_id=event.event_id,
            symbol="BTCUSDT",
            side="BUY",
            qty=1,
            price=100.0,
        )
        self.assertEqual(o1.order_id, o2.order_id)
        self.assertEqual(len(wallet.transactions), 1)
        self.assertEqual(float(wallet.position_qty), 1.0)
        self.assertEqual(
            paper_fill_key_for_event(session_id="sess-1", event_id="evt-trade-1"),
            o1.client_order_id,
        )


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
            fill_key="fill:sess-r:evt-1",
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
            client_order_id="cid-different-after-restart",
            price_hint=50.0,
            session_id="sess-r",
            fill_key="fill:sess-r:evt-1",
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

    def test_saved_strategy_resumes_paper_sessions_after_restart(self) -> None:
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
            provider.fetch_quote.return_value = {"price": 40.0, "symbol": "AAPL"}
            plane.providers = MagicMock()
            plane.providers.get.return_value = provider

            # Persist a strategy-bound session without requiring full strategy registry.
            session = plane.start_paper_session(
                symbol="AAPL",
                broker_id="local_paper",
                initial_cash=8_000.0,
            )
            session["strategy_id"] = "strat-w18"
            session["strategy_version"] = 3
            store.upsert_paper_session(session)
            placed = plane.paper_place_order(
                session["session_id"],
                side="BUY",
                qty=1,
                client_order_id="cid-strat-1",
            )
            cash_after = money(placed["session"]["wallet"]["cash"])

            # Simulate process restart: new control plane, same durable DB.
            plane2 = MarketSimControlPlane(store=store, data=data, enabled=True)
            plane2.providers = MagicMock()
            plane2.providers.get.return_value = provider
            resumed = plane2.resume_paper_sessions_for_strategy("strat-w18", strategy_version=3)
            self.assertEqual(resumed["count"], 1)
            self.assertTrue(resumed["sessions"][0]["resumed"])
            self.assertEqual(money(resumed["sessions"][0]["wallet"]["cash"]), cash_after)
            self.assertEqual(
                resumed["truth"]["durable_path"], "market_paper_sessions"
            )
            self.assertEqual(
                resumed["truth"]["paper_deployment_table"], "NOT_PERSISTED"
            )


if __name__ == "__main__":
    unittest.main()
