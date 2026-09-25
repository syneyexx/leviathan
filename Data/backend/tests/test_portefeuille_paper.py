"""Paper Portefeuille — accounting, multi-asset, risk, autonomous, restart, rebalance."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from Data.modules.market_sim.accounting import money
from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.portefeuille.ledger import PortfolioBook
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.types import MarketSimError


def _plane(tmp: Path) -> MarketSimControlPlane:
    markets = tmp / "markets"
    markets.mkdir(exist_ok=True)
    store = MarketSimStore(tmp / "lev.db")
    store.initialize()
    data = MarketDataStore(store, markets)
    plane = MarketSimControlPlane(store=store, data=data, enabled=True)
    provider = MagicMock()
    provider.status.return_value = MagicMock(reachable=True, latency_ms=1)

    def _quote(symbol: str) -> dict:
        prices = {
            "BTCUSDT": 50_000.0,
            "BTC": 50_000.0,
            "ETHUSDT": 3_000.0,
            "ETH": 3_000.0,
            "AAPL": 180.0,
        }
        return {"price": prices.get(symbol.upper(), 100.0), "symbol": symbol}

    provider.fetch_quote.side_effect = _quote
    plane.providers = MagicMock()
    plane.providers.get.return_value = provider
    return plane


class PortfolioLedgerTests(unittest.TestCase):
    def test_buy_sell_fees_realized(self) -> None:
        book = PortfolioBook(portfolio_id="p1", cash=money(100_000))
        book.apply_fill(
            symbol="BTC", side="BUY", qty=1, price=100, fee=1, tx_id="t1", timestamp="t"
        )
        self.assertEqual(float(book.cash), 100_000 - 101)
        self.assertIn("BTC", book.positions)
        book.apply_fill(
            symbol="BTC", side="SELL", qty=1, price=110, fee=1, tx_id="t2", timestamp="t"
        )
        self.assertNotIn("BTC", book.positions)
        # pnl = (110-100)*1 - 1 fee on sell; buy fee already in cash
        self.assertGreater(float(book.realized_pnl), 0)
        marks = {"BTC": 110}
        self.assertAlmostEqual(float(book.equity(marks)), float(book.cash), places=4)

    def test_short_cover(self) -> None:
        book = PortfolioBook(portfolio_id="p1", cash=money(100_000), shorting_enabled=True)
        book.apply_fill(
            symbol="TSLA", side="SHORT", qty=10, price=100, fee=1, tx_id="s1", timestamp="t"
        )
        self.assertEqual(book.positions["TSLA"].side, "SHORT")
        # Mark up → unrealized loss
        up = book.unrealized_pnl({"TSLA": 110})
        self.assertLess(float(up), 0)
        book.apply_fill(
            symbol="TSLA", side="COVER", qty=10, price=90, fee=1, tx_id="s2", timestamp="t"
        )
        self.assertNotIn("TSLA", book.positions)
        self.assertGreater(float(book.realized_pnl), 0)

    def test_netting_sell_beyond_long_opens_short(self) -> None:
        book = PortfolioBook(portfolio_id="p1", cash=money(100_000), shorting_enabled=True)
        book.apply_fill(symbol="ETH", side="BUY", qty=1, price=100, fee=0, tx_id="a", timestamp="t")
        book.apply_fill(symbol="ETH", side="SELL", qty=1.5, price=100, fee=0, tx_id="b", timestamp="t")
        pos = book.positions["ETH"]
        self.assertEqual(pos.side, "SHORT")
        self.assertEqual(float(pos.qty), 0.5)

    def test_short_disabled_rejects(self) -> None:
        book = PortfolioBook(portfolio_id="p1", cash=money(100_000), shorting_enabled=False)
        with self.assertRaises(ValueError):
            book.apply_fill(symbol="ETH", side="SHORT", qty=1, price=100, fee=0, tx_id="x", timestamp="t")


class PortfolioServiceTests(unittest.TestCase):
    def test_create_and_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane = _plane(Path(tmp))
            pf = plane.create_portfolio(
                name="Alpha Paper",
                initial_equity=100_000,
                settings={"allow_manual_only": True, "fee_bps": 5, "slippage_bps": 2},
            )
            self.assertEqual(pf["mode"], "PAPER")
            self.assertTrue(pf["truth"]["paper_only"])
            self.assertFalse(pf["truth"]["real_money"])
            dash = plane.portfolio_dashboard(pf["portfolio_id"])
            self.assertEqual(float(dash["kpis"]["total_equity"]), 100_000)
            self.assertEqual(dash["portfolio"]["name"], "Alpha Paper")
            self.assertIn("insights", dash)

    def test_buy_updates_cash_position_tx_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane = _plane(Path(tmp))
            pf = plane.create_portfolio(
                name="Book",
                initial_equity=100_000,
                settings={"allow_manual_only": True, "cash_reserve_pct": 0, "fee_bps": 0, "slippage_bps": 0},
            )
            pid = pf["portfolio_id"]
            out = plane.portfolio_place_order(
                pid,
                symbol="BTCUSDT",
                side="BUY",
                qty=0.1,
                client_order_id="c1",
                agent_id="agent-a",
                strategy_id="strat-momo",
                strategy_version=1,
            )
            self.assertEqual(out["order"]["status"], "filled")
            self.assertIn("transaction", out)
            pf2 = plane.get_portfolio(pid)
            self.assertLess(float(pf2["cash"]), 100_000)
            dash = plane.portfolio_dashboard(pid)
            self.assertGreaterEqual(len(dash["positions"]), 1)
            self.assertEqual(dash["positions"][0]["agent_id"], "agent-a")
            self.assertEqual(dash["positions"][0]["strategy_id"], "strat-momo")
            self.assertGreaterEqual(len(dash["recent_transactions"]), 1)
            snaps = plane.store.list_portfolio_snapshots(pid)
            self.assertGreaterEqual(len(snaps), 2)

    def test_multi_asset_equity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane = _plane(Path(tmp))
            pf = plane.create_portfolio(
                name="Multi",
                initial_equity=100_000,
                settings={
                    "allow_manual_only": True,
                    "cash_reserve_pct": 0,
                    "fee_bps": 0,
                    "slippage_bps": 0,
                    "max_position_pct": 40,
                    "per_trade_risk_pct": 40,
                    "max_symbol_exposure_pct": 40,
                    "asset_concentration_pct": 40,
                },
            )
            pid = pf["portfolio_id"]
            for sym, qty, cid in (
                ("BTCUSDT", 0.1, "m1"),
                ("ETHUSDT", 1.0, "m2"),
                ("AAPL", 10, "m3"),
            ):
                out = plane.portfolio_place_order(pid, symbol=sym, side="BUY", qty=qty, client_order_id=cid)
                self.assertEqual(out["order"]["status"], "filled", out)
            dash = plane.portfolio_dashboard(pid)
            self.assertEqual(len(dash["positions"]), 3)
            eq = float(dash["kpis"]["total_equity"])
            self.assertGreater(eq, 90_000)
            self.assertLess(eq, 110_000)

    def test_agent_allocation_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane = _plane(Path(tmp))
            pf = plane.create_portfolio(
                name="Alloc",
                initial_equity=100_000,
                settings={
                    "allow_manual_only": True,
                    "cash_reserve_pct": 0,
                    "fee_bps": 0,
                    "slippage_bps": 0,
                    "agent_allocation_ceiling_pct": 100,
                },
                agent_allocations=[{"target_id": "agent-a", "target_allocation_pct": 5}],
            )
            pid = pf["portfolio_id"]
            # 5% of 100k = 5k; buying 0.2 BTC @ 50k = 10k → block
            out = plane.portfolio_place_order(
                pid,
                symbol="BTCUSDT",
                side="BUY",
                qty=0.2,
                client_order_id="alloc1",
                agent_id="agent-a",
            )
            self.assertEqual(out["order"]["status"], "blocked")
            self.assertIn("allocation", (out.get("code") or "").lower() + out["order"].get("reject_reason", "").lower())

    def test_risk_kill_switch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane = _plane(Path(tmp))
            pf = plane.create_portfolio(
                name="Kill",
                initial_equity=100_000,
                settings={"allow_manual_only": True, "cash_reserve_pct": 0},
            )
            pid = pf["portfolio_id"]
            plane.portfolio_kill_switch(pid, armed=True)
            out = plane.portfolio_place_order(
                pid, symbol="BTCUSDT", side="BUY", qty=0.01, client_order_id="k1"
            )
            self.assertEqual(out["order"]["status"], "blocked")

    def test_idempotent_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane = _plane(Path(tmp))
            pf = plane.create_portfolio(
                name="Idem",
                initial_equity=100_000,
                settings={"allow_manual_only": True, "cash_reserve_pct": 0, "fee_bps": 0, "slippage_bps": 0},
            )
            pid = pf["portfolio_id"]
            a = plane.portfolio_place_order(
                pid, symbol="BTCUSDT", side="BUY", qty=0.01, client_order_id="same"
            )
            b = plane.portfolio_place_order(
                pid, symbol="BTCUSDT", side="BUY", qty=0.01, client_order_id="same"
            )
            self.assertTrue(b.get("idempotent_replay"))
            txs = plane.store.list_portfolio_transactions(pid)
            self.assertEqual(len(txs), 1)
            self.assertEqual(a["order"]["order_id"], b["order"]["order_id"])

    def test_restart_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plane = _plane(root)
            pf = plane.create_portfolio(
                name="Persist",
                initial_equity=100_000,
                settings={"allow_manual_only": True, "cash_reserve_pct": 0, "fee_bps": 0, "slippage_bps": 0},
            )
            pid = pf["portfolio_id"]
            plane.portfolio_place_order(
                pid, symbol="BTCUSDT", side="BUY", qty=0.1, client_order_id="p1"
            )
            cash_before = float(plane.get_portfolio(pid)["cash"])
            # New plane / store reload
            plane2 = _plane(root)
            # Re-bind same db
            store = MarketSimStore(root / "lev.db")
            store.initialize()
            data = MarketDataStore(store, root / "markets")
            plane2 = MarketSimControlPlane(store=store, data=data, enabled=True)
            provider = MagicMock()
            provider.status.return_value = MagicMock(reachable=True, latency_ms=1)
            provider.fetch_quote.return_value = {"price": 50_000.0, "symbol": "BTCUSDT"}
            plane2.providers = MagicMock()
            plane2.providers.get.return_value = provider
            pf2 = plane2.get_portfolio(pid)
            self.assertAlmostEqual(float(pf2["cash"]), cash_before, places=4)
            dash = plane2.portfolio_dashboard(pid)
            self.assertGreaterEqual(len(dash["positions"]), 1)
            self.assertGreaterEqual(len(dash["recent_transactions"]), 1)

    def test_autonomous_buy_e2e(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane = _plane(Path(tmp))
            pf = plane.create_portfolio(
                name="Auto",
                initial_equity=100_000,
                orchestra_id="orch-1",
                settings={
                    "allow_manual_only": True,
                    "cash_reserve_pct": 0,
                    "fee_bps": 0,
                    "slippage_bps": 0,
                },
                strategy_allocations=[
                    {"target_id": "strat-1", "target_allocation_pct": 30, "strategy_version": 1}
                ],
                agent_allocations=[{"target_id": "agent-exec", "target_allocation_pct": 30}],
            )
            pid = pf["portfolio_id"]
            plane.start_portfolio(pid)
            decision = {
                "decision_id": "dec-1",
                "portfolio_id": pid,
                "orchestra_id": "orch-1",
                "agent_id": "agent-exec",
                "strategy_id": "strat-1",
                "strategy_version": 1,
                "symbol": "BTCUSDT",
                "action": "BUY",
                "requested_qty": 0.05,
                "client_order_id": "auto-dec-1",
            }
            out = plane.portfolio_tick(pid, decision=decision)
            self.assertTrue(out.get("executed"))
            dash = plane.portfolio_dashboard(pid)
            self.assertGreaterEqual(len(dash["positions"]), 1)
            self.assertLess(float(dash["kpis"]["cash_balance"]), 100_000)
            self.assertEqual(dash["positions"][0]["strategy_id"], "strat-1")
            self.assertEqual(dash["positions"][0]["agent_id"], "agent-exec")

    def test_autonomous_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane = _plane(Path(tmp))
            pf = plane.create_portfolio(
                name="Close",
                initial_equity=100_000,
                settings={"allow_manual_only": True, "cash_reserve_pct": 0, "fee_bps": 0, "slippage_bps": 0},
            )
            pid = pf["portfolio_id"]
            plane.portfolio_place_order(
                pid,
                symbol="BTCUSDT",
                side="BUY",
                qty=0.1,
                client_order_id="open1",
                strategy_id="s1",
                strategy_version=1,
                agent_id="a1",
            )
            pos = plane.portfolio_dashboard(pid)["positions"][0]
            # Price up via side_effect (return_value does not override side_effect)
            plane.providers.get.return_value.fetch_quote.side_effect = lambda s: {
                "price": 55_000.0,
                "symbol": s,
            }
            closed = plane.portfolio_close_position(pid, pos["position_id"])
            self.assertEqual(closed["order"]["status"], "filled")
            dash = plane.portfolio_dashboard(pid)
            self.assertEqual(len(dash["positions"]), 0)
            self.assertGreater(float(dash["kpis"]["realized_pnl"]), 0)

    def test_concurrent_agents_no_overspend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane = _plane(Path(tmp))
            pf = plane.create_portfolio(
                name="Race",
                initial_equity=10_000,
                settings={
                    "allow_manual_only": True,
                    "cash_reserve_pct": 0,
                    "fee_bps": 0,
                    "slippage_bps": 0,
                    "max_position_pct": 100,
                    "per_trade_risk_pct": 100,
                    "max_symbol_exposure_pct": 100,
                    "asset_concentration_pct": 100,
                    "max_gross_exposure_pct": 500,
                    "max_leverage": 5,
                    "agent_allocation_ceiling_pct": 100,
                    "strategy_allocation_ceiling_pct": 100,
                },
            )
            pid = pf["portfolio_id"]
            results: list[dict] = []

            def _buy(i: int) -> None:
                # Each tries to spend ~$6k — book only has $10k
                r = plane.portfolio_place_order(
                    pid,
                    symbol="BTCUSDT",
                    side="BUY",
                    qty=0.12,
                    client_order_id=f"race-{i}",
                    agent_id=f"agent-{i}",
                )
                results.append(r)

            threads = [threading.Thread(target=_buy, args=(i,)) for i in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            pf2 = plane.get_portfolio(pid)
            self.assertGreaterEqual(float(pf2["cash"]), -0.01)
            self.assertGreaterEqual(float(pf2["available_buying_power"]), -0.01)
            filled = [r for r in results if r.get("order", {}).get("status") == "filled"]
            blocked = [r for r in results if r.get("order", {}).get("status") == "blocked"]
            self.assertGreaterEqual(len(filled), 1)
            # Both cannot fully consume overlapping capital
            self.assertLessEqual(len(filled), 1)
            self.assertEqual(len(filled) + len(blocked), 2)

    def test_rebalance_preview_and_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane = _plane(Path(tmp))
            pf = plane.create_portfolio(
                name="Rebal",
                initial_equity=100_000,
                settings={
                    "allow_manual_only": True,
                    "cash_reserve_pct": 0,
                    "fee_bps": 0,
                    "slippage_bps": 0,
                    "asset_concentration_pct": 80,
                    "max_symbol_exposure_pct": 80,
                    "max_position_pct": 80,
                    "per_trade_risk_pct": 80,
                },
            )
            pid = pf["portfolio_id"]
            filled = plane.portfolio_place_order(
                pid, symbol="BTCUSDT", side="BUY", qty=1.0, client_order_id="conc"
            )
            self.assertEqual(filled["order"]["status"], "filled", filled)
            # Tighten concentration for recommendations
            plane.patch_portfolio(
                pid,
                {
                    "settings": {
                        "allow_manual_only": True,
                        "cash_reserve_pct": 0,
                        "fee_bps": 0,
                        "slippage_bps": 0,
                        "asset_concentration_pct": 5,
                        "max_symbol_exposure_pct": 5,
                        "max_position_pct": 25,
                        "per_trade_risk_pct": 25,
                    }
                },
            )
            dash = plane.portfolio_dashboard(pid)
            self.assertTrue(
                any(r["type"] == "REDUCE_CONCENTRATION" for r in dash["recommendations"]),
                dash["recommendations"],
            )
            preview = plane.portfolio_rebalance_preview(pid)
            self.assertTrue(preview["truth"]["preview_only"])
            self.assertAlmostEqual(
                float(plane.get_portfolio(pid)["equity"]),
                float(dash["kpis"]["total_equity"]),
                places=2,
            )

    def test_live_money_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane = _plane(Path(tmp))
            with self.assertRaises(MarketSimError) as ctx:
                plane.create_portfolio(name="Live", broker_mode="live_broker")
            self.assertEqual(ctx.exception.code, "LIVE_MONEY_BLOCKED")

    def test_settings_change_fees(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane = _plane(Path(tmp))
            pf = plane.create_portfolio(
                name="Fees",
                initial_equity=100_000,
                settings={"allow_manual_only": True, "cash_reserve_pct": 0, "fee_bps": 0, "slippage_bps": 0},
            )
            pid = pf["portfolio_id"]
            plane.portfolio_place_order(
                pid, symbol="BTCUSDT", side="BUY", qty=0.1, client_order_id="f0"
            )
            fees0 = float(plane.get_portfolio(pid)["fees_paid"])
            plane.patch_portfolio(pid, {"settings": {"fee_bps": 50, "slippage_bps": 0, "cash_reserve_pct": 0}})
            plane.portfolio_place_order(
                pid, symbol="ETHUSDT", side="BUY", qty=1.0, client_order_id="f1"
            )
            fees1 = float(plane.get_portfolio(pid)["fees_paid"])
            self.assertGreater(fees1, fees0)


if __name__ == "__main__":
    unittest.main()
