"""T2 — MarketState + Feature Engine regression tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.market_sim.causality import MarketView, SimulationClock
from Data.modules.market_sim.features import (
    FEATURE_PIPELINE_VERSION,
    FeatureEngine,
    FeatureStatus,
    assert_bars_causal,
    sma,
)
from Data.modules.market_sim.market_state import (
    MultiTimeframeView,
    aggregate_bars,
    build_market_state,
    synthesize_higher_timeframe,
)
from Data.modules.market_sim.types import Bar, CausalityViolation, MarketSimError


def _bars(n: int = 80, *, start_px: float = 100.0) -> list[Bar]:
    out: list[Bar] = []
    px = start_px
    for i in range(n):
        # Mild uptrend with noise
        px = px * (1.001 if i % 5 else 0.999)
        o = px
        h = px * 1.01
        l = px * 0.99
        c = px * 1.002
        ts = f"2024-01-01T{i:02d}:00:00+00:00" if i < 24 else f"2024-01-02T{(i - 24):02d}:00:00+00:00"
        if i >= 48:
            day = 3 + (i - 48) // 24
            hour = (i - 48) % 24
            ts = f"2024-01-{day:02d}T{hour:02d}:00:00+00:00"
        out.append(Bar(ts=ts, open=o, high=h, low=l, close=c, volume=1000 + i * 10))
        px = c
    return out


class FeatureLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bars = _bars(80)
        self.engine = FeatureEngine()
        self.as_of = self.bars[-1].ts

    def test_sma_ema_rsi_atr_adx(self) -> None:
        for name, period in (("sma", 20), ("ema", 20), ("rsi", 14), ("atr", 14), ("adx", 14)):
            fv = self.engine.compute(self.bars, name, as_of=self.as_of, period=period)
            self.assertEqual(fv.status, FeatureStatus.MEASURED.value, msg=name)
            self.assertIsNotNone(fv.value)
            self.assertEqual(fv.provenance["pipeline_version"], FEATURE_PIPELINE_VERSION)

    def test_bollinger_zscore_roc_vol(self) -> None:
        for name in ("bollinger_mid", "bollinger_upper", "bollinger_lower", "zscore", "roc", "realized_vol"):
            fv = self.engine.compute(self.bars, name, as_of=self.as_of)
            self.assertEqual(fv.status, FeatureStatus.MEASURED.value, msg=name)

    def test_donchian_breakout_volume_vwap(self) -> None:
        for name in ("donchian_high", "donchian_low", "breakout", "volume_avg", "volume_z", "vwap", "trend_slope", "drawdown"):
            fv = self.engine.compute(self.bars, name, as_of=self.as_of)
            self.assertEqual(fv.status, FeatureStatus.MEASURED.value, msg=name)

    def test_insufficient_history(self) -> None:
        fv = self.engine.compute(self.bars[:5], "rsi", as_of=self.bars[4].ts, period=14)
        self.assertEqual(fv.status, FeatureStatus.INSUFFICIENT_HISTORY.value)
        self.assertIsNone(fv.value)

    def test_orderbook_features_not_invented(self) -> None:
        fv = self.engine.compute(self.bars, "order_book_imbalance", as_of=self.as_of)
        self.assertEqual(fv.status, FeatureStatus.NOT_IMPLEMENTED.value)
        self.assertIn("OHLCV", str(fv.params))

    def test_market_breadth_not_implemented_without_universe(self) -> None:
        fv = self.engine.compute(self.bars, "market_breadth", as_of=self.as_of)
        self.assertEqual(fv.status, FeatureStatus.NOT_IMPLEMENTED.value)

    def test_correlation_beta_relative_strength(self) -> None:
        bench = _bars(80, start_px=200.0)
        corr = self.engine.compute(self.bars, "correlation", as_of=self.as_of, period=20, benchmark_bars=bench)
        beta = self.engine.compute(self.bars, "beta", as_of=self.as_of, period=20, benchmark_bars=bench)
        rs = self.engine.compute(self.bars, "relative_strength", as_of=self.as_of, period=20, benchmark_bars=bench)
        sp = self.engine.compute(self.bars, "spread", as_of=self.as_of, benchmark_bars=bench)
        for fv in (corr, beta, rs, sp):
            self.assertEqual(fv.status, FeatureStatus.MEASURED.value, msg=fv.name)

    def test_sma_matches_manual(self) -> None:
        closes = [b.close for b in self.bars]
        self.assertAlmostEqual(sma(closes, 10) or 0.0, sum(closes[-10:]) / 10.0)

    def test_feature_refuses_future_bars(self) -> None:
        with self.assertRaises(CausalityViolation):
            assert_bars_causal(self.bars, as_of=self.bars[10].ts)


class MarketViewFeatureTests(unittest.TestCase):
    def test_view_feature_is_causal(self) -> None:
        bars = _bars(40)
        clock = SimulationClock(bars=bars)
        for _ in range(25):
            clock.advance()
        view = MarketView(clock=clock, instrument="BTCUSDT", timeframe="1h")
        fv = view.feature("rsi", period=14)
        self.assertEqual(fv.status, FeatureStatus.MEASURED.value)  # type: ignore[union-attr]
        # Feature uses only visible bars
        self.assertEqual(fv.lookback_used, 25)  # type: ignore[union-attr]
        self.assertEqual(fv.as_of, clock.current_ts)  # type: ignore[union-attr]

    def test_strategy_cannot_access_future_feature(self) -> None:
        bars = _bars(30)
        clock = SimulationClock(bars=bars)
        clock.advance()
        view = MarketView(clock=clock, instrument="X", timeframe="1h")
        # Poison: trying to compute on future bars via assert
        with self.assertRaises(CausalityViolation):
            assert_bars_causal(bars, as_of=view.as_of or "")


class MarketStateTests(unittest.TestCase):
    def test_build_market_state(self) -> None:
        bars = _bars(80)
        clock = SimulationClock(bars=bars, index=len(bars) - 1)
        view = MarketView(clock=clock, instrument="BTCUSDT", timeframe="1h")
        state = build_market_state(view, venue="binance", asset_class="crypto_spot")
        payload = state.public_dict()
        self.assertEqual(payload["identity"]["as_of"], bars[-1].ts)
        self.assertIn(payload["trend"]["direction"], {"up", "down", "flat"})
        self.assertIn(payload["volatility"]["label"], {"low", "medium", "high"})
        self.assertTrue(payload["truth"]["deterministic_features_are_facts"])
        self.assertTrue(payload["truth"]["ohlcv_is_not_orderbook"])
        self.assertEqual(state.provenance["feature_pipeline_version"], FEATURE_PIPELINE_VERSION)
        summary = state.summary_features()
        self.assertIn("regime", summary)
        self.assertIn("trend", summary)

    def test_market_state_before_clock_fails(self) -> None:
        clock = SimulationClock(bars=_bars(10), index=-1)
        view = MarketView(clock=clock, instrument="X", timeframe="1h")
        with self.assertRaises(CausalityViolation):
            build_market_state(view)

    def test_view_market_state_helper(self) -> None:
        bars = _bars(50)
        clock = SimulationClock(bars=bars, index=len(bars) - 1)
        view = MarketView(clock=clock, instrument="ETHUSDT", timeframe="1h")
        state = view.market_state(asset_class="crypto_spot")
        self.assertEqual(state.instrument, "ETHUSDT")


class MultiTimeframeTests(unittest.TestCase):
    def test_aggregate_and_synthesize(self) -> None:
        bars = _bars(48)
        clock = SimulationClock(bars=bars, index=len(bars) - 1)
        base = MarketView(clock=clock, instrument="BTCUSDT", timeframe="1h")
        h4 = synthesize_higher_timeframe(base, target_timeframe="4h")
        self.assertEqual(h4.timeframe, "4h")
        self.assertLessEqual(len(h4.visible_bars()), len(bars))
        # Aggregated as_of must not exceed base as_of
        self.assertLessEqual(h4.as_of or "", base.as_of or "")

        mt = MultiTimeframeView(base=base, frames={"4h": h4})
        rsi_1h = mt.feature("rsi", timeframe="1h", period=14)
        rsi_4h = mt.feature("rsi", timeframe="4h", period=14)
        self.assertEqual(rsi_1h.status, FeatureStatus.MEASURED.value)
        # 4h may still be warming depending on bar count
        self.assertIn(rsi_4h.status, {FeatureStatus.MEASURED.value, FeatureStatus.INSUFFICIENT_HISTORY.value})
        states = mt.states()
        self.assertIn("1h", states)
        self.assertIn("4h", states)

    def test_synthesize_refuses_before_start(self) -> None:
        clock = SimulationClock(bars=_bars(10), index=-1)
        base = MarketView(clock=clock, instrument="X", timeframe="1h")
        with self.assertRaises(CausalityViolation):
            synthesize_higher_timeframe(base, target_timeframe="4h")

    def test_aggregate_ohlcv_invariants(self) -> None:
        bars = _bars(8)
        agg = aggregate_bars(bars, target_seconds=4 * 3600)
        self.assertGreaterEqual(len(agg), 1)
        for b in agg:
            self.assertGreaterEqual(b.high, max(b.open, b.close))
            self.assertLessEqual(b.low, min(b.open, b.close))


class FeatureProvenanceTests(unittest.TestCase):
    def test_provenance_fields_present(self) -> None:
        bars = _bars(30)
        fv = FeatureEngine().compute(bars, "sma", as_of=bars[-1].ts, period=10)
        self.assertEqual(fv.provenance["first_ts"], bars[0].ts)
        self.assertEqual(fv.provenance["last_ts"], bars[-1].ts)
        self.assertEqual(fv.provenance["source"], "ohlcv_causal_window")


class MultiEngineMarketStateIntegrationTests(unittest.TestCase):
    def test_prepare_and_step_emits_market_state(self) -> None:
        from Data.modules.common.hashing import sha256_file
        from Data.modules.market_sim.multi_engine import MultiAgentEngine
        from Data.modules.market_sim.store import MarketSimStore, utc_now
        from Data.modules.market_sim.types import SimRun

        fixture = Path(__file__).resolve().parent / "fixtures" / "market_data" / "BTCUSDT_1h.csv"
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketSimStore(Path(tmp) / "db.sqlite")
            store.initialize()
            run = SimRun(
                run_id="t2-run",
                status="QUEUED",
                source_id="src",
                strategy_id="s",
                strategy_version=1,
                symbol="BTCUSDT",
                timeframe="1h",
                start_ts="",
                end_ts="",
                data_hash=sha256_file(fixture),
                seed=1,
                initial_cash=100_000.0,
                cash=100_000.0,
                created_at=utc_now(),
                updated_at=utc_now(),
                agents=[
                    {
                        "agent_id": "a1",
                        "role": "market_analyst",
                        "authority": {"may_order": True},
                        "parameters": {"fast_ma": 5, "slow_ma": 12},
                    }
                ],
                metadata={"game_mode": "individual", "agent_initial_cash": 50_000},
                deliberation_every_n=1,
            )
            store.create_run(run)
            engine = MultiAgentEngine(store)
            state = engine.prepare(run, bars_path=str(fixture))
            # Advance enough for features
            for _ in range(40):
                if not engine.step_once(state):
                    break
            events = store.list_events(run.run_id, kind="commit_reveal_round", limit=50)
            self.assertGreater(len(events), 0)
            # At least one later round should carry market_state once warmed
            with_state = [e for e in events if (e.get("payload") or {}).get("market_state")]
            self.assertGreater(len(with_state), 0)
            ms = with_state[-1]["payload"]["market_state"]
            self.assertIn("identity", ms)
            self.assertIn("regime", ms)
            self.assertTrue(ms["truth"]["deterministic_features_are_facts"])


if __name__ == "__main__":
    unittest.main()
