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


# ---------------------------------------------------------------------------
# P0B — one execution path, TIF, limit/stop, intrabar
# ---------------------------------------------------------------------------


class P0BCanonicalExecutionPathTests(unittest.TestCase):
    def test_step_once_has_no_legacy_fill_import(self) -> None:
        import inspect

        from Data.modules.market_sim.engine import SimulationEngine

        src = inspect.getsource(SimulationEngine.step_once)
        self.assertNotIn("LegacyFill", src)
        self.assertNotIn("from .fill_model", src)
        self.assertIn("execute_intent", src)
        self.assertIn("wallet", src)

    def test_engine_state_uses_wallet_ledger(self) -> None:
        import inspect

        from Data.modules.market_sim.engine import EngineState, SimulationEngine

        fields = EngineState.__dataclass_fields__
        self.assertIn("wallet", fields)
        prep = inspect.getsource(SimulationEngine.prepare)
        self.assertIn("WalletLedger", prep)
        self.assertIn("RiskGuard", prep)


class P0BPartialAndTifTests(unittest.TestCase):
    def test_bar_tif_cancels_remainder(self) -> None:
        from Data.modules.market_sim.accounting import WalletBook
        from Data.modules.market_sim.execution import NextBarFillModel, make_intent

        book = WalletBook()
        w = book.ensure_agent("a", initial_cash=500)
        intent = make_intent(
            run_id="r",
            agent_id="a",
            wallet_id=w.wallet_id,
            side="BUY",
            qty=100,
            decision_bar_index=0,
            decision_ts="t0",
            info_version="v",
            time_in_force="BAR",
        )
        result = NextBarFillModel(fee_bps=0, slippage_bps=0, max_participation=1.0).execute_intent(
            wallet=w, intent=intent, fill_open=100.0, bar_volume=1e9, fill_bar_index=1
        )
        self.assertTrue(result.filled)
        self.assertEqual(result.status, "PARTIAL")
        self.assertEqual(intent.status, "filled")
        self.assertEqual(float(result.remaining_qty or 0), 0.0)

    def test_gtc_partial_keeps_working_remainder(self) -> None:
        from Data.modules.market_sim.accounting import WalletBook
        from Data.modules.market_sim.execution import NextBarFillModel, make_intent

        book = WalletBook()
        w = book.ensure_agent("a", initial_cash=500)
        intent = make_intent(
            run_id="r",
            agent_id="a",
            wallet_id=w.wallet_id,
            side="BUY",
            qty=100,
            decision_bar_index=0,
            decision_ts="t0",
            info_version="v",
            time_in_force="GTC",
        )
        result = NextBarFillModel(fee_bps=0, slippage_bps=0, max_participation=1.0).execute_intent(
            wallet=w, intent=intent, fill_open=100.0, bar_volume=1e9, fill_bar_index=1
        )
        self.assertTrue(result.filled)
        self.assertEqual(intent.status, "working")
        self.assertGreater(float(result.remaining_qty or 0), 0)
        self.assertAlmostEqual(float(intent.qty or 0), float(result.remaining_qty or 0))

    def test_fok_rejects_when_cash_insufficient(self) -> None:
        from Data.modules.market_sim.accounting import WalletBook
        from Data.modules.market_sim.execution import NextBarFillModel, make_intent

        book = WalletBook()
        w = book.ensure_agent("a", initial_cash=500)
        intent = make_intent(
            run_id="r",
            agent_id="a",
            wallet_id=w.wallet_id,
            side="BUY",
            qty=100,
            decision_bar_index=0,
            decision_ts="t0",
            info_version="v",
            time_in_force="FOK",
        )
        result = NextBarFillModel(fee_bps=0, slippage_bps=0, max_participation=1.0).execute_intent(
            wallet=w, intent=intent, fill_open=100.0, bar_volume=1e9, fill_bar_index=1
        )
        self.assertFalse(result.filled)
        self.assertEqual(intent.status, "rejected")


