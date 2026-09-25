"""T9 — PaperForwardRunner, Risk Engine v2, brokers/reconcile, audit ledger."""

from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.backend.migrations import MIGRATIONS
from Data.modules.market_sim.audit_ledger import append_audit_event, verify_audit_chain
from Data.modules.market_sim.brokers import LiveBroker, ReplayBroker, build_broker
from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.paper_broker import LocalPaperBroker
from Data.modules.market_sim.reconciliation import (
    data_quality_watchdog,
    drift_vs_backtest,
    reconcile_shadow_ledger,
)
from Data.modules.market_sim.risk_engine_v2 import RiskEngineV2
from Data.modules.market_sim.risk_guard import RiskLimits
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore, utc_now
from Data.modules.market_sim.types import MarketSimError
from Data.modules.trading.stub import TradingStub


class _FakeProvider:
    provider_id = "fake"

    def status(self):
        from Data.modules.market_sim.providers import ProviderStatus

        return ProviderStatus(
            provider_id=self.provider_id,
            reachable=True,
            authenticated=True,
            latency_ms=12.0,
            detail="ok",
        )

    def fetch_quote(self, symbol: str):
        return {"symbol": symbol, "price": 100.0, "ts": utc_now()}


class PaperSessionWalletTests(unittest.TestCase):
    def test_per_session_wallets_isolated(self) -> None:
        b = LocalPaperBroker()
        self.assertTrue(hasattr(b, "wallet_for_session"))
        self.assertTrue(hasattr(b, "sessions"))
        w1 = b.wallet_for_session("s1", initial_cash=50_000)
        w2 = b.wallet_for_session("s2", initial_cash=75_000)
        self.assertNotEqual(w1.wallet_id, w2.wallet_id)
        self.assertEqual(float(w1.cash), 50_000.0)
        self.assertEqual(float(w2.cash), 75_000.0)
        # Mutating one session must not affect the other.
        from Data.modules.market_sim.accounting import money

        w1.cash = money(1_000)
        self.assertEqual(float(b.wallet_for_session("s2").cash), 75_000.0)

    def test_start_session_uses_per_session_wallet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MarketSimStore(root / "db.sqlite")
            store.initialize()
            data = MarketDataStore(store, root / "markets")
            (root / "markets").mkdir()
            svc = MarketSimControlPlane(store, data, enabled=True)
            svc.providers.get = lambda _pid: _FakeProvider()  # type: ignore[method-assign]
            s1 = svc.start_paper_session(symbol="BTCUSDT", initial_cash=10_000)
            s2 = svc.start_paper_session(symbol="ETHUSDT", initial_cash=20_000)
            broker = svc._paper_broker("local_paper")
            self.assertIn(s1["session_id"], broker.sessions)
            self.assertIn(s2["session_id"], broker.sessions)
            self.assertNotEqual(
                float(broker.sessions[s1["session_id"]].cash),
                float(broker.sessions[s2["session_id"]].cash),
            )


class PaperForwardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        store = MarketSimStore(root / "db.sqlite")
        store.initialize()
        data = MarketDataStore(store, root / "markets")
        (root / "markets").mkdir()
        self.svc = MarketSimControlPlane(store, data, enabled=True)
        self.svc.providers.get = lambda _pid: _FakeProvider()  # type: ignore[method-assign]
        self.session = self.svc.start_paper_session(symbol="BTCUSDT", initial_cash=100_000)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_runner_tick_idempotent_client_order_ids(self) -> None:
        runner = self.svc.start_paper_forward(self.session["session_id"])
        rid = runner["runner_id"]
        first = self.svc.paper_forward_tick(rid, side="BUY")
        coid = first["client_order_id"]
        # Replay same loop index via stored checkpoint would use next index;
        # placing with same coid through broker must be idempotent.
        broker = self.svc._paper_broker("local_paper")
        again = broker.place(
            symbol="BTCUSDT",
            side="BUY",
            qty=1.0,
            client_order_id=coid,
            price_hint=100.0,
            session_id=self.session["session_id"],
        )
        self.assertEqual(again.client_order_id, coid)
        paused = self.svc.paper_forward_pause(rid)
        self.assertEqual(paused["status"], "paused")
        resumed = self.svc.paper_forward_resume(rid)
        self.assertEqual(resumed["status"], "running")
        self.assertGreaterEqual(resumed["checkpoint"]["loops_done"], 1)

    def test_readonly_get_has_no_write_side_effect_in_source(self) -> None:
        src = inspect.getsource(MarketSimControlPlane.get_paper_session_readonly)
        self.assertNotIn("upsert_paper_session", src)
        self.assertNotIn("fetch_quote", src)


