"""T5 — Science layer: metrics v2, trial ledger, WFA/purged CV/CPCV, sealed acceptance, FDR."""

from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.engine import SimulationEngine
from Data.modules.market_sim.experiments import (
    cpcv_splits,
    evaluate_acceptance,
    purged_cv_splits,
    robustness_report,
    walk_forward_splits,
)
from Data.modules.market_sim.metrics import (
    bootstrap_metric_cis,
    compute_metrics,
    periods_per_year_for_timeframe,
)
from Data.modules.market_sim.multi_engine import MultiAgentEngine
from Data.modules.market_sim.science import (
    benjamini_hochberg,
    calibrate_trial_family,
    power_analysis,
)
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore, utc_now
from Data.modules.market_sim.types import MarketSimError, MetricStatus, SimFill, SimRun


class MetricsV2Tests(unittest.TestCase):
    def test_timeframe_annualization_table(self) -> None:
        self.assertEqual(periods_per_year_for_timeframe("1D"), 252.0)
        self.assertAlmostEqual(periods_per_year_for_timeframe("1h"), 365.25 * 24)
        self.assertGreater(periods_per_year_for_timeframe("1m"), periods_per_year_for_timeframe("1h"))

    def test_engines_pass_periods_per_year(self) -> None:
        self.assertIn("periods_per_year", inspect.getsource(SimulationEngine._finalize_metrics))
        self.assertIn("periods_per_year", inspect.getsource(MultiAgentEngine._finalize_metrics))

    def test_ledger_derived_win_rate(self) -> None:
        equity = [100.0, 110.0, 105.0]
        fills = [
            {"side": "BUY", "qty": 1, "price": 100, "fee": 0, "realized_delta": 0.0},
            {"side": "SELL", "qty": 1, "price": 110, "fee": 0, "realized_delta": 10.0},
            {"side": "SELL", "qty": 1, "price": 90, "fee": 0, "realized_delta": -5.0},
        ]
        m = compute_metrics(equity=equity, fills=fills, initial_cash=100.0, bootstrap=False)
        self.assertEqual(m["win_rate"]["status"], MetricStatus.MEASURED.value)
        self.assertAlmostEqual(m["win_rate"]["value"], 0.5)
        self.assertEqual(m["profit_factor"]["status"], MetricStatus.MEASURED.value)
        self.assertIn("trade_count", m)
        self.assertEqual(m["trade_count"]["value"], 3)

    def test_bootstrap_cis(self) -> None:
        returns = [0.01, -0.005, 0.02, 0.0, 0.015, -0.01, 0.008] * 3
        ci = bootstrap_metric_cis(returns, n_boot=200, seed=7)
        self.assertEqual(ci["status"], MetricStatus.MEASURED.value)
        self.assertEqual(ci["sharpe"]["status"], MetricStatus.MEASURED.value)
        self.assertLessEqual(ci["sharpe"]["ci_low"], ci["sharpe"]["ci_high"])

    def test_simfill_public_dict_has_realized_delta(self) -> None:
        fill = SimFill(
            fill_id="f",
            run_id="r",
            bar_index=0,
            ts="t",
            side="SELL",
            qty=1,
            price=10,
            fee=0,
            slippage=0,
            agent_id=None,
            rationale="",
            status="FILLED",
            created_at=utc_now(),
            realized_delta=1.25,
        )
        self.assertEqual(fill.public_dict()["realized_delta"], 1.25)


class TrialLedgerTests(unittest.TestCase):
    def test_append_only_ledger_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketSimStore(Path(tmp) / "db.sqlite")
            store.initialize()
            trial = {
                "trial_id": "t-ledger-1",
                "strategy_id": "s1",
                "strategy_version": 1,
                "hypothesis": "h",
                "proposer_agent_id": "human",
                "data_hash": "h",
                "fingerprint": "fp-l1",
                "status": "proposed",
                "config": {},
                "split": {},
                "results": {},
                "acceptance_criteria": {},
                "rejection_reason": "",
                "seed": 1,
                "created_at": utc_now(),
                "finished_at": None,
                "metadata": {},
            }
            store.append_trial(trial)
            trial2 = dict(trial)
            trial2["status"] = "rejected"
            trial2["rejection_reason"] = "nope"
            trial2["finished_at"] = utc_now()
            store.save_experiment(trial2)
            events = store.list_trial_events(trial_id="t-ledger-1")
            self.assertGreaterEqual(len(events), 2)
            kinds = [e["kind"] for e in events]
            self.assertTrue(any("trial_created" in k or "status:" in k for k in kinds))
            with store.connect() as conn:
                with self.assertRaises(Exception):
                    conn.execute(
                        "UPDATE market_trial_ledger SET status='x' WHERE event_id=?",
                        (events[0]["event_id"],),
                    )

    def test_append_trial_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketSimStore(Path(tmp) / "db.sqlite")
            store.initialize()
            trial = {
                "trial_id": "t-dup",
                "strategy_id": "s",
                "strategy_version": 1,
                "hypothesis": "h",
                "proposer_agent_id": "a",
                "data_hash": "d",
                "fingerprint": "fp-dup",
                "status": "proposed",
                "config": {},
                "split": {},
                "results": {},
                "acceptance_criteria": {},
                "rejection_reason": "",
                "seed": 1,
                "created_at": utc_now(),
                "finished_at": None,
                "metadata": {},
            }
            store.append_trial(trial)
            with self.assertRaises(ValueError):
                store.append_trial(trial)


