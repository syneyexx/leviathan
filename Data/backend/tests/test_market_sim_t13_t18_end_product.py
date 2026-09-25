"""Master Program T13–T18 — Shadow Live, lifecycle, training bridge, UI labels."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.backend.migrations import MIGRATIONS
from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.lifecycle import can_transition, compute_performance_drift
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.training_bridge import export_verified_trading_trajectories
from Data.modules.market_sim.types import MarketSimError


class _FakeProvider:
    provider_id = "fake"

    def status(self):
        from Data.modules.market_sim.providers import ProviderStatus

        return ProviderStatus(
            provider_id=self.provider_id,
            reachable=True,
            authenticated=True,
            latency_ms=42.0,
            detail="ok",
        )

    def fetch_quote(self, symbol: str):
        return {"symbol": symbol, "price": 100.0, "ts": "2024-01-01T00:00:00+00:00"}


class ShadowLiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        store = MarketSimStore(root / "db.sqlite")
        store.initialize()
        data = MarketDataStore(store, root / "markets")
        (root / "markets").mkdir()
        self.svc = MarketSimControlPlane(store, data, enabled=True)
        self.svc.providers.get = lambda _pid: _FakeProvider()  # type: ignore[method-assign]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_shadow_decide_does_not_submit_broker(self) -> None:
        session = self.svc.start_shadow_live(symbol="BTCUSDT")
        self.assertEqual(session["mode"], "SHADOW")
        self.assertTrue(session["truth"]["no_broker_order"])
        out = self.svc.shadow_live_decide(session["session_id"], side="BUY", qty=1)
        decision = out["decision"]
        self.assertFalse(decision["metadata"].get("broker_submitted"))
        self.assertTrue(decision["truth"]["no_broker_order"])
        self.assertEqual(decision["expected_execution_price"], 100.0)

    def test_shadow_outcome_and_restart_persist(self) -> None:
        session = self.svc.start_shadow_live(symbol="ETHUSDT")
        out = self.svc.shadow_live_decide(session["session_id"], side="SELL", qty=2)
        did = out["decision"]["decision_id"]
        attached = self.svc.shadow_live_attach_outcome(
            session["session_id"], did, realized_price=98.0
        )
        self.assertIn("shadow_pnl", attached["decision"]["realized_outcome"])
        # Reload via new runner instance (simulates restart).
        self.svc._shadow_live = None
        loaded = self.svc.get_shadow_live(session["session_id"])
        self.assertEqual(loaded["session_id"], session["session_id"])
        self.assertEqual(len(loaded["decisions"]), 1)


class LifecycleTests(unittest.TestCase):
    def test_degrade_from_active(self) -> None:
        self.assertTrue(can_transition("ACTIVE", "DEGRADED"))
        self.assertTrue(can_transition("DEGRADED", "REVIEW"))
        self.assertFalse(can_transition("ARCHIVED", "ACTIVE"))

    def test_drift_unmeasured_small_sample(self) -> None:
        d = compute_performance_drift(expected_returns=[0.1], actual_returns=[0.2])
        self.assertEqual(d["status"], "UNMEASURED")

    def test_service_promote_degrade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MarketSimStore(root / "db.sqlite")
            store.initialize()
            data = MarketDataStore(store, root / "markets")
            (root / "markets").mkdir()
            svc = MarketSimControlPlane(store, data, enabled=True)
            created = svc.create_strategy(name="deg-test", parameters={"fast_ma": 5})
            sid = created["strategy"]["strategy_id"]
            svc.promote_strategy(sid, to_status="RESEARCH")
            svc.promote_strategy(sid, to_status="CANDIDATE")
            svc.promote_strategy(sid, to_status="PAPER_READY")
            svc.promote_strategy(sid, to_status="ACTIVE")
            degraded = svc.promote_strategy(sid, to_status="DEGRADED", reason="drift")
            self.assertEqual(degraded["status"], "DEGRADED")


class TrainingBridgeTests(unittest.TestCase):
    def test_unverified_skipped_verified_exported(self) -> None:
        pending = {
            "decision_id": "d1",
            "session_id": "s1",
            "side": "BUY",
            "qty": 1,
            "symbol": "X",
            "expected_execution_price": 10,
            "truth": {"shadow_live": True, "no_broker_order": True},
        }
        measured = {
            **pending,
            "decision_id": "d2",
            "realized_outcome": {"shadow_pnl": 1.5},
            "outcome_attached_at": "t",
        }
        report = export_verified_trading_trajectories([pending, measured])
        self.assertEqual(report["admitted"], 1)
        self.assertEqual(report["skipped"], 1)
        self.assertTrue(report["truth"]["no_trading_trainer_2"])
        self.assertTrue(report["sft_lines"])


class LivePaperModeTests(unittest.TestCase):
    """T14 — paper sessions labeled LOCAL/BROKER PAPER; live money blocked."""

    def test_local_paper_execution_mode_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MarketSimStore(root / "db.sqlite")
            store.initialize()
            data = MarketDataStore(store, root / "markets")
            (root / "markets").mkdir()
            svc = MarketSimControlPlane(store, data, enabled=True)
            svc.providers.get = lambda _pid: _FakeProvider()  # type: ignore[method-assign]
            session = svc.start_paper_session(symbol="BTCUSDT", broker_id="local_paper")
            self.assertEqual(session["execution_mode"], "LOCAL PAPER")
            self.assertTrue(session["metadata"]["truth"]["live_money_blocked"])
            self.assertTrue(session["metadata"]["truth"]["not_live_money"])


class PaperUiModeLabelTests(unittest.TestCase):
    def test_paper_page_labels_shadow_local_broker(self) -> None:
        page = (
            Path(__file__).resolve().parents[2]
            / "frontend"
            / "src"
            / "pages"
            / "trading"
            / "PaperTradingPage.tsx"
        )
        text = page.read_text(encoding="utf-8")
        self.assertIn("SHADOW", text)
        self.assertIn("LOCAL PAPER", text)
        self.assertIn("BROKER PAPER", text)
        self.assertIn("BLOCKED", text)
        self.assertIn("startShadowLive", text)
        self.assertIn("exportTradingTrainingBridge", text)
        self.assertIn("Shadow Live", text)


class Migration50Tests(unittest.TestCase):
    def test_migration_50_present(self) -> None:
        self.assertGreaterEqual(MIGRATIONS[-1].version, 50)
        by_ver = {m.version: m.name for m in MIGRATIONS}
        self.assertEqual(by_ver[50], "trading_shadow_lifecycle")


if __name__ == "__main__":
    unittest.main()