class P0BLimitStopTests(unittest.TestCase):
    def test_limit_buy_non_trigger(self) -> None:
        from Data.modules.market_sim.accounting import WalletBook
        from Data.modules.market_sim.execution import NextBarFillModel, make_intent

        book = WalletBook()
        w = book.ensure_agent("a", initial_cash=10_000)
        intent = make_intent(
            run_id="r",
            agent_id="a",
            wallet_id=w.wallet_id,
            side="BUY",
            qty=1,
            decision_bar_index=0,
            decision_ts="t0",
            info_version="v",
            order_type="LIMIT",
            limit_price=90.0,
            time_in_force="GTC",
        )
        result = NextBarFillModel(fee_bps=0, slippage_bps=0).execute_intent(
            wallet=w,
            intent=intent,
            fill_open=100.0,
            fill_high=105.0,
            fill_low=95.0,
            bar_volume=1e6,
            fill_bar_index=1,
        )
        self.assertFalse(result.filled)
        self.assertEqual(intent.status, "working")

    def test_limit_buy_triggers_at_limit_when_open_above(self) -> None:
        from Data.modules.market_sim.accounting import WalletBook
        from Data.modules.market_sim.execution import NextBarFillModel, make_intent

        book = WalletBook()
        w = book.ensure_agent("a", initial_cash=10_000)
        intent = make_intent(
            run_id="r",
            agent_id="a",
            wallet_id=w.wallet_id,
            side="BUY",
            qty=1,
            decision_bar_index=0,
            decision_ts="t0",
            info_version="v",
            order_type="LIMIT",
            limit_price=98.0,
            time_in_force="BAR",
        )
        result = NextBarFillModel(fee_bps=0, slippage_bps=0).execute_intent(
            wallet=w,
            intent=intent,
            fill_open=100.0,
            fill_high=101.0,
            fill_low=97.0,
            bar_volume=1e6,
            fill_bar_index=1,
        )
        self.assertTrue(result.filled)
        self.assertAlmostEqual(float(result.price), 98.0)
        self.assertEqual(result.fill_price_source, "limit_price")

    def test_stop_buy_gap_uses_open(self) -> None:
        from Data.modules.market_sim.accounting import WalletBook
        from Data.modules.market_sim.execution import NextBarFillModel, make_intent

        book = WalletBook()
        w = book.ensure_agent("a", initial_cash=10_000)
        intent = make_intent(
            run_id="r",
            agent_id="a",
            wallet_id=w.wallet_id,
            side="BUY",
            qty=1,
            decision_bar_index=0,
            decision_ts="t0",
            info_version="v",
            order_type="STOP",
            stop_price=100.0,
            time_in_force="BAR",
        )
        result = NextBarFillModel(fee_bps=0, slippage_bps=0).execute_intent(
            wallet=w,
            intent=intent,
            fill_open=105.0,
            fill_high=106.0,
            fill_low=104.0,
            bar_volume=1e6,
            fill_bar_index=1,
        )
        self.assertTrue(result.filled)
        self.assertAlmostEqual(float(result.price), 105.0)
        self.assertEqual(result.fill_price_source, "next_bar_open_gap")

    def test_stop_sell_triggers_at_stop_inside_bar(self) -> None:
        from Data.modules.market_sim.accounting import WalletBook, money
        from Data.modules.market_sim.execution import NextBarFillModel, make_intent

        book = WalletBook()
        w = book.ensure_agent("a", initial_cash=10_000)
        w.apply_buy(qty=1, price=money(110), fee=money(0), tx_id="setup")
        intent = make_intent(
            run_id="r",
            agent_id="a",
            wallet_id=w.wallet_id,
            side="SELL",
            qty=1,
            decision_bar_index=0,
            decision_ts="t0",
            info_version="v",
            order_type="STOP",
            stop_price=100.0,
            time_in_force="BAR",
        )
        result = NextBarFillModel(fee_bps=0, slippage_bps=0).execute_intent(
            wallet=w,
            intent=intent,
            fill_open=102.0,
            fill_high=103.0,
            fill_low=99.0,
            bar_volume=1e6,
            fill_bar_index=1,
        )
        self.assertTrue(result.filled)
        self.assertAlmostEqual(float(result.price), 100.0)
        self.assertEqual(result.fill_price_source, "stop_price")

    def test_stop_limit_no_guaranteed_fill_after_arm(self) -> None:
        from Data.modules.market_sim.accounting import WalletBook
        from Data.modules.market_sim.execution import NextBarFillModel, make_intent

        book = WalletBook()
        w = book.ensure_agent("a", initial_cash=10_000)
        intent = make_intent(
            run_id="r",
            agent_id="a",
            wallet_id=w.wallet_id,
            side="BUY",
            qty=1,
            decision_bar_index=0,
            decision_ts="t0",
            info_version="v",
            order_type="STOP_LIMIT",
            stop_price=100.0,
            limit_price=99.0,
            time_in_force="GTC",
        )
        # Open gaps through stop but never trades down to limit
        result = NextBarFillModel(fee_bps=0, slippage_bps=0).execute_intent(
            wallet=w,
            intent=intent,
            fill_open=101.0,
            fill_high=102.0,
            fill_low=100.5,
            bar_volume=1e6,
            fill_bar_index=1,
        )
        self.assertFalse(result.filled)
        self.assertTrue(intent.stop_triggered)
        self.assertEqual(intent.status, "working")


