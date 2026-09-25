"""P4A — PaperForwardRunner + isolated paper accounting + canonical RiskGuard."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from Data.modules.market_sim.accounting import money
from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.paper_broker import LocalPaperBroker
from Data.modules.market_sim.paper_forward import PaperForwardRunner
from Data.modules.market_sim.risk_guard import RiskGuard, RiskLimits
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore


class P4APaperIsolationTests(unittest.TestCase):
    def test_per_session_wallets_isolated(self) -> None:
        b = LocalPaperBroker()
        self.assertTrue(hasattr(b, "wallet_for_session"))
        self.assertTrue(hasattr(b, "sessions"))
        w1 = b.wallet_for_session("s1", initial_cash=50_000)
        w2 = b.wallet_for_session("s2", initial_cash=80_000)
        self.assertEqual(float(w1.cash), 50_000)
        self.assertEqual(float(w2.cash), 80_000)
        w1.cash = money(10_000)
        self.assertEqual(float(b.wallet_for_session("s1").cash), 10_000)
        self.assertEqual(float(b.wallet_for_session("s2").cash), 80_000)
        # Shared default wallet untouched
        self.assertEqual(float(b.wallet.cash), 100_000)

    def test_risk_guard_blocks_paper_order(self) -> None:
        runner = PaperForwardRunner(
            risk=RiskGuard(RiskLimits(max_orders_per_day=0, kill_switch_armed=False))
        )
        b = LocalPaperBroker()
        wallet = b.wallet_for_session("sx", initial_cash=100_000)
        out = runner.step(wallet=wallet, symbol="BTC", price=100.0, side="BUY", qty=1.0)
        self.assertFalse(out["allowed"])
        self.assertIn("max orders", out["reason"].lower())

    def test_start_paper_session_isolates_cash(self) -> None:
        from Data.backend.tests.test_market_sim_characterization import FIXTURE

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = root / "markets"
            markets.mkdir()
            (markets / "BTCUSDT_1h.csv").write_bytes(FIXTURE.read_bytes())
            store = MarketSimStore(root / "lev.db")
            store.initialize()
            data = MarketDataStore(store, markets)
            plane = MarketSimControlPlane(store=store, data=data, enabled=True)
            # Mock provider quote so orders can proceed
            provider = MagicMock()
            provider.status.return_value = MagicMock(reachable=True, latency_ms=1)
            provider.fetch_quote.return_value = {"price": 100.0, "symbol": "BTCUSDT"}
            plane.providers = MagicMock()
            plane.providers.get.return_value = provider

            s1 = plane.start_paper_session(symbol="BTCUSDT", initial_cash=40_000)
            s2 = plane.start_paper_session(symbol="BTCUSDT", initial_cash=70_000)
            self.assertTrue(s1["metadata"]["isolated_wallet"])
            self.assertEqual(float(s1["wallet"]["cash"]), 40_000)
            self.assertEqual(float(s2["wallet"]["cash"]), 70_000)

            # Place an order on s1 — must not drain s2
            placed = plane.paper_place_order(s1["session_id"], side="BUY", qty=1.0)
            self.assertIn("risk", placed)
            self.assertTrue(placed["risk"]["allowed"])
            s1b = plane.paper_session_state(s1["session_id"])
            s2b = plane.paper_session_state(s2["session_id"])
            self.assertLess(float(s1b["wallet"]["cash"]), 40_000)
            self.assertEqual(float(s2b["wallet"]["cash"]), 70_000)

    def test_paper_forward_step_hold(self) -> None:
        from Data.backend.tests.test_market_sim_characterization import FIXTURE

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = root / "markets"
            markets.mkdir()
            (markets / "BTCUSDT_1h.csv").write_bytes(FIXTURE.read_bytes())
            store = MarketSimStore(root / "lev.db")
            store.initialize()
            data = MarketDataStore(store, markets)
            plane = MarketSimControlPlane(store=store, data=data, enabled=True)
            provider = MagicMock()
            provider.status.return_value = MagicMock(reachable=True, latency_ms=1)
            provider.fetch_quote.return_value = {"price": 100.0, "symbol": "BTCUSDT"}
            plane.providers = MagicMock()
            plane.providers.get.return_value = provider
            session = plane.start_paper_session(symbol="BTCUSDT")
            out = plane.paper_forward_step(session["session_id"], side="HOLD")
            self.assertEqual(out["result"]["action"], "hold")
            self.assertEqual(out["forward"]["steps"], 1)
            self.assertTrue(out["forward"]["truth"]["paper_only"])


if __name__ == "__main__":
    unittest.main()