class WalkForwardScienceTests(unittest.TestCase):
    def test_rolling_and_purged_and_cpcv(self) -> None:
        rolling = walk_forward_splits(100, window=20, step=10)
        self.assertGreaterEqual(len(rolling["windows"]), 2)

        purged = purged_cv_splits(100, n_folds=5, purge=3, embargo=2)
        self.assertEqual(len(purged["folds"]), 5)
        fold0 = purged["folds"][0]
        overlap = set(fold0["train_indices"]) & set(fold0["test_indices"])
        self.assertEqual(overlap, set())

        cpcv = cpcv_splits(120, n_groups=6, n_test_groups=2, purge=2, embargo=1)
        self.assertGreaterEqual(cpcv["n_paths"], 10)
        self.assertTrue(cpcv["truth"]["combinatorial_purged_cv"])

    def test_robustness_report(self) -> None:
        windows = [
            {"total_return": {"status": "MEASURED", "value": 0.1}},
            {"total_return": {"status": "MEASURED", "value": 0.05}},
            {"total_return": {"status": "MEASURED", "value": -0.02}},
        ]
        report = robustness_report(windows)
        self.assertEqual(report["status"], MetricStatus.MEASURED.value)
        self.assertEqual(report["n_measured"], 3)
        self.assertAlmostEqual(report["positive_share"], 2 / 3)


class SealedAcceptanceTests(unittest.TestCase):
    def test_rejects_without_run_ids(self) -> None:
        fake = {
            "trade_count": 100,
            "total_return_pct": 50.0,
            "max_drawdown_pct": 5.0,
            "excess_return_pct": 10.0,
        }
        ok, reason = evaluate_acceptance(fake, {"min_trades": 5, "beat_benchmark": True})
        self.assertFalse(ok)
        self.assertIn("run-derived", reason)

    def test_complete_experiment_seals_single_use(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = root / "markets"
            markets.mkdir()
            store = MarketSimStore(root / "db.sqlite")
            store.initialize()
            svc = MarketSimControlPlane(store, MarketDataStore(store, markets), enabled=True)

            run = SimRun(
                run_id="run-seal-1",
                status="COMPLETED",
                source_id="src",
                strategy_id="s",
                strategy_version=1,
                symbol="BTCUSDT",
                timeframe="1h",
                start_ts="2024-01-01T00:00:00+00:00",
                end_ts="2024-01-02T00:00:00+00:00",
                data_hash="abc",
                seed=1,
            )
            run.metrics = {
                "trade_count": {"status": "MEASURED", "value": 10},
                "total_return": {"status": "MEASURED", "value": 0.05},
                "max_drawdown": {"status": "MEASURED", "value": 0.02},
            }
            store.create_run(run)

            trial = {
                "trial_id": "trial-seal-1",
                "strategy_id": "s",
                "strategy_version": 1,
                "hypothesis": "h",
                "proposer_agent_id": "human",
                "data_hash": "abc",
                "fingerprint": "fp-seal",
                "status": "proposed",
                "config": {},
                "split": {},
                "results": {},
                "acceptance_criteria": {
                    "min_trades": 1,
                    "max_drawdown_pct": 50.0,
                    "min_total_return_pct": 0.0,
                },
                "rejection_reason": "",
                "seed": 1,
                "created_at": utc_now(),
                "finished_at": None,
                "metadata": {},
            }
            store.append_trial(trial)

            done = svc.complete_experiment("trial-seal-1", run_id="run-seal-1")
            self.assertEqual(done["status"], "passed")
            self.assertTrue(store.is_acceptance_run_sealed("run-seal-1"))

            trial2 = dict(trial)
            trial2["trial_id"] = "trial-seal-2"
            trial2["fingerprint"] = "fp-seal-2"
            store.append_trial(trial2)
            with self.assertRaises(MarketSimError) as ctx:
                svc.complete_experiment("trial-seal-2", run_id="run-seal-1")
            self.assertEqual(ctx.exception.code, "ACCEPTANCE_SEAL_REUSED")


class FdrPowerTests(unittest.TestCase):
    def test_benjamini_hochberg_discovers(self) -> None:
        p = [0.001, 0.4, 0.5, 0.6, 0.7]
        result = benjamini_hochberg(p, q=0.05, labels=["A", "B", "C", "D", "E"])
        self.assertGreaterEqual(result["n_discoveries"], 1)
        self.assertEqual(result["discoveries"][0]["label"], "A")

    def test_power_analysis_increases_with_n(self) -> None:
        low = power_analysis(effect_size=0.3, n=10, alpha=0.05)
        high = power_analysis(effect_size=0.3, n=200, alpha=0.05)
        self.assertGreater(high["power"], low["power"])
        self.assertTrue(low["underpowered"])

    def test_calibrate_trial_family(self) -> None:
        out = calibrate_trial_family(
            [0.01, 0.2],
            labels=["x", "y"],
            effect_sizes=[0.5, 0.1],
            sample_sizes=[50, 50],
        )
        self.assertIn("fdr", out)
        self.assertEqual(len(out["power"]), 2)


if __name__ == "__main__":
    unittest.main()
