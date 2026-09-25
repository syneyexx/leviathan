"""P0A — kernel honesty: fills, ClosedTrade foundation, annualization, metric keys.

Slice 1 of Master Program v4.1. Does not claim full P0 (G08–G11) complete.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.market_sim.experiments import evaluate_acceptance
from Data.modules.market_sim.instruments import InstrumentFamily, spec_for_symbol
from Data.modules.market_sim.metrics import compute_metrics, resolve_periods_per_year
from Data.modules.market_sim.position_episodes import PositionEpisodeTracker
from Data.modules.market_sim.store import MarketSimStore, utc_now
from Data.modules.market_sim.types import (
    MetricStatus,
    OrderType,
    SimFill,
    WinRateDefinition,
)


class AnnualizationResolverTests(unittest.TestCase):
    def test_crypto_1h_differs_from_equity_1h(self) -> None:
        crypto = resolve_periods_per_year(
            timeframe="1h",
            instrument_family=InstrumentFamily.CRYPTO_SPOT,
        )
        equity = resolve_periods_per_year(
            timeframe="1h",
            instrument_family=InstrumentFamily.EQUITY,
        )
        self.assertEqual(crypto["status"], MetricStatus.MEASURED.value)
        self.assertEqual(equity["status"], MetricStatus.MEASURED.value)
        self.assertEqual(crypto["annualization_source"], "asset_family_default")
        self.assertEqual(equity["annualization_source"], "asset_family_default")
        self.assertAlmostEqual(float(crypto["value"]), 365.0 * 24.0)
        self.assertAlmostEqual(float(equity["value"]), 252.0 * 6.5)
        self.assertNotAlmostEqual(float(crypto["value"]), float(equity["value"]))

    def test_explicit_instrument_calendar_wins(self) -> None:
        spec = spec_for_symbol(
            "BTCUSDT",
            timeframe="1h",
            metadata={"family": "crypto_spot", "periods_per_year": 1234.0},
        )
        resolved = resolve_periods_per_year(timeframe="1h", instrument_spec=spec)
        self.assertEqual(resolved["annualization_source"], "instrument_calendar")
        self.assertAlmostEqual(float(resolved["value"]), 1234.0)

    def test_unresolved_without_timeframe_or_family(self) -> None:
        resolved = resolve_periods_per_year(timeframe="weird_tf", instrument_family=None)
        self.assertEqual(resolved["status"], MetricStatus.UNMEASURED.value)
        self.assertIsNone(resolved["value"])

    def test_sharpe_unmeasured_when_annualization_unresolved(self) -> None:
        m = compute_metrics(
            equity=[100.0, 101.0, 102.0, 101.5],
            fills=[],
            initial_cash=100.0,
            periods_per_year=None,
            annualization={
                "status": MetricStatus.UNMEASURED.value,
                "value": None,
                "annualization_source": "unresolved",
            },
        )
        self.assertEqual(m["sharpe"]["status"], MetricStatus.UNMEASURED.value)
        self.assertEqual(m["sortino"]["status"], MetricStatus.UNMEASURED.value)


class SimFillHonestyTests(unittest.TestCase):
    def test_realized_delta_in_public_dict_when_measured(self) -> None:
        fill = SimFill(
            fill_id="f1",
            run_id="r",
            bar_index=2,
            ts="2024-01-01T00:00:00+00:00",
            side="SELL",
            qty=1.0,
            price=110.0,
            fee=0.1,
            slippage=0.02,
            agent_id="a",
            rationale="exit",
            status="FILLED",
            created_at=utc_now(),
            realized_delta=9.9,
            remaining_qty=0.0,
            order_type=OrderType.MARKET.value,
            fill_price_source="next_bar_open",
            observed_execution=False,
            decision_bar_index=1,
            intent_id="intent-1",
            trade_id="trade-1",
        )
        payload = fill.public_dict()
        self.assertEqual(payload["realized_delta"], 9.9)
        self.assertEqual(payload["remaining_qty"], 0.0)
        self.assertEqual(payload["order_type"], "MARKET")
        self.assertEqual(payload["fill_price_source"], "next_bar_open")
        self.assertFalse(payload["observed_execution"])
        self.assertEqual(payload["decision_bar_index"], 1)
        self.assertEqual(payload["intent_id"], "intent-1")
        self.assertEqual(payload["trade_id"], "trade-1")

    def test_unmeasured_realized_delta_omitted_from_public_dict(self) -> None:
        fill = SimFill(
            fill_id="f2",
            run_id="r",
            bar_index=1,
            ts="t",
            side="BUY",
            qty=1.0,
            price=100.0,
            fee=0.1,
            slippage=0.0,
            agent_id="a",
            rationale="",
            status="FILLED",
            created_at=utc_now(),
        )
        payload = fill.public_dict()
        self.assertNotIn("realized_delta", payload)
        self.assertNotIn("trade_id", payload)
        self.assertFalse(payload["observed_execution"])


class ClosedTradeWinRateTests(unittest.TestCase):
    def test_position_episode_round_trip(self) -> None:
        tracker = PositionEpisodeTracker(run_id="r1", instrument="BTCUSDT")
        self.assertIsNone(
            tracker.on_fill(
                side="BUY",
                qty=2.0,
                price=100.0,
                fee=1.0,
                slippage=0.5,
                ts="t0",
                bar_index=0,
            )
        )
        closed = tracker.on_fill(
            side="SELL",
            qty=2.0,
            price=110.0,
            fee=1.0,
            slippage=0.5,
            ts="t1",
            bar_index=5,
            close_reason="signal",
        )
        self.assertIsNotNone(closed)
        assert closed is not None
        self.assertEqual(closed.side, "LONG")
        self.assertAlmostEqual(closed.gross_pnl, 20.0)
        self.assertAlmostEqual(closed.net_pnl, 18.0)
        self.assertEqual(closed.holding_period_bars, 5)
        self.assertEqual(len(tracker.closed), 1)

    def test_closed_trade_win_rate_preferred_over_fill_delta(self) -> None:
        closed = [
            {
                "trade_id": "t1",
                "net_pnl": 10.0,
            },
            {
                "trade_id": "t2",
                "net_pnl": -5.0,
            },
            {
                "trade_id": "t3",
                "net_pnl": 2.0,
            },
        ]
        # Misleading fill-level deltas must not override closed-trade definition.
        fills = [
            {"side": "SELL", "qty": 1, "price": 1, "fee": 0, "realized_delta": -100.0},
        ]
        m = compute_metrics(
            equity=[100.0, 110.0],
            fills=fills,
            initial_cash=100.0,
            closed_trades=closed,
        )
        self.assertEqual(m["win_rate"]["definition"], WinRateDefinition.CLOSED_POSITION_EPISODE.value)
        self.assertEqual(m["win_rate"]["status"], MetricStatus.MEASURED.value)
        self.assertAlmostEqual(float(m["win_rate"]["value"]), 2.0 / 3.0)
        self.assertEqual(
            m["closed_trade_win_rate"]["definition"],
            WinRateDefinition.CLOSED_POSITION_EPISODE.value,
        )

    def test_fill_level_win_rate_is_explicitly_labeled(self) -> None:
        fills = [
            {"side": "SELL", "qty": 1, "price": 110, "fee": 0, "realized_delta": 10.0},
            {"side": "SELL", "qty": 1, "price": 90, "fee": 0, "realized_delta": -5.0},
        ]
        m = compute_metrics(equity=[100.0, 105.0], fills=fills, initial_cash=100.0)
        self.assertEqual(
            m["win_rate"]["definition"],
            WinRateDefinition.FILL_LEVEL_REALIZED_DELTA.value,
        )
        self.assertEqual(
            m["closed_trade_win_rate"]["status"],
            MetricStatus.UNMEASURED.value,
        )
        self.assertAlmostEqual(float(m["win_rate"]["value"]), 0.5)


class MetricKeyAlignmentTests(unittest.TestCase):
    def test_acceptance_reads_compute_metrics_shape(self) -> None:
        equity = [100.0, 110.0, 120.0]
        fills = [
            {"side": "BUY", "qty": 1, "price": 100, "fee": 0},
            {"side": "SELL", "qty": 1, "price": 120, "fee": 0, "realized_delta": 20},
        ]
        m = compute_metrics(equity=equity, fills=fills, initial_cash=100.0)
        self.assertIn("total_return", m)
        self.assertIn("total_return_pct", m)
        self.assertIn("trade_count", m)
        self.assertIn("max_drawdown_pct", m)
        passed, reason = evaluate_acceptance(
            m,
            {"min_trades": 1, "max_drawdown_pct": 50.0, "min_total_return_pct": 0.0},
        )
        self.assertTrue(passed, reason)

    def test_trade_count_from_closed_trades(self) -> None:
        m = compute_metrics(
            equity=[100.0, 110.0],
            fills=[{"side": "BUY", "qty": 1, "price": 100, "fee": 0}],
            initial_cash=100.0,
            closed_trades=[{"net_pnl": 5.0}, {"net_pnl": -1.0}],
        )
        self.assertEqual(m["trade_count"]["value"], 2)
        self.assertEqual(m["trade_count"]["definition"], "closed_position_episodes")


class StorePersistenceTests(unittest.TestCase):
    def test_fill_and_closed_trade_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "t.db"
            from Data.backend.migrations import MigrationRunner

            MigrationRunner(db).apply_all()
            store = MarketSimStore(db)
            now = utc_now()
            with store.connect() as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO market_sim_runs(
                        run_id, status, source_id, symbol, timeframe,
                        start_ts, end_ts, data_hash, seed, created_at, updated_at
                    ) VALUES (?, 'COMPLETED', 'src', 'BTCUSDT', '1h',
                              't0', 't1', 'abc', 1, ?, ?)
                    """,
                    ("run-p0a", now, now),
                )

            fill = SimFill(
                fill_id="fill-p0a",
                run_id="run-p0a",
                bar_index=3,
                ts="2024-01-01T03:00:00+00:00",
                side="SELL",
                qty=1.0,
                price=105.0,
                fee=0.2,
                slippage=0.1,
                agent_id="strategy",
                rationale="exit",
                status="FILLED",
                created_at=now,
                realized_delta=4.7,
                remaining_qty=0.0,
                order_type="MARKET",
                fill_price_source="next_bar_open",
                observed_execution=False,
                decision_bar_index=2,
                intent_id="intent-x",
                trade_id="trade-x",
            )
            store.add_fill(fill)
            loaded = store.list_fills("run-p0a")
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].realized_delta, 4.7)
            self.assertEqual(loaded[0].intent_id, "intent-x")
            self.assertFalse(loaded[0].observed_execution)

            from Data.modules.market_sim.types import ClosedTrade

            trade = ClosedTrade(
                trade_id="trade-x",
                run_id="run-p0a",
                instrument="BTCUSDT",
                strategy_id=None,
                strategy_version=None,
                opened_at="t0",
                closed_at="t1",
                side="LONG",
                entry_quantity=1.0,
                exit_quantity=1.0,
                avg_entry_price=100.0,
                avg_exit_price=105.0,
                gross_pnl=5.0,
                fees=0.2,
                slippage_cost=0.1,
                net_pnl=4.7,
                holding_period_bars=3,
                partial_fill_count=0,
                close_reason="signal",
            )
            store.add_closed_trade(trade)
            trades = store.list_closed_trades("run-p0a")
            self.assertEqual(len(trades), 1)
            self.assertAlmostEqual(trades[0].net_pnl, 4.7)


class EngineFinalizeAnnualizationTests(unittest.TestCase):
    def test_engines_pass_periods_per_year(self) -> None:
        import inspect

        from Data.modules.market_sim.engine import SimulationEngine
        from Data.modules.market_sim.multi_engine import MultiAgentEngine

        engine_src = inspect.getsource(SimulationEngine._finalize_metrics)
        multi_src = inspect.getsource(MultiAgentEngine._finalize_metrics)
        self.assertIn("periods_per_year", engine_src)
        self.assertIn("resolve_periods_per_year", engine_src)
        self.assertIn("periods_per_year", multi_src)
        self.assertIn("resolve_periods_per_year", multi_src)


if __name__ == "__main__":
    unittest.main()