class P0BIntrabarPolicyTests(unittest.TestCase):
    def test_ambiguous_stop_target_uses_conservative(self) -> None:
        from Data.modules.market_sim.execution import resolve_intrabar_path
        from Data.modules.market_sim.types import IntrabarPathPolicy

        path = resolve_intrabar_path(
            side="LONG",
            stop_price=95.0,
            target_price=108.0,
            open_px=100.0,
            high=110.0,
            low=90.0,
            policy=IntrabarPathPolicy.CONSERVATIVE.value,
        )
        self.assertTrue(path["ambiguous"])
        self.assertEqual(path["outcome"], "stop")

    def test_unresolved_policy_marks_unresolved(self) -> None:
        from Data.modules.market_sim.execution import resolve_intrabar_path
        from Data.modules.market_sim.types import IntrabarPathPolicy

        path = resolve_intrabar_path(
            side="LONG",
            stop_price=95.0,
            target_price=108.0,
            open_px=100.0,
            high=110.0,
            low=90.0,
            policy=IntrabarPathPolicy.UNRESOLVED.value,
        )
        self.assertEqual(path["outcome"], "unresolved")


class P0BGoldenFillPnLTests(unittest.TestCase):
    def test_market_buy_sell_roundtrip_pnl(self) -> None:
        from Data.modules.market_sim.accounting import WalletBook
        from Data.modules.market_sim.execution import NextBarFillModel, make_intent

        book = WalletBook()
        w = book.ensure_agent("a", initial_cash=10_000)
        model = NextBarFillModel(fee_bps=0, slippage_bps=0, max_participation=1.0)
        buy = make_intent(
            run_id="r",
            agent_id="a",
            wallet_id=w.wallet_id,
            side="BUY",
            qty=10,
            decision_bar_index=0,
            decision_ts="t0",
            info_version="v",
            time_in_force="BAR",
        )
        r1 = model.execute_intent(
            wallet=w, intent=buy, fill_open=100.0, bar_volume=1e9, fill_bar_index=1
        )
        self.assertTrue(r1.filled)
        sell = make_intent(
            run_id="r",
            agent_id="a",
            wallet_id=w.wallet_id,
            side="SELL",
            qty=10,
            decision_bar_index=1,
            decision_ts="t1",
            info_version="v2",
            time_in_force="BAR",
        )
        before = float(w.realized_pnl)
        r2 = model.execute_intent(
            wallet=w, intent=sell, fill_open=110.0, bar_volume=1e9, fill_bar_index=2
        )
        self.assertTrue(r2.filled)
        self.assertAlmostEqual(float(w.realized_pnl) - before, 100.0)


if __name__ == "__main__":
    unittest.main()
