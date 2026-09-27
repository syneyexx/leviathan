"""Wave 6 — scenario / stress catalog honesty + RiskGuard kill-switch clarity.

Covers:
- required stress scenarios exist and are deterministic for same seed/inputs
- missing inputs → UNMEASURED (never fake PASS)
- live trading remains blocked (LiveTradingGuard)
"""

from __future__ import annotations

import unittest

from Data.modules.market_sim.risk_guard import RiskGuard, RiskLimits
from Data.modules.market_sim.scenario_risk import (
    REQUIRED_STRESS_SCENARIO_IDS,
    STRESS_SCENARIO_IDS,
    bind_stress_scenario,
    get_stress_scenario,
    list_stress_scenario_ids,
    required_stress_scenarios_present,
    run_stress_scenario,
    stress_catalog,
)


class ScenarioRiskW6CatalogTests(unittest.TestCase):
    def test_required_scenarios_exist(self) -> None:
        catalog = stress_catalog()
        self.assertTrue(required_stress_scenarios_present(catalog))
        ids = set(list_stress_scenario_ids())
        self.assertEqual(ids, set(STRESS_SCENARIO_IDS))
        for sid in REQUIRED_STRESS_SCENARIO_IDS:
            self.assertIn(sid, catalog)
            self.assertIsNotNone(get_stress_scenario(sid))
        # rate_move OR fx_move
        self.assertTrue({"rate_move", "fx_move"} & ids)
        for sid, spec in catalog.items():
            pub = spec.public_dict()
            self.assertTrue(pub["truth"]["stress_scenario_is_not_a_forecast"])
            self.assertTrue(pub["truth"]["no_fabricated_probabilities"])
            self.assertNotIn("probability", pub)
            self.assertNotIn("prob", pub)
            self.assertEqual(spec.status, "ASSUMED")

    def test_scenarios_deterministic_for_same_seed(self) -> None:
        symbols = ("AAPL", "MSFT", "BTCUSDT", "EURUSD", "US10Y")
        families = {
            "AAPL": "equity",
            "MSFT": "equity",
            "BTCUSDT": "crypto",
            "EURUSD": "forex",
            "US10Y": "fixed_income",
        }
        for sid in STRESS_SCENARIO_IDS:
            a = bind_stress_scenario(sid, symbols=symbols, asset_families=families, seed=42)
            b = bind_stress_scenario(sid, symbols=symbols, asset_families=families, seed=42)
            self.assertEqual(dict(a.shocks), dict(b.shocks), sid)
            self.assertEqual(a.seed, 42)
            self.assertEqual(a.status, "ASSUMED")

            c = bind_stress_scenario(sid, symbols=symbols, asset_families=families, seed=99)
            # Seeded scenarios that use jitter must differ; others may be identical.
            if sid in {"volatility_shock", "correlated_selloff"}:
                self.assertNotEqual(dict(a.shocks), dict(c.shocks), sid)

            positions = {
                "AAPL": {"qty": 10, "side": "LONG"},
                "BTCUSDT": {"qty": 1, "side": "LONG"},
            }
            marks = {"AAPL": 100.0, "BTCUSDT": 50_000.0}
            r1 = run_stress_scenario(
                scenario_id=sid,
                positions=positions,
                marks=marks,
                cash=1_000.0,
                asset_families=families,
                seed=7,
            )
            r2 = run_stress_scenario(
                scenario_id=sid,
                positions=positions,
                marks=marks,
                cash=1_000.0,
                asset_families=families,
                seed=7,
            )
            self.assertEqual(r1.measurement, "ASSUMED", sid)
            self.assertEqual(r1.pnl, r2.pnl, sid)
            self.assertEqual(r1.shocked_equity, r2.shocked_equity, sid)
            self.assertIn("stress_scenario_is_not_a_forecast", r1.notes)


class ScenarioRiskW6MissingInputTests(unittest.TestCase):
    def test_missing_inputs_unmeasured_not_fake_pass(self) -> None:
        missing_cases = [
            run_stress_scenario(
                scenario_id="equity_crash",
                positions=None,
                marks={"AAPL": 100.0},
                cash=0.0,
            ),
            run_stress_scenario(
                scenario_id="equity_crash",
                positions={"AAPL": {"qty": 1, "side": "LONG"}},
                marks=None,
                cash=0.0,
            ),
            run_stress_scenario(
                scenario_id="equity_crash",
                positions={"AAPL": {"qty": 1, "side": "LONG"}},
                marks={"AAPL": 100.0},
                cash=None,
            ),
            run_stress_scenario(
                scenario_id="equity_crash",
                positions={},
                marks={"AAPL": 100.0},
                cash=0.0,
            ),
            run_stress_scenario(
                scenario_id="equity_crash",
                positions={"AAPL": {"qty": 5, "side": "LONG"}},
                marks={},  # no mark and no avg_entry
                cash=0.0,
            ),
        ]
        for result in missing_cases:
            self.assertEqual(result.measurement, "UNMEASURED")
            self.assertNotEqual(result.measurement, "PASS")
            pub = result.public_dict()
            self.assertEqual(pub["measurement"], "UNMEASURED")
            self.assertTrue(pub["truth"]["missing_data_is_UNMEASURED"])
            # Must not claim a fabricated green/pass outcome.
            self.assertNotIn(pub["measurement"], {"PASS", "MEASURED", "OBSERVED"})

    def test_unknown_scenario_unmeasured(self) -> None:
        spec = bind_stress_scenario("not_a_real_scenario", symbols=["AAPL"], seed=1)
        self.assertEqual(spec.status, "UNMEASURED")
        result = run_stress_scenario(
            scenario_id="not_a_real_scenario",
            positions={"AAPL": {"qty": 1, "side": "LONG"}},
            marks={"AAPL": 10.0},
            cash=0.0,
            seed=1,
        )
        self.assertEqual(result.measurement, "UNMEASURED")


class RiskGuardKillSwitchClarityTests(unittest.TestCase):
    def test_kill_switch_state_is_clear(self) -> None:
        guard = RiskGuard(RiskLimits())
        state = guard.kill_switch_state()
        self.assertTrue(state["clear"])
        self.assertFalse(state["armed"])
        self.assertIsNone(state["reason"])

        guard.arm_kill_switch("drawdown")
        armed = guard.kill_switch_state()
        self.assertTrue(armed["armed"])
        self.assertFalse(armed["clear"])
        self.assertEqual(armed["reason"], "drawdown")

        guard.clear_kill_switch("operator_reset")
        cleared = guard.kill_switch_state()
        self.assertTrue(cleared["clear"])
        self.assertFalse(cleared["armed"])
        self.assertIsNone(cleared["reason"])
        self.assertFalse(guard.limits.kill_switch_armed)
        self.assertFalse(guard.killed)


class LiveTradingBlockedRegression(unittest.TestCase):
    def test_live_trading_still_blocked(self) -> None:
        from Data.modules.market_sim.trading_live_guard import LiveTradingGuard
        from Data.modules.market_sim.types import MarketSimError

        guard = LiveTradingGuard()
        status = guard.public_status()
        self.assertEqual(status["LIVE_TRADING_AVAILABLE"], "BLOCKED")
        with self.assertRaises(MarketSimError) as ctx:
            guard.place_live_order(symbol="BTCUSDT", side="buy", qty=1)
        self.assertEqual(ctx.exception.code, "LIVE_TRADING_BLOCKED")


if __name__ == "__main__":
    unittest.main()
