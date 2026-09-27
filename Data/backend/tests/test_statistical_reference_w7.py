"""Statistical reference / honesty tests — qualification-critical methods.

Approximate helpers must not claim MEASURED qualification authority.
Empty samples must never become zero PASS metrics.
"""

from __future__ import annotations

import unittest

from Data.modules.market_sim.stats_inferential import (
    benjamini_hochberg,
    block_bootstrap_mean,
    combinatorial_purged_cv_paths,
    deflated_sharpe_ratio,
    probability_of_backtest_overfitting,
    probability_of_backtest_overfitting_cscv,
    purge_embargo_indices,
)


class StatisticalReferenceTests(unittest.TestCase):
    def test_bootstrap_reference_vector(self) -> None:
        # Deterministic series — CI must bracket mean and be reproducible.
        rets = [0.01, -0.005, 0.002, 0.003, -0.001, 0.004, 0.0, -0.002, 0.001, 0.002]
        a = block_bootstrap_mean(rets, block_size=2, samples=400, seed=11)
        b = block_bootstrap_mean(rets, block_size=2, samples=400, seed=11)
        self.assertEqual(a.mean, b.mean)
        self.assertEqual(a.ci_low, b.ci_low)
        self.assertEqual(a.ci_high, b.ci_high)
        self.assertLessEqual(a.ci_low, a.mean)
        self.assertGreaterEqual(a.ci_high, a.mean)
        self.assertIn("APPROXIMATE", a.method)

    def test_bootstrap_empty_unmeasured(self) -> None:
        empty = block_bootstrap_mean([])
        self.assertIsInstance(empty, dict)
        self.assertEqual(empty["measurement"], "UNMEASURED")
        self.assertIsNone(empty["mean"])

    def test_dsr_reference_vector(self) -> None:
        # Known qualitative: higher n_trials → lower DSR for same observed Sharpe.
        d1 = deflated_sharpe_ratio(1.5, n_trials=1, n_observations=252)
        d50 = deflated_sharpe_ratio(1.5, n_trials=50, n_observations=252)
        self.assertEqual(d1["measurement"], "APPROXIMATE")
        self.assertFalse(d1.get("qualification_authority", True))
        self.assertIsNotNone(d1["dsr"])
        self.assertLess(d50["dsr"], d1["dsr"])
        tiny = deflated_sharpe_ratio(1.0, n_trials=0, n_observations=10)
        self.assertEqual(tiny["measurement"], "UNMEASURED")

    def test_pbo_reference_vector(self) -> None:
        # All identical sharpes → low overfit signal; mixed ranks → higher.
        flat = probability_of_backtest_overfitting([1.0] * 10, seed=1, samples=100)
        mixed = probability_of_backtest_overfitting(
            [2.0, -1.0, 1.5, -0.5, 0.8, -0.2, 1.2, 0.1, -0.8, 0.3],
            seed=1,
            samples=100,
        )
        self.assertEqual(flat["measurement"], "APPROXIMATE")
        self.assertFalse(flat.get("qualification_authority", True))
        self.assertTrue(flat["truth"]["not_cscv_bailey_lopez_de_prado"])
        self.assertIsNotNone(mixed["pbo"])
        small = probability_of_backtest_overfitting([1.0, 2.0], seed=1)
        self.assertEqual(small["measurement"], "UNMEASURED")

    def test_pbo_cscv_reference_vector(self) -> None:
        # T×N matrix: strategy 0 dominates in-sample early, strategy 1 later.
        # Rectangular random-ish matrix must return MEASURED CSCV PBO in [0,1].
        rng = __import__("random").Random(7)
        matrix = [[rng.uniform(-0.02, 0.02) for _ in range(6)] for _ in range(64)]
        # Make col 0 strong in first half, weak in second → selection overfit signal.
        for i in range(32):
            matrix[i][0] += 0.05
        for i in range(32, 64):
            matrix[i][0] -= 0.05
            matrix[i][1] += 0.03
        out = probability_of_backtest_overfitting_cscv(matrix, n_groups=8)
        self.assertEqual(out["measurement"], "MEASURED")
        self.assertFalse(out.get("qualification_authority", True))
        self.assertIn("cscv", out["truth"]["method"])
        self.assertGreaterEqual(out["pbo"], 0.0)
        self.assertLessEqual(out["pbo"], 1.0)
        empty = probability_of_backtest_overfitting_cscv([[1.0]], n_groups=8)
        self.assertEqual(empty["measurement"], "UNMEASURED")

    def test_fdr_reference_vector(self) -> None:
        # Classic BH: with q=0.05, p=[0.001, 0.01, 0.03, 0.04, 0.2] rejects first few.
        out = benjamini_hochberg([0.001, 0.01, 0.03, 0.04, 0.2], q=0.05)
        self.assertEqual(out["measurement"], "MEASURED")
        self.assertIn(0, out["rejected"])
        self.assertNotIn(4, out["rejected"])
        empty = benjamini_hochberg([])
        self.assertEqual(empty["measurement"], "UNMEASURED")

    def test_cpcv_no_overlap(self) -> None:
        cpcv = combinatorial_purged_cv_paths(100, n_groups=6, n_test_groups=2, purge_bars=2, embargo_bars=1)
        self.assertEqual(cpcv["measurement"], "MEASURED")
        self.assertGreater(cpcv["n_paths"], 0)
        self.assertTrue(cpcv["truth"].get("cpcv_geometry_only") or cpcv["truth"].get("no_time_shuffle"))
        for path in cpcv.get("paths") or []:
            train = path.get("train") or path.get("train_range")
            test = path.get("test") or path.get("test_range")
            if isinstance(train, (list, tuple)) and isinstance(test, (list, tuple)) and len(train) == 2 and len(test) == 2:
                # ranges [lo, hi)
                self.assertLessEqual(train[1], test[0])
        gap = purge_embargo_indices(100, train_end=60, test_start=60, purge_bars=5, embargo_bars=5)
        self.assertTrue(gap["causal_gap_ok"])
        train_hi = gap["train"][1]
        test_lo = gap["test"][0]
        self.assertLessEqual(train_hi, test_lo)

    def test_insufficient_sample_unmeasured(self) -> None:
        dsr = deflated_sharpe_ratio(3.0, n_trials=100, n_observations=1)
        self.assertEqual(dsr["measurement"], "UNMEASURED")
        pbo = probability_of_backtest_overfitting([0.1], seed=1)
        self.assertEqual(pbo["measurement"], "UNMEASURED")

    def test_trial_count_includes_failed_trials(self) -> None:
        # DSR must use full trial ledger N including failures (negative sharpes).
        sharpes = [1.2, -0.5, 0.8, -1.0, 0.3, 0.0]
        dsr = deflated_sharpe_ratio(1.2, n_trials=len(sharpes), n_observations=100)
        self.assertEqual(dsr["n_trials"], 6)
        pbo = probability_of_backtest_overfitting(sharpes, seed=2, samples=50)
        self.assertEqual(pbo["n_trials"], 6)


