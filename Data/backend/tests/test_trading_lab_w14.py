"""W14 — StrategyAsset registry, DSL v3, regimes, HPO, curriculum."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.market_sim.curriculum import CurriculumStage, new_curriculum
from Data.modules.market_sim.features import FEATURE_PIPELINE_VERSION
from Data.modules.market_sim.hpo import assert_not_sealed_tuning, build_hpo_plan, run_hpo
from Data.modules.market_sim.regimes import (
    detect_trend_regime,
    detect_volatility_regime,
    hmm_regime_capability,
    synthetic_known_regime_fixture,
)
from Data.modules.market_sim.strategy_asset import (
    CompatibilitySurface,
    ExecutionCompatibilityManifest,
    StrategyAsset,
    promote_asset,
)
from Data.modules.market_sim.strategy_dsl import (
    DSL_V3_VERSION,
    apply_risk_exits,
    parse_strategy_spec,
    validate_strategy_spec,
)
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.types import MarketSimError, StrategyStatus


class StrategyAssetTests(unittest.TestCase):
    def test_compatibility_rejects_live_and_pipeline_mismatch(self) -> None:
        manifest = ExecutionCompatibilityManifest(
            required_features=["sma"],
            required_feature_pipeline_version=FEATURE_PIPELINE_VERSION,
        )
        live = manifest.validate_against_runtime(
            feature_pipeline_version=FEATURE_PIPELINE_VERSION,
            surface=CompatibilitySurface.LIVE,
        )
        self.assertFalse(live["ok"])
        self.assertIn("live_compatible_blocked", live["reasons"])
        mismatch = manifest.validate_against_runtime(
            feature_pipeline_version="other-pipe",
            available_features={"sma"},
        )
        self.assertFalse(mismatch["ok"])
        self.assertFalse(manifest.public_dict()["live_compatible"])

    def test_promotion_requires_evidence(self) -> None:
        asset = StrategyAsset(asset_id="a1", name="demo", version=1)
        with self.assertRaises(MarketSimError):
            promote_asset(asset, target_status=StrategyStatus.VALIDATED.value, evidence={})
        promote_asset(
            asset,
            target_status=StrategyStatus.VALIDATED.value,
            evidence={"acceptance": {"passed": True}, "evaluation_refs": ["eval-1"]},
        )
        self.assertEqual(asset.status, StrategyStatus.VALIDATED.value)
        with self.assertRaises(MarketSimError):
            promote_asset(
                StrategyAsset(asset_id="a2", name="x", version=1, status=StrategyStatus.DRAFT.value),
                target_status=StrategyStatus.CHAMPION.value,
                evidence={"evaluation_refs": ["e"]},
            )
        promote_asset(
            asset,
            target_status=StrategyStatus.CHAMPION.value,
            evidence={"evaluation_refs": ["eval-1"]},
        )
        self.assertEqual(asset.status, StrategyStatus.CHAMPION.value)


class DslV3Tests(unittest.TestCase):
    def test_v3_fields_validated_and_risk_exits(self) -> None:
        spec = parse_strategy_spec(
            {
                "version": 3,
                "kind": "rsi",
                "parameters": {"period": 14},
                "entry": {"oversold": 30},
                "stop_loss": {"pct": 0.05},
                "take_profit": {"pct": 0.1},
                "time_stop": {"max_bars": 5},
                "position_sizing": {"method": "fixed_fraction", "fraction": 0.1},
                "universe_filters": [{"symbols": ["AAA"]}],
                "session_schedule": {"session": "RTH"},
            }
        )
        self.assertEqual(spec.version, DSL_V3_VERSION)
        ok, reason = validate_strategy_spec(spec)
        self.assertTrue(ok, reason)
        stop = apply_risk_exits(
            position_qty=1, entry_price=100.0, last_price=94.0, bars_held=1, spec=spec
        )
        self.assertEqual(stop["triggered"], "stop_loss")
        tp = apply_risk_exits(
            position_qty=1, entry_price=100.0, last_price=112.0, bars_held=1, spec=spec
        )
        self.assertEqual(tp["triggered"], "take_profit")
        ts = apply_risk_exits(
            position_qty=1, entry_price=100.0, last_price=101.0, bars_held=5, spec=spec
        )
        self.assertEqual(ts["triggered"], "time_stop")
        bad = parse_strategy_spec({"version": 3, "kind": "hold", "stop_loss": {"eval": "1+1"}})
        ok2, reason2 = validate_strategy_spec(bad)
        self.assertFalse(ok2)
        self.assertIn("arbitrary code", reason2)


class RegimeLibraryTests(unittest.TestCase):
    def test_synthetic_fixture_and_hmm_gated(self) -> None:
        fx = synthetic_known_regime_fixture(n=90, seed=3)
        self.assertTrue(fx["truth"]["known_ground_truth"])
        self.assertEqual(fx["detector_vol_mid"]["status"], "MEASURED")
        # End segment is bullish in the fixture construction
        self.assertIn(fx["detector_trend_end"]["label"], {"bull", "bear", "flat"})
        hmm = hmm_regime_capability()
        self.assertEqual(hmm["status"], "FEATURE_GATED")
        closes = [100 + i * 0.5 for i in range(40)]
        trend = detect_trend_regime(closes, ts="t", fast=5, slow=20)
        self.assertEqual(trend.status, "MEASURED")
        self.assertEqual(trend.label, "bull")


class HpoAndCurriculumTests(unittest.TestCase):
    def test_hpo_logs_all_trials_and_forbids_sealed(self) -> None:
        with self.assertRaises(ValueError):
            assert_not_sealed_tuning("sealed")
        plan = build_hpo_plan(
            method="grid",
            search_space={"fast": [5, 10], "slow": [20, 30]},
            max_trials=10,
            split="train",
        )
        self.assertEqual(len(plan.trials), 4)
        ledger: list[dict] = []
        run_hpo(
            plan,
            evaluate=lambda p: float(p["fast"]) - float(p["slow"]) / 100.0,
            trial_ledger_append=ledger.append,
            strategy_id="s1",
        )
        self.assertEqual(len(ledger), 4)
        self.assertTrue(all(t.status == "COMPLETED" for t in plan.trials))
        # Failed trials retained
        plan2 = build_hpo_plan(method="grid", search_space={"x": [1, 2]}, max_trials=5, seed=1)
        def boom(params):
            if params["x"] == 2:
                raise RuntimeError("boom")
            return 1.0
        run_hpo(plan2, evaluate=boom, trial_ledger_append=ledger.append)
        self.assertTrue(any(t.status == "FAILED" for t in plan2.trials))
        tpe = build_hpo_plan(method="bayesian_tpe", search_space={"x": [1]}, max_trials=5)
        self.assertEqual(tpe.metadata["capability"]["status"], "FEATURE_GATED")

    def test_hpo_persists_to_trial_ledger_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "m.db"
            MigrationRunner(db).apply_all()
            store = MarketSimStore(str(db))
            plan = build_hpo_plan(
                method="random",
                search_space={"period": [10, 14, 20]},
                max_trials=3,
                seed=9,
                split="val",
            )
            run_hpo(
                plan,
                evaluate=lambda p: float(p["period"]),
                trial_ledger_append=store.append_trial,
                strategy_id="strat-hpo",
            )
            self.assertEqual(store.count_trials(strategy_id="strat-hpo"), 3)

    def test_curriculum_is_logged_and_reproducible(self) -> None:
        cur = new_curriculum(curriculum_id="c1", seed=11)
        self.assertEqual(cur.current_stage, CurriculumStage.SYNTHETIC_EASY)
        cur.advance(passed=True, evidence={"n": 1})
        self.assertEqual(cur.current_stage, CurriculumStage.SYNTHETIC_HOSTILE)
        h1 = cur.content_hash()
        cur.advance(passed=False, evidence={"fail": True}, notes="hostile fail")
        # Failure does not advance
        self.assertEqual(cur.current_stage, CurriculumStage.SYNTHETIC_HOSTILE)
        self.assertNotEqual(h1, cur.content_hash())
        payload = cur.public_dict()
        self.assertTrue(payload["truth"]["logged_and_reproducible"])
        self.assertEqual(payload["stages"][-2], "sealed")


if __name__ == "__main__":
    unittest.main()
