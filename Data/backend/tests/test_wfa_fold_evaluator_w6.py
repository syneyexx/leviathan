"""Wave 6 — WFA fold evaluator (train-fit / test-run separation)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from typing import Any

from Data.modules.market_sim.institutional_core.status import MeasurementState
from Data.modules.market_sim.types import Bar
from Data.modules.market_sim.wfa import (
    WfaPolicy,
    evaluate_acceptance_from_run,
    evaluate_wfa_folds,
    rolling_wfa_windows,
    walk_forward_plan,
)


def _bars(n: int) -> list[Bar]:
    dt0 = datetime(2020, 1, 1, tzinfo=timezone.utc)
    out: list[Bar] = []
    for i in range(n):
        ts = (dt0 + timedelta(hours=i)).isoformat(timespec="seconds")
        out.append(Bar(ts=ts, open=100.0, high=101.0, low=99.0, close=100.0 + i * 0.01, volume=1.0))
    return out


class WfaFoldEvaluatorW6Tests(unittest.TestCase):
    def test_keeps_legacy_window_helpers(self) -> None:
        bars = _bars(80)
        windows = rolling_wfa_windows(bars, train_size=20, test_size=5, step=5, purge_bars=1)
        self.assertGreaterEqual(len(windows), 1)
        plan = walk_forward_plan(bars, mode="rolling", train_size=20, test_size=5)
        self.assertEqual(plan["mode"], "rolling")
        sealed = evaluate_acceptance_from_run(
            {
                "run_id": "r1",
                "metrics": {
                    "trade_count": {"value": 10, "status": "MEASURED"},
                    "total_return_pct": {"value": 5.0, "status": "MEASURED"},
                    "max_drawdown_pct": {"value": 2.0, "status": "MEASURED"},
                },
            },
            criteria={"min_trades": 5, "max_drawdown_pct": 20.0, "min_total_return_pct": 0.0},
        )
        self.assertTrue(sealed.passed)

    def test_insufficient_folds_is_insufficient_history(self) -> None:
        bars = _bars(30)
        policy = WfaPolicy(
            mode="rolling",
            train_size=20,
            validation_size=0,
            test_size=10,
            step=10,
            purge_bars=0,
            embargo_bars=0,
            min_folds=5,
            min_pass_ratio=0.5,
            max_worst_fold_drawdown_pct=None,
            max_dispersion=None,
        )

        def run_fold(**kwargs: Any) -> dict[str, Any]:
            raise AssertionError("run_fold must not be called when folds are insufficient")

        result = evaluate_wfa_folds(bars, policy=policy, run_fold=run_fold)
        self.assertEqual(result.state, MeasurementState.INSUFFICIENT_HISTORY)
        self.assertFalse(result.passed)
        self.assertIn("INSUFFICIENT_HISTORY", result.blockers)

    def test_train_fit_never_sees_test_metrics(self) -> None:
        bars = _bars(120)
        policy = WfaPolicy(
            mode="rolling",
            train_size=30,
            validation_size=5,
            test_size=10,
            step=10,
            purge_bars=1,
            embargo_bars=1,
            min_folds=2,
            min_pass_ratio=0.5,
            max_worst_fold_drawdown_pct=50.0,
            max_dispersion=None,
        )
        seen_fit_ranges: list[tuple[str, str]] = []
        seen_test_ranges: list[tuple[str, str]] = []
        fit_params_log: list[dict[str, Any]] = []

        def fit_fold(**kwargs: Any) -> dict[str, Any]:
            train_range = kwargs["train_range"]
            seen_fit_ranges.append(train_range)
            # Must not receive test metrics / test bars.
            self.assertNotIn("test_metrics", kwargs)
            self.assertNotIn("bars_test", kwargs)
            params = {"alpha": len(seen_fit_ranges)}
            fit_params_log.append(params)
            return {"frozen_params": params, "train_run_id": f"train-{len(seen_fit_ranges)}"}

        def run_fold(**kwargs: Any) -> dict[str, Any]:
            seen_test_ranges.append(kwargs["test_range"])
            frozen = dict(kwargs["frozen_params"])
            # Frozen params come from fit only.
            self.assertIn("alpha", frozen)
            fold_i = int(kwargs["fold_index"])
            return {
                "test_run_id": f"test-{fold_i}",
                "metrics": {
                    "trade_count": {"value": 12, "status": "MEASURED"},
                    "total_return_pct": {"value": 3.0 + fold_i, "status": "MEASURED"},
                    "max_drawdown_pct": {"value": 4.0, "status": "MEASURED"},
                },
            }

        result = evaluate_wfa_folds(
            bars,
            policy=policy,
            fit_fold=fit_fold,
            run_fold=run_fold,
            frozen_strategy_version=7,
            acceptance_criteria={
                "min_trades": 5,
                "max_drawdown_pct": 20.0,
                "min_total_return_pct": 0.0,
            },
        )
        self.assertGreaterEqual(result.fold_count, 2)
        self.assertEqual(len(seen_fit_ranges), result.fold_count)
        self.assertEqual(len(seen_test_ranges), result.fold_count)
        # Chronological: each test starts after its train.
        for fit_r, test_r in zip(seen_fit_ranges, seen_test_ranges):
            self.assertLess(fit_r[1], test_r[0])
        self.assertTrue(result.passed)
        self.assertEqual(result.state, MeasurementState.PASS)
        self.assertEqual(result.folds[0].frozen_strategy_version, 7)
        self.assertEqual(result.folds[0].frozen_params["alpha"], 1)
        # Test metrics must not have mutated later fit params (each fold independent).
        self.assertEqual([p["alpha"] for p in fit_params_log], list(range(1, result.fold_count + 1)))

    def test_optional_store_upsert_wfa_fold(self) -> None:
        bars = _bars(80)
        policy = WfaPolicy(
            mode="rolling",
            train_size=20,
            validation_size=0,
            test_size=5,
            step=5,
            purge_bars=0,
            embargo_bars=0,
            min_folds=2,
            min_pass_ratio=0.5,
            max_worst_fold_drawdown_pct=None,
            max_dispersion=None,
        )
        persisted: list[dict[str, Any]] = []

        class _Store:
            def upsert_wfa_fold(self, row: dict[str, Any]) -> dict[str, Any]:
                persisted.append(dict(row))
                return row

        def run_fold(**kwargs: Any) -> dict[str, Any]:
            return {
                "test_run_id": f"t-{kwargs['fold_index']}",
                "metrics": {
                    "trade_count": {"value": 8, "status": "MEASURED"},
                    "total_return_pct": {"value": 1.0, "status": "MEASURED"},
                    "max_drawdown_pct": {"value": 1.0, "status": "MEASURED"},
                },
            }

        result = evaluate_wfa_folds(
            bars,
            policy=policy,
            run_fold=run_fold,
            store=_Store(),
            qualification_id="q-1",
            strategy_id="s-1",
            acceptance_criteria={
                "min_trades": 5,
                "max_drawdown_pct": 20.0,
                "min_total_return_pct": 0.0,
            },
        )
        self.assertEqual(len(persisted), result.fold_count)
        self.assertEqual(persisted[0]["qualification_id"], "q-1")
        self.assertEqual(persisted[0]["strategy_id"], "s-1")

    def test_store_without_upsert_is_fine(self) -> None:
        bars = _bars(60)
        policy = WfaPolicy(
            mode="rolling",
            train_size=20,
            validation_size=0,
            test_size=5,
            step=5,
            purge_bars=0,
            embargo_bars=0,
            min_folds=1,
            min_pass_ratio=0.0,
            max_worst_fold_drawdown_pct=None,
            max_dispersion=None,
        )

        class _BareStore:
            pass

        def run_fold(**kwargs: Any) -> dict[str, Any]:
            return {
                "test_run_id": "t0",
                "metrics": {
                    "trade_count": {"value": 8, "status": "MEASURED"},
                    "total_return_pct": {"value": 1.0, "status": "MEASURED"},
                    "max_drawdown_pct": {"value": 1.0, "status": "MEASURED"},
                },
            }

        result = evaluate_wfa_folds(
            bars,
            policy=policy,
            run_fold=run_fold,
            store=_BareStore(),
            acceptance_criteria={
                "min_trades": 5,
                "max_drawdown_pct": 20.0,
                "min_total_return_pct": 0.0,
            },
        )
        self.assertGreaterEqual(result.fold_count, 1)


if __name__ == "__main__":
    unittest.main()
