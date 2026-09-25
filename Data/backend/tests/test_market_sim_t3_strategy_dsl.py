"""T3 — Strategy DSL v2 compile / sandboxed evaluate / lineage tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.market_sim.causality import MarketView, SimulationClock
from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.strategy_dsl import (
    DSL_VERSION,
    STRATEGY_FAMILIES,
    StrategyDslError,
    compile_strategy_dsl,
    evaluate_compiled_strategy,
    family_template,
    is_dsl_v2_document,
    legacy_rules_to_dsl_v2,
    unwrap_dsl_spec,
)
from Data.modules.market_sim.strategy_eval import (
    evaluate_strategy,
    resolve_compiled_strategy,
    validate_strategy_document,
)
from Data.modules.market_sim.types import Bar, MarketSimError, OrderSide


def _bars(n: int = 80, *, start_px: float = 100.0, trend: str = "up") -> list[Bar]:
    out: list[Bar] = []
    px = start_px
    for i in range(n):
        if trend == "up":
            px = px * (1.002 if i % 3 else 0.999)
        elif trend == "down":
            px = px * (0.998 if i % 3 else 1.001)
        else:
            px = px * (1.0005 if i % 2 else 0.9995)
        o = px
        h = px * 1.005
        l = px * 0.995
        c = px * (1.001 if trend == "up" else 0.999)
        day = 1 + i // 24
        hour = i % 24
        ts = f"2024-01-{day:02d}T{hour:02d}:00:00+00:00"
        out.append(Bar(ts=ts, open=o, high=h, low=l, close=c, volume=1000 + i * 10))
        px = c
    return out


class CompileValidateTests(unittest.TestCase):
    def test_compile_family_templates(self) -> None:
        for fam in STRATEGY_FAMILIES:
            spec = family_template(fam)
            compiled = compile_strategy_dsl(spec)
            self.assertEqual(compiled.dsl_version, DSL_VERSION)
            self.assertTrue(compiled.content_hash)
            self.assertTrue(compiled.public_dict()["truth"]["sandboxed"])
            self.assertTrue(compiled.public_dict()["truth"]["no_arbitrary_code"])

    def test_reject_arbitrary_code_tokens(self) -> None:
        spec = family_template("moving_average")
        spec["metadata"] = {"note": "eval(os.system('rm'))"}
        with self.assertRaises(StrategyDslError):
            compile_strategy_dsl(spec)

    def test_reject_unknown_feature(self) -> None:
        spec = family_template("custom")
        spec["features"] = [{"alias": "x", "name": "order_book_imbalance", "period": 10}]
        with self.assertRaises(StrategyDslError):
            compile_strategy_dsl(spec)

    def test_reject_unknown_family(self) -> None:
        spec = family_template("custom")
        spec["family"] = "hft_latency_arb"
        with self.assertRaises(StrategyDslError):
            compile_strategy_dsl(spec)

    def test_reject_bad_condition_ops(self) -> None:
        spec = family_template("custom")
        spec["entry_conditions"] = {"op": "regex_match", "feature": "fast", "value": 1}
        with self.assertRaises(StrategyDslError):
            compile_strategy_dsl(spec)

    def test_reject_forbidden_top_level_keys(self) -> None:
        spec = family_template("custom")
        spec["script"] = "print('pwn')"
        with self.assertRaises(StrategyDslError):
            compile_strategy_dsl(spec)

    def test_is_dsl_v2_document_shapes(self) -> None:
        self.assertTrue(is_dsl_v2_document(family_template("momentum")))
        self.assertFalse(is_dsl_v2_document({"kind": "ma_cross"}))
        self.assertFalse(
            is_dsl_v2_document(
                {"kind": "dsl_v2", "dsl_version": 2, "spec": family_template("custom")}
            )
        )
        nested = unwrap_dsl_spec(
            {"kind": "dsl_v2", "spec": family_template("mean_reversion")}
        )
        self.assertIsNotNone(nested)
        self.assertTrue(is_dsl_v2_document(nested))


class LegacyCompatibilityTests(unittest.TestCase):
    def test_legacy_lift_and_parity_ma_cross(self) -> None:
        bars = _bars(60, trend="up")
        clock = SimulationClock(bars=bars, index=len(bars) - 1)
        params = {"fast_ma": 5, "slow_ma": 15}
        entry = {"kind": "ma_cross"}
        exit_r = {"kind": "ma_cross"}

        legacy = evaluate_strategy(
            clock,
            parameters=params,
            entry_rules=entry,
            exit_rules=exit_r,
            position_qty=0.0,
            use_dsl_v2=False,
        )
        dsl = evaluate_strategy(
            clock,
            parameters=params,
            entry_rules=entry,
            exit_rules=exit_r,
            position_qty=0.0,
            use_dsl_v2=True,
        )
        # Both paths must return a valid side; when flat on a strong uptrend
        # without a fresh cross they typically HOLD.
        self.assertIn(legacy.side, {OrderSide.BUY.value, OrderSide.HOLD.value, OrderSide.SELL.value})
        self.assertIn(dsl.side, {OrderSide.BUY.value, OrderSide.HOLD.value, OrderSide.SELL.value})
        self.assertEqual(dsl.parameters_used.get("dsl_version"), DSL_VERSION)

    def test_mean_reversion_legacy_lift(self) -> None:
        doc = legacy_rules_to_dsl_v2(
            parameters={"lookback": 20, "entry_z": -1.5},
            entry_rules={"kind": "mean_reversion", "entry_z": -1.5},
            exit_rules={"kind": "mean_reversion", "exit_z": 0.0},
        )
        compiled = compile_strategy_dsl(doc)
        self.assertEqual(compiled.family, "mean_reversion")
        self.assertEqual(compiled.legacy_kind, "mean_reversion")

    def test_persisted_dsl_v2_wrapper_resolves(self) -> None:
        compiled = validate_strategy_document(family_template("breakout"))
        wrapper = {
            "kind": "dsl_v2",
            "dsl_version": compiled.dsl_version,
            "content_hash": compiled.content_hash,
            "family": compiled.family,
            "spec": compiled.public_dict(),
        }
        resolved = resolve_compiled_strategy(entry_rules=wrapper)
        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(resolved.content_hash, compiled.content_hash)


class EvaluateCausalTests(unittest.TestCase):
    def test_evaluate_ma_template_on_view(self) -> None:
        bars = _bars(80, trend="up")
        clock = SimulationClock(bars=bars, index=len(bars) - 1)
        view = MarketView(clock=clock, instrument="BTCUSDT", timeframe="1h")
        compiled = compile_strategy_dsl(family_template("moving_average"))
        result = evaluate_compiled_strategy(compiled, view=view, position_qty=0.0)
        self.assertIn(result["side"], {OrderSide.BUY.value, OrderSide.HOLD.value, OrderSide.SELL.value})
        self.assertTrue(result.get("dsl"))

    def test_warmup_holds(self) -> None:
        bars = _bars(8)
        clock = SimulationClock(bars=bars, index=3)
        spec = family_template("moving_average")
        spec["cooldowns"] = {}
        compiled = compile_strategy_dsl(spec)
        result = evaluate_compiled_strategy(compiled, clock=clock, position_qty=0.0)
        self.assertEqual(result["side"], OrderSide.HOLD.value)
        self.assertIn("insufficient", result["rationale"])

    def test_regime_filter_blocks(self) -> None:
        bars = _bars(80)
        clock = SimulationClock(bars=bars, index=len(bars) - 1)
        spec = family_template("trend_following")
        spec["cooldowns"] = {}
        # Force regime filter that will fail on feature value if we set impossible threshold
        spec["regime_filters"] = {"feature": "adx14", "op": "gte", "value": 1e9}
        compiled = compile_strategy_dsl(spec)
        result = evaluate_compiled_strategy(compiled, clock=clock, position_qty=0.0)
        self.assertEqual(result["side"], OrderSide.HOLD.value)
        self.assertIn("regime", result["rationale"])


class ServiceDslIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        markets = root / "markets"
        markets.mkdir(parents=True)
        db = root / "leviathan.db"
        store = MarketSimStore(db)
        store.initialize()
        data = MarketDataStore(store, markets)
        self.svc = MarketSimControlPlane(store, data, enabled=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_create_from_family_and_fork_version(self) -> None:
        created = self.svc.create_strategy(name="TF", family="trend_following")
        self.assertIsNotNone(created.get("compiled"))
        sid = created["strategy"]["strategy_id"]
        self.assertEqual(created["strategy"]["metadata"]["family"], "trend_following")
        self.assertEqual(created["version"]["entry_rules"]["kind"], "dsl_v2")

        validated = self.svc.validate_strategy_dsl(family_template("momentum"))
        self.assertTrue(validated["valid"])

        families = self.svc.list_strategy_families()
        self.assertIn("mean_reversion", families["families"])

        tmpl = self.svc.strategy_family_template("breakout")
        self.assertEqual(tmpl["compiled"]["family"], "breakout")

        v2 = self.svc.version_strategy(
            sid,
            dsl_spec=family_template("mean_reversion"),
            changelog="switch to MR",
        )
        self.assertEqual(v2["strategy"]["current_version"], 2)
        self.assertEqual(v2["compiled"]["family"], "mean_reversion")
        self.assertNotEqual(v2["version"]["content_hash"], created["version"]["content_hash"])

        fork = self.svc.fork_strategy(sid, name="TF fork")
        self.assertIsNotNone(fork.get("compiled"))
        self.assertEqual(fork["compiled"]["family"], "mean_reversion")
        self.assertNotEqual(fork["strategy"]["strategy_id"], sid)

    def test_create_from_dsl_spec_rejects_bad(self) -> None:
        bad = family_template("custom")
        bad["features"] = [{"alias": "x", "name": "not_a_real_feature", "period": 5}]
        with self.assertRaises(MarketSimError):
            self.svc.create_strategy(name="bad", dsl_spec=bad)

    def test_legacy_create_still_works(self) -> None:
        created = self.svc.create_strategy(
            name="legacy-ma",
            parameters={"fast_ma": 5, "slow_ma": 20},
            entry_rules={"kind": "ma_cross"},
        )
        self.assertEqual(created["version"]["entry_rules"]["kind"], "ma_cross")
        self.assertIsNone(created.get("compiled"))


class SandboxEscapeSuite(unittest.TestCase):
    """G16-lite: declarative DSL must not accept code/escape hatches."""

    CASES = [
        {"__import__": "os"},
        {"code": "x=1"},
        {"python": "1+1"},
        {"module": "os"},
        {"path": "/etc/passwd"},
        {"url": "http://evil"},
        {"endpoint": "/admin"},
        {"script": "rm -rf /"},
    ]

    def test_top_level_escape_keys_rejected(self) -> None:
        for payload in self.CASES:
            spec = family_template("custom")
            spec.update(payload)
            with self.assertRaises(StrategyDslError, msg=str(payload)):
                compile_strategy_dsl(spec)

    def test_feature_param_dunder_rejected(self) -> None:
        spec = family_template("custom")
        spec["features"] = [
            {"alias": "fast", "name": "sma", "period": 10, "params": {"__class__": "x"}}
        ]
        with self.assertRaises(StrategyDslError):
            compile_strategy_dsl(spec)


if __name__ == "__main__":
    unittest.main()
