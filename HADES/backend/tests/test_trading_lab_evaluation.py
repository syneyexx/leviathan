"""Evaluation: metrics, selection correction and refusal to overclaim.

Verification note (2026-09-17): VERIFIED_ON_HOST via
`python3 -m unittest discover -s backend/tests -p 'test_trading*.py' -v`
on Linux Cloud Agent (Python 3.12). See docs/TRADING_LAB.md §8 and docs/CURRENT_STATUS.md.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trading_lab.evaluation import (
    EvaluationInput,
    PromotionCriteria,
    RunSummaryInput,
    block_bootstrap_interval,
    build_report,
    compare_runs,
    deflated_sharpe,
    max_drawdown,
    returns_from_curve,
    sharpe_ratio,
    stress_scenarios,
    summarise,
)


def curve(values: list[float], *, start_hour: int = 0) -> list[tuple[str, float]]:
    return [
        (f"2020-01-{1 + (start_hour + index) // 24:02d}T{(start_hour + index) % 24:02d}:00:00+00:00", value)
        for index, value in enumerate(values)
    ]


class MetricsTest(unittest.TestCase):
    def test_returns_are_simple_period_returns(self) -> None:
        returns = returns_from_curve(curve([100.0, 110.0, 99.0]))
        self.assertEqual(len(returns), 2)
        self.assertAlmostEqual(returns[0], 0.1, places=9)
        self.assertAlmostEqual(returns[1], -0.1, places=9)

    def test_a_flat_curve_has_no_sharpe_instead_of_a_division_by_zero(self) -> None:
        self.assertIsNone(sharpe_ratio([0.0, 0.0, 0.0]))

    def test_max_drawdown_is_measured_from_the_running_peak(self) -> None:
        drawdown, _ = max_drawdown(curve([100.0, 120.0, 60.0, 90.0]))
        self.assertAlmostEqual(drawdown, 0.5, places=6)

    def test_deflated_sharpe_falls_as_the_number_of_trials_grows(self) -> None:
        single = deflated_sharpe(0.2, trials=1, observations=500)
        many = deflated_sharpe(0.2, trials=500, observations=500)
        self.assertIsNotNone(single)
        self.assertIsNotNone(many)
        self.assertLess(many, single, "searching harder must lower the confidence, not raise it")

    def test_bootstrap_interval_is_deterministic_for_a_seed(self) -> None:
        returns = [0.01, -0.005, 0.02, 0.0, -0.01] * 20
        first = block_bootstrap_interval(returns, "mean", seed=11)
        second = block_bootstrap_interval(returns, "mean", seed=11)
        self.assertEqual(first, second)

    def test_summarise_marks_a_short_curve_as_insufficient(self) -> None:
        metrics = summarise(RunSummaryInput(label="tiny", split="development", equity_curve=curve([100.0, 101.0])))
        self.assertTrue(metrics.insufficient_evidence)


class VerdictTest(unittest.TestCase):
    def fold(self, label: str, values: list[float], *, trades: int = 50) -> object:
        return summarise(
            RunSummaryInput(
                label=label,
                split="validation",
                equity_curve=curve(values),
                trades=trades,
                timeframe="1h",
            )
        )

    def test_lookahead_violations_fail_the_report_outright(self) -> None:
        report = build_report(
            EvaluationInput(
                report_id="rep_1",
                strategy_id="str_1",
                strategy_version=1,
                folds=[self.fold("f1", [100.0 + index for index in range(400)])],
                fold_returns=[[0.001] * 400],
                lookahead_violations=["future_event:X@2020-01-01T00:00:00+00:00"],
            )
        )
        self.assertEqual(report.verdict, "fail")
        self.assertTrue(any("lookahead" in reason for reason in report.verdict_reasons))

    def test_too_few_trades_yields_insufficient_evidence_not_a_pass(self) -> None:
        report = build_report(
            EvaluationInput(
                report_id="rep_2",
                strategy_id="str_1",
                strategy_version=1,
                folds=[self.fold("f1", [100.0 + index for index in range(400)], trades=1)],
                fold_returns=[[0.001] * 400],
                criteria=PromotionCriteria(min_folds=1),
            )
        )
        self.assertEqual(report.verdict, "insufficient_evidence")

    def test_a_single_fold_is_not_enough_for_a_pass(self) -> None:
        report = build_report(
            EvaluationInput(
                report_id="rep_3",
                strategy_id="str_1",
                strategy_version=1,
                folds=[self.fold("f1", [100.0 + index for index in range(400)])],
                fold_returns=[[0.001] * 400],
            )
        )
        self.assertNotEqual(report.verdict, "pass")

    def test_the_report_always_records_the_trial_count_and_limitations(self) -> None:
        report = build_report(
            EvaluationInput(
                report_id="rep_4",
                strategy_id="str_1",
                strategy_version=1,
                folds=[self.fold("f1", [100.0 + index for index in range(400)])],
                fold_returns=[[0.001] * 400],
                search_trials_considered=250,
            )
        )
        self.assertEqual(report.search_trials_considered, 250)
        self.assertIn("250", report.multiple_testing_note)
        self.assertTrue(report.simulator_limitations, "a report must state what the simulator cannot model")
        self.assertEqual(report.evaluator_role, "independent_validator")

    def test_stress_scenarios_are_declared_and_non_empty(self) -> None:
        scenarios = stress_scenarios()
        self.assertTrue(scenarios)
        for scenario in scenarios:
            self.assertIn("scenario", scenario)
            self.assertIn("cost_overrides", scenario)

    def test_compare_runs_states_the_difference_and_refuses_to_call_it_significant(self) -> None:
        comparison = compare_runs(
            {"net_return": 0.10, "sharpe": 1.0, "trades": 40},
            {"net_return": 0.11, "sharpe": 1.01, "trades": 44},
        )
        rows = {row["metric"]: row for row in comparison["rows"]}
        self.assertAlmostEqual(rows["net_return"]["delta"], 0.01, places=6)
        self.assertEqual(rows["trades"]["delta"], 4)
        self.assertIn("not tested for significance", comparison["note"])


if __name__ == "__main__":  # pragma: no cover - manual execution only
    unittest.main()