class RiskEngineV2Tests(unittest.TestCase):
    def test_every_order_path_uses_risk_engine(self) -> None:
        src = inspect.getsource(MarketSimControlPlane.paper_place_order)
        self.assertIn("risk_engine", src)
        self.assertIn("evaluate_order", src)

    def test_kill_switch_human_reset(self) -> None:
        eng = RiskEngineV2(RiskLimits(max_drawdown_pct=5.0))
        eng.arm_global_kill("test", now=utc_now())
        self.assertTrue(eng.kill.global_armed)
        with self.assertRaises(MarketSimError):
            eng.human_reset_kill(now=utc_now(), human_token=None)
        reset = eng.human_reset_kill(now=utc_now(), human_token="operator-1")
        self.assertFalse(reset.global_armed)

    def test_loosen_requires_approval(self) -> None:
        eng = RiskEngineV2()
        with self.assertRaises(MarketSimError) as ctx:
            eng.loosen_limits({"max_position_pct": 90.0}, approval_id=None, now=utc_now())
        self.assertEqual(ctx.exception.code, "APPROVAL_REQUIRED")

    def test_service_rejects_via_risk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MarketSimStore(root / "db.sqlite")
            store.initialize()
            data = MarketDataStore(store, root / "markets")
            (root / "markets").mkdir()
            svc = MarketSimControlPlane(store, data, enabled=True)
            svc.providers.get = lambda _pid: _FakeProvider()  # type: ignore[method-assign]
            session = svc.start_paper_session(symbol="BTCUSDT")
            svc.risk_engine.arm_global_kill("halt", now=utc_now())
            with self.assertRaises(MarketSimError) as ctx:
                svc.paper_place_order(session["session_id"], side="BUY", qty=1)
            self.assertIn(ctx.exception.code, {"KILL_SWITCH", "RISK_REJECTED"})


class BrokerAdapterTests(unittest.TestCase):
    def test_live_broker_unsupported(self) -> None:
        live = LiveBroker()
        with self.assertRaises(MarketSimError) as ctx:
            live.place(symbol="AAPL", side="BUY", qty=1, client_order_id="x")
        self.assertEqual(ctx.exception.code, "UNSUPPORTED")
        self.assertEqual(live.account()["status"], "UNSUPPORTED")
        built = build_broker("live")
        self.assertIsInstance(built, LiveBroker)

    def test_replay_broker_deterministic(self) -> None:
        quotes = [{"price": 10.0}, {"price": 11.0}]
        a = ReplayBroker(quotes=list(quotes), fee_bps=0, slippage_bps=0)
        b = ReplayBroker(quotes=list(quotes), fee_bps=0, slippage_bps=0)
        oa = a.place(symbol="X", side="BUY", qty=1, client_order_id="c1", session_id="s")
        ob = b.place(symbol="X", side="BUY", qty=1, client_order_id="c1", session_id="s")
        self.assertEqual(oa.fill_price, ob.fill_price)
        # Idempotent
        again = a.place(symbol="X", side="BUY", qty=1, client_order_id="c1", session_id="s")
        self.assertEqual(again.order_id, oa.order_id)


class ReconciliationTests(unittest.TestCase):
    def test_shadow_reconcile_and_drift(self) -> None:
        report = reconcile_shadow_ledger(
            primary_fills=[
                {"client_order_id": "1", "side": "BUY", "qty": 1, "fill_price": 10},
                {"client_order_id": "2", "side": "SELL", "qty": 1, "fill_price": 11},
            ],
            shadow_fills=[
                {"client_order_id": "1", "side": "BUY", "qty": 1, "fill_price": 10.1},
            ],
            created_at=utc_now(),
        )
        self.assertEqual(report["matched"], 1)
        self.assertEqual(report["missing_in_shadow"], 1)
        drift = drift_vs_backtest(
            paper_equity=[100, 101, 102],
            backtest_equity=[100, 100.5, 101],
            band_pct=5.0,
            created_at=utc_now(),
        )
        self.assertTrue(drift["within_band"])
        wd = data_quality_watchdog(feed_status="disconnected", feed_latency_ms=100)
        self.assertEqual(wd["action"], "pause")


