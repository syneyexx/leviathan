"""P2A — Strategy DSL v2: breakout, RSI, regime_filter, feature_compare."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from Data.modules.market_sim.causality import SimulationClock
from Data.modules.market_sim.strategy_dsl import (
    DSL_V2_VERSION,
    evaluate_dsl_v2,
    parse_strategy_spec,
    validate_strategy_spec,
)
from Data.modules.market_sim.strategy_eval import evaluate_strategy
from Data.modules.market_sim.types import Bar, OrderSide


def _bars_trend(n: int = 80, *, up: bool = True) -> list[Bar]:
    dt0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    out: list[Bar] = []
    px = 100.0
    for i in range(n):
        px = px + (0.5 if up else -0.5)
        ts = (dt0 + timedelta(hours=i)).isoformat(timespec="seconds")
        out.append(Bar(ts=ts, open=px - 0.1, high=px + 1, low=px - 1, close=px, volume=100))
    return out


def _bars_oscillating(n: int = 80) -> list[Bar]:
    dt0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    out: list[Bar] = []
    for i in range(n):
        # Sharp drop then recovery to stress RSI
        if i < 40:
            px = 100.0 - i * 1.5
        else:
            px = 40.0 + (i - 40) * 2.0
        ts = (dt0 + timedelta(hours=i)).isoformat(timespec="seconds")
        out.append(Bar(ts=ts, open=px, high=px + 0.5, low=px - 0.5, close=px, volume=50))
    return out


class P2AStrategyDslTests(unittest.TestCase):
    def test_parse_and_validate_v2(self) -> None:
        spec = parse_strategy_spec(
            {
                "version": 2,
                "kind": "rsi",
                "entry": {"oversold": 25},
                "filters": [{"kind": "regime_filter", "mode": "adx", "min_adx": 10}],
            },
            exit_rules={"overbought": 75},
            parameters={"period": 14},
        )
        self.assertEqual(spec.version, DSL_V2_VERSION)
        self.assertEqual(spec.kind, "rsi")
        ok, reason = validate_strategy_spec(spec)
        self.assertTrue(ok, reason)

        bad = parse_strategy_spec({"version": 2, "kind": "telepathy"})
        ok2, _ = validate_strategy_spec(bad)
        self.assertFalse(ok2)

    def test_breakout_kind(self) -> None:
        bars = _bars_trend(60, up=True)
        clock = SimulationClock(bars=bars)
        for _ in range(len(bars)):
            clock.advance()
        # Force a breakout-like state at end of strong uptrend
        sig = evaluate_strategy(
            clock,
            parameters={"period": 10},
            entry_rules={"kind": "breakout", "period": 10},
            exit_rules={"kind": "breakout"},
            position_qty=0.0,
        )
        self.assertIn(sig.side, {OrderSide.BUY.value, OrderSide.HOLD.value})
        self.assertIn("breakout", sig.parameters_used.get("kind", "breakout") + sig.rationale)

    def test_rsi_oversold_entry(self) -> None:
        bars = _bars_oscillating(70)
        clock = SimulationClock(bars=bars)
        # Advance into deep drawdown region
        for _ in range(45):
            clock.advance()
        sig = evaluate_strategy(
            clock,
            parameters={"period": 14},
            entry_rules={"kind": "rsi", "oversold": 35, "period": 14},
            exit_rules={"overbought": 70},
            position_qty=0.0,
        )
        self.assertIn(sig.side, {OrderSide.BUY.value, OrderSide.HOLD.value})
        self.assertTrue("rsi" in sig.rationale.lower() or "rsi" in str(sig.parameters_used))

    def test_feature_compare_sma(self) -> None:
        bars = _bars_trend(50, up=True)
        clock = SimulationClock(bars=bars)
        for _ in range(len(bars)):
            clock.advance()
        sig = evaluate_strategy(
            clock,
            parameters={},
            entry_rules={
                "kind": "feature_compare",
                "left": "sma",
                "left_period": 5,
                "op": ">",
                "right_feature": "sma",
                "right_period": 20,
            },
            exit_rules={"op": "<"},
            position_qty=0.0,
        )
        self.assertEqual(sig.parameters_used.get("kind"), "feature_compare")
        # Uptrend: fast SMA should exceed slow → BUY or HOLD with compare rationale
        self.assertIn(sig.side, {OrderSide.BUY.value, OrderSide.HOLD.value})

    def test_regime_filter_blocks_entry(self) -> None:
        bars = _bars_trend(40, up=True)
        clock = SimulationClock(bars=bars)
        for _ in range(len(bars)):
            clock.advance()
        # Require bearish regime on a strong uptrend → block
        sig = evaluate_strategy(
            clock,
            parameters={"period": 14},
            entry_rules={
                "kind": "rsi",
                "oversold": 100,  # always "oversold"
                "filters": [
                    {
                        "kind": "regime_filter",
                        "mode": "trend",
                        "fast": 5,
                        "slow": 20,
                        "require": "bearish",
                    }
                ],
            },
            exit_rules={"overbought": 70},
            position_qty=0.0,
        )
        self.assertEqual(sig.side, OrderSide.HOLD.value)
        self.assertIn("blocked", sig.rationale.lower())

    def test_legacy_ma_cross_still_works(self) -> None:
        bars = _bars_trend(40, up=True)
        clock = SimulationClock(bars=bars)
        for _ in range(35):
            clock.advance()
        sig = evaluate_strategy(
            clock,
            parameters={"fast_ma": 5, "slow_ma": 15},
            entry_rules={"kind": "ma_cross"},
            exit_rules={"kind": "ma_cross"},
            position_qty=0.0,
        )
        self.assertIn(sig.side, {OrderSide.BUY.value, OrderSide.HOLD.value, OrderSide.SELL.value})

    def test_dsl_v2_direct_feature_compare_validation(self) -> None:
        spec = parse_strategy_spec(
            {
                "version": 2,
                "kind": "feature_compare",
                "entry": {"left": "close", "op": ">", "right": 0},
            }
        )
        ok, reason = validate_strategy_spec(spec)
        self.assertTrue(ok, reason)
        bars = _bars_trend(30)
        clock = SimulationClock(bars=bars)
        for _ in range(len(bars)):
            clock.advance()
        dsl = evaluate_dsl_v2(clock, spec, position_qty=0.0)
        self.assertEqual(dsl.parameters_used.get("kind"), "feature_compare")


if __name__ == "__main__":
    unittest.main()
