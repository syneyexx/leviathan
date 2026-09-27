"""G04 — Corporate actions applied through WalletLedger + engine path."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.market_sim.accounting import WalletLedger, money
from Data.modules.market_sim.engine import SimulationEngine
from Data.modules.market_sim.store import MarketSimStore, utc_now
from Data.modules.market_sim.types import SimRun, RunStatus


class CorporateActionLedgerTests(unittest.TestCase):
    def test_split_adjusts_qty_and_cost(self) -> None:
        w = WalletLedger(
            wallet_id="w1",
            owner_id="t",
            owner_kind="agent",
            cash=money(1000),
            primary_symbol="AAPL",
        )
        w.apply_buy(qty=10, price=100, fee=0, tx_id="b1", symbol="AAPL")
        out = w.apply_corporate_action(
            symbol="AAPL",
            kind="split",
            effective_at="2024-01-02T00:00:00Z",
            as_of="2024-01-02T00:00:00Z",
            factor=2.0,
            ca_id="split-2for1",
        )
        self.assertTrue(out["applied"])
        self.assertEqual(float(w.position_qty), 20.0)
        self.assertEqual(float(w.avg_entry), 50.0)
        w.assert_invariants(50)

    def test_dividend_credits_cash(self) -> None:
        w = WalletLedger(
            wallet_id="w1",
            owner_id="t",
            owner_kind="agent",
            cash=money(1000),
            primary_symbol="AAPL",
        )
        w.apply_buy(qty=10, price=100, fee=0, tx_id="b1", symbol="AAPL")
        cash_before = w.cash
        out = w.apply_corporate_action(
            symbol="AAPL",
            kind="dividend",
            effective_at="2024-01-02T00:00:00Z",
            as_of="2024-01-02T00:00:00Z",
            cash_amount=1.5,
            ca_id="div-1.5",
        )
        self.assertTrue(out["applied"])
        self.assertEqual(float(w.cash - cash_before), 15.0)
        self.assertEqual(float(w.position_qty), 10.0)

    def test_pit_before_effective_noop(self) -> None:
        w = WalletLedger(
            wallet_id="w1",
            owner_id="t",
            owner_kind="agent",
            cash=money(1000),
            primary_symbol="AAPL",
            position_qty=money(10),
            avg_entry=money(100),
        )
        out = w.apply_corporate_action(
            symbol="AAPL",
            kind="split",
            effective_at="2024-06-01T00:00:00Z",
            as_of="2024-01-01T00:00:00Z",
            factor=2.0,
            ca_id="future-split",
        )
        self.assertFalse(out["applied"])
        self.assertEqual(out["reason"], "before_effective_time")
        self.assertEqual(float(w.position_qty), 10.0)

    def test_engine_applies_split_during_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bars = root / "bars.csv"
            bars.write_text(
                "ts,open,high,low,close,volume\n"
                "2024-01-01T00:00:00Z,100,101,99,100,1000\n"
                "2024-01-02T00:00:00Z,50,51,49,50,2000\n"
                "2024-01-03T00:00:00Z,50,52,49,51,1500\n",
                encoding="utf-8",
            )
            db = root / "market.db"
            MigrationRunner(db).apply_all()
            store = MarketSimStore(db)
            now = utc_now()
            run = SimRun(
                run_id="run-ca-1",
                status=RunStatus.CREATED.value,
                source_id="src",
                strategy_id=None,
                strategy_version=None,
                symbol="AAPL",
                timeframe="1D",
                start_ts="2024-01-01T00:00:00Z",
                end_ts="2024-01-03T00:00:00Z",
                data_hash="",
                seed=1,
                fee_bps=0.0,
                slippage_bps=0.0,
                max_position_pct=100.0,
                max_drawdown_pct=50.0,
                per_trade_risk_pct=10.0,
                created_at=now,
                updated_at=now,
                metadata={
                    "corporate_actions": [
                        {
                            "symbol": "AAPL",
                            "kind": "split",
                            "effective_at": "2024-01-02T00:00:00Z",
                            "factor": 2.0,
                            "ca_id": "split-mid",
                        }
                    ]
                },
            )
            engine = SimulationEngine(store)
            store.create_run(run)
            state = engine.prepare(run, bars_path=str(bars), verify_data_hash=False)
            state.wallet.apply_buy(qty=10, price=100, fee=0, tx_id="seed-buy", symbol="AAPL")
            self.assertTrue(engine.step_once(state))
            self.assertTrue(engine.step_once(state))
            self.assertIn("split-mid", state.applied_ca_ids)
            self.assertEqual(float(state.wallet.position_qty), 20.0)
            self.assertEqual(float(state.wallet.avg_entry), 50.0)


if __name__ == "__main__":
    unittest.main()