class AuditLedgerTests(unittest.TestCase):
    def test_hash_chain_detects_tamper(self) -> None:
        events: list[dict] = []
        append_audit_event(
            events, kind="intent", payload={"side": "BUY"}, created_at=utc_now(), session_id="s"
        )
        append_audit_event(
            events, kind="risk_decision", payload={"allowed": True}, created_at=utc_now(), session_id="s"
        )
        append_audit_event(
            events, kind="broker_call", payload={"ok": True}, created_at=utc_now(), session_id="s"
        )
        append_audit_event(
            events, kind="fill", payload={"status": "filled"}, created_at=utc_now(), session_id="s"
        )
        append_audit_event(
            events, kind="reconciliation", payload={"matched": 1}, created_at=utc_now(), session_id="s"
        )
        ok = verify_audit_chain(events)
        self.assertTrue(ok["ok"])
        events[2]["payload"]["ok"] = False  # tamper
        bad = verify_audit_chain(events)
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["reason"], "entry_hash_mismatch")

    def test_service_order_writes_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MarketSimStore(root / "db.sqlite")
            store.initialize()
            data = MarketDataStore(store, root / "markets")
            (root / "markets").mkdir()
            svc = MarketSimControlPlane(store, data, enabled=True)
            svc.providers.get = lambda _pid: _FakeProvider()  # type: ignore[method-assign]
            session = svc.start_paper_session(symbol="BTCUSDT")
            svc.paper_place_order(session["session_id"], side="BUY", qty=1, client_order_id="aud-1")
            kinds = [e["kind"] for e in svc._audit_events]
            self.assertIn("intent", kinds)
            self.assertIn("risk_decision", kinds)
            self.assertIn("broker_call", kinds)
            self.assertIn("fill", kinds)
            verified = svc.verify_trading_audit()
            self.assertTrue(verified["ok"])


class SecurityPostureTests(unittest.TestCase):
    def test_live_flag_off_and_stub_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MarketSimStore(root / "db.sqlite")
            store.initialize()
            data = MarketDataStore(store, root / "markets")
            (root / "markets").mkdir()
            svc = MarketSimControlPlane(store, data, enabled=True)
            with mock.patch.dict("os.environ", {"LEVIATHAN_FEATURE_TRADING_LIVE": ""}, clear=False):
                posture = svc.security_posture()
            self.assertFalse(posture["live_feature_enabled"])
            self.assertEqual(posture["live_trading_available"], "BLOCKED")
            self.assertTrue(posture["trading_stub_refuses"])
            self.assertEqual(posture["live_broker"], "UNSUPPORTED")
            stub = TradingStub().place_order(symbol="X", side="BUY", quantity=1)
            self.assertFalse(stub.accepted)


class Migration49Tests(unittest.TestCase):
    def test_migration_49_present(self) -> None:
        self.assertGreaterEqual(MIGRATIONS[-1].version, 49)
        by_ver = {m.version: m.name for m in MIGRATIONS}
        self.assertEqual(by_ver[49], "trading_paper_risk_audit")


class T9CapabilityTests(unittest.TestCase):
    def test_t9_capabilities_registered(self) -> None:
        from Data.modules.execution.builtins import build_default_catalog

        catalog = build_default_catalog()
        for needed in (
            "market_sim.paper.forward.start",
            "market_sim.paper.forward.tick",
            "market_sim.paper.forward.pause",
            "market_sim.paper.forward.resume",
            "market_sim.paper.reconcile",
            "market_sim.paper.drift",
            "market_sim.risk.reset",
            "market_sim.risk.loosen",
        ):
            self.assertIsNotNone(catalog.get(needed), needed)


if __name__ == "__main__":
    unittest.main()
