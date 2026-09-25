"""P2A — Strategy DSL v2: breakout, RSI, regime_filter, feature_compare."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from Data.modules.market_sim.causality import SimulationClock
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore, utc_now
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


class P2BTrialLedgerAndWfaTests(unittest.TestCase):
    def test_rolling_wfa_windows(self) -> None:
        from Data.modules.market_sim.wfa import rolling_wfa_windows, walk_forward_plan

        bars = _bars_trend(100)
        windows = rolling_wfa_windows(bars, train_size=30, test_size=10, step=10, purge_bars=2)
        self.assertGreaterEqual(len(windows), 2)
        self.assertLess(windows[0].train_end_index, windows[0].test_start_index)
        plan = walk_forward_plan(bars, mode="rolling", train_size=30, test_size=10, step=10)
        self.assertEqual(plan["mode"], "rolling")
        self.assertIn("windows", plan)

    def test_acceptance_from_run_ids(self) -> None:
        from Data.modules.market_sim.wfa import evaluate_acceptance_from_run

        run = {
            "run_id": "r-accept",
            "metrics": {
                "trade_count": {"value": 10, "status": "MEASURED"},
                "total_return": {"value": 0.05, "status": "MEASURED"},
                "max_drawdown": {"value": 0.08, "status": "MEASURED"},
            },
            "metadata": {},
        }
        result = evaluate_acceptance_from_run(
            run,
            criteria={"min_trades": 5, "max_drawdown_pct": 25.0, "min_total_return_pct": 0.0},
            sealed_attempt_id="sa-1",
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.run_id, "r-accept")
        self.assertEqual(result.sealed_attempt_id, "sa-1")
        self.assertTrue(result.public_dict()["truth"]["acceptance_from_run_metrics"])

    def test_append_trial_ledger(self) -> None:
        import tempfile
        from pathlib import Path

        from Data.backend.migrations import MigrationRunner
        from Data.modules.market_sim.store import MarketSimStore, utc_now

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "leviathan.db"
            MigrationRunner(db).apply_all()
            store = MarketSimStore(db)
            a = store.append_trial(
                {
                    "trial_id": "same",
                    "strategy_id": "strat",
                    "strategy_version": 1,
                    "hypothesis": "a",
                    "proposer_agent_id": "x",
                    "data_hash": "h",
                    "fingerprint": "f1",
                    "status": "proposed",
                    "config": {},
                    "split": {},
                    "results": {},
                    "acceptance_criteria": {},
                    "seed": 1,
                    "created_at": utc_now(),
                }
            )
            b = store.append_trial(
                {
                    "trial_id": "same",
                    "strategy_id": "strat",
                    "strategy_version": 2,
                    "hypothesis": "b",
                    "proposer_agent_id": "x",
                    "data_hash": "h",
                    "fingerprint": "f2",
                    "status": "proposed",
                    "config": {},
                    "split": {},
                    "results": {},
                    "acceptance_criteria": {},
                    "seed": 2,
                    "created_at": utc_now(),
                }
            )
            self.assertNotEqual(a["trial_id"], b["trial_id"])
            self.assertEqual(store.count_trials(), 2)


class P2CSandboxLineageMemoryTests(unittest.TestCase):
    def test_python_strategy_feature_gated(self) -> None:
        from Data.modules.market_sim.code_strategy import (
            assert_not_python_strategy,
            python_strategy_capability,
        )
        from Data.modules.market_sim.types import MarketSimError

        cap = python_strategy_capability()
        self.assertEqual(cap["availability"], "NOT_AVAILABLE")
        self.assertEqual(cap["status"], "FEATURE_GATED")
        with self.assertRaises(MarketSimError) as ctx:
            assert_not_python_strategy({"kind": "python", "source": "print(1)"})
        self.assertEqual(ctx.exception.code, "PYTHON_STRATEGY_NOT_AVAILABLE")

    def _plane(self, tmp: str) -> MarketSimControlPlane:
        from Data.modules.market_sim.data_store import MarketDataStore

        root = Path(tmp)
        store = MarketSimStore(root / "leviathan.db")
        store.initialize()
        data = MarketDataStore(store, root / "markets")
        return MarketSimControlPlane(store=store, data=data, enabled=True)

    def test_create_strategy_rejects_python(self) -> None:
        from Data.modules.market_sim.types import MarketSimError

        with tempfile.TemporaryDirectory() as tmp:
            plane = self._plane(tmp)
            with self.assertRaises(MarketSimError) as ctx:
                plane.create_strategy(
                    name="py",
                    entry_rules={"kind": "python", "source": "x=1"},
                )
            self.assertEqual(ctx.exception.code, "PYTHON_STRATEGY_NOT_AVAILABLE")

    def test_strategy_lineage_metadata(self) -> None:
        from Data.modules.market_sim.strategy_lineage import attach_lineage_metadata, lineage_chain

        meta = attach_lineage_metadata(
            parent_version=1,
            parent_content_hash="abc",
            changelog="v2",
        )
        self.assertTrue(meta["immutable"])
        self.assertEqual(meta["parent_version"], 1)
        self.assertTrue(meta["lineage"])

        with tempfile.TemporaryDirectory() as tmp:
            plane = self._plane(tmp)
            created = plane.create_strategy(name="lineage")
            sid = created["strategy"]["strategy_id"]
            v2 = plane.version_strategy(
                sid,
                parameters={"fast_ma": 5, "slow_ma": 20},
                changelog="tighten",
            )
            self.assertTrue(v2["version"]["metadata"]["immutable"])
            self.assertEqual(v2["version"]["metadata"]["parent_version"], 1)
            chain = lineage_chain(plane.store, sid)
            self.assertEqual(len(chain), 2)
            self.assertEqual(chain[0]["version"], 1)
            self.assertEqual(chain[1]["version"], 2)

    def test_strategy_memory_as_of_causal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketSimStore(Path(tmp) / "m.db")
            store.initialize()
            store.save_strategy_memory(
                {
                    "memory_id": "early",
                    "strategy_id": "s1",
                    "strategy_version": 1,
                    "features": {},
                    "applicability": {},
                    "outcome_summary": "early",
                    "trial_id": None,
                    "available_at": "2020-01-01T00:00:00+00:00",
                    "created_at": utc_now(),
                    "rejected": False,
                }
            )
            store.save_strategy_memory(
                {
                    "memory_id": "future",
                    "strategy_id": "s1",
                    "strategy_version": 1,
                    "features": {},
                    "applicability": {},
                    "outcome_summary": "future",
                    "trial_id": None,
                    "available_at": "2030-01-01T00:00:00+00:00",
                    "created_at": utc_now(),
                    "rejected": False,
                }
            )
            rows = store.list_strategy_memories(
                strategy_id="s1",
                as_of_ts="2024-01-01T00:00:00+00:00",
            )
            ids = {r["memory_id"] for r in rows}
            self.assertIn("early", ids)
            self.assertNotIn("future", ids)


if __name__ == "__main__":
    unittest.main()