class LiveTradingBlockedRegression(unittest.TestCase):
    def test_live_trading_remains_blocked(self) -> None:
        from Data.modules.market_sim.trading_live_guard import LiveTradingGuard
        from Data.modules.market_sim.types import MarketSimError

        guard = LiveTradingGuard()
        status = guard.public_status()
        self.assertEqual(status["LIVE_TRADING_AVAILABLE"], "BLOCKED")
        with self.assertRaises(MarketSimError) as ctx:
            guard.place_live_order(symbol="BTCUSDT", side="buy", qty=1)
        self.assertEqual(ctx.exception.code, "LIVE_TRADING_BLOCKED")


class CapabilityTruthTests(unittest.TestCase):
    def test_l2_not_claimed_for_ohlcv(self) -> None:
        from Data.modules.market_sim.capabilities import build_market_capabilities

        caps = build_market_capabilities(feature_enabled=True, binance_reachable=False, alpaca_paper=False)
        self.assertTrue(caps["truth"]["ohlcv_is_not_orderbook"])
        gran = {g["granularity"]: g for g in caps["execution_granularity"]}
        self.assertEqual(gran["BAR_OHLCV"]["status"], "SUPPORTED")
        self.assertEqual(gran["BOOK_L2"]["status"], "UNSUPPORTED")
        self.assertTrue(gran["BOOK_L2"]["truth"]["synthetic_l2_forbidden"])
        self.assertEqual(gran["ORDER_EVENT_L3"]["status"], "UNSUPPORTED")
        for row in caps.get("markets") or []:
            self.assertEqual(row.get("LIVE_TRADING_AVAILABLE"), "BLOCKED")

    def test_unsupported_instrument_fails_closed(self) -> None:
        from Data.modules.market_sim.instruments import InstrumentFamily, assert_family_implemented
        from Data.modules.market_sim.types import MarketSimError

        with self.assertRaises(MarketSimError):
            assert_family_implemented(InstrumentFamily.OPTIONS)

    def test_frontend_uses_backend_capabilities_shape(self) -> None:
        from Data.modules.market_sim.capabilities import build_market_capabilities

        caps = build_market_capabilities(feature_enabled=True, binance_reachable=False, alpaca_paper=False)
        self.assertIn("markets", caps)
        self.assertEqual(caps.get("live_trading_default"), "BLOCKED")
        for row in caps["markets"]:
            self.assertIn("HISTORICAL_SIM_AVAILABLE", row)
            self.assertIn("LIVE_TRADING_AVAILABLE", row)
            self.assertEqual(row["LIVE_TRADING_AVAILABLE"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
