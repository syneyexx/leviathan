"""W15 — Autonomous agent training lab: scientific search, sealed lineage, tournaments."""

from __future__ import annotations

import unittest

from Data.modules.market_sim.agent_lab import (
    AcceptanceCriteria,
    LabOutcome,
    LessonTrust,
    assert_lineage_holdout_clean,
    elo_update,
    EloRating,
    evaluate_candidate_pipeline,
    export_lab_trajectory_for_training,
    finalize_lab,
    mark_sealed_revealed,
    new_agent_lab,
    register_qualified_asset,
    retrieve_lessons,
    run_tournament,
    store_lesson,
)
from Data.modules.market_sim.strategy_asset import StrategyAsset
from Data.modules.market_sim.types import MarketSimError, StrategyStatus


class ScientificAcceptanceTests(unittest.TestCase):
    def test_no_strategy_qualified_is_valid_pass(self) -> None:
        lab = new_agent_lab(lab_id="lab-1", acceptance=AcceptanceCriteria(min_trades=5, max_drawdown_pct=20))
        evaluate_candidate_pipeline(
            lab,
            strategy_id="s1",
            strategy_version=1,
            hypothesis="mean reversion",
            train_metrics={"trade_count": 10, "max_drawdown_pct": 5, "total_return_pct": 2},
            val_metrics={"trade_count": 2, "max_drawdown_pct": 5},  # fails min_trades
        )
        finalize_lab(lab)
        self.assertEqual(lab.outcome, LabOutcome.NO_STRATEGY_QUALIFIED.value)
        self.assertTrue(lab.public_dict()["truth"]["no_strategy_qualified_is_valid_pass"])
        self.assertTrue(lab.metadata["negative_result_valuable"])
        self.assertTrue(any(l.trust == LessonTrust.AGENT_PROPOSED.value for l in lab.lessons))

    def test_threshold_relaxation_forbidden(self) -> None:
        lab = new_agent_lab()
        with self.assertRaises(MarketSimError) as ctx:
            evaluate_candidate_pipeline(
                lab,
                strategy_id="s",
                strategy_version=1,
                hypothesis="x",
                train_metrics={},
                val_metrics={},
                relax_thresholds=True,
            )
        self.assertEqual(ctx.exception.code, "THRESHOLD_RELAXATION_FORBIDDEN")

    def test_qualified_path_and_register(self) -> None:
        crit = AcceptanceCriteria(min_trades=3, max_drawdown_pct=30, min_total_return_pct=1.0)
        lab = new_agent_lab(acceptance=crit)
        good = {"trade_count": 10, "max_drawdown_pct": 5, "total_return_pct": 8, "sharpe": 1.2}
        cand = evaluate_candidate_pipeline(
            lab,
            strategy_id="s2",
            strategy_version=1,
            hypothesis="breakout",
            train_metrics=good,
            val_metrics=good,
            robustness_metrics=good,
            sealed_metrics=good,
            sealed_attempt_id="att-1",
            sealed_dataset_id="ds-1",
        )
        self.assertTrue(cand.accepted)
        finalize_lab(lab)
        self.assertEqual(lab.outcome, LabOutcome.QUALIFIED_STRATEGY_FOUND.value)
        asset = StrategyAsset(asset_id="s2", name="breakout", version=1)
        register_qualified_asset(asset, evaluation_refs=[cand.candidate_id])
        self.assertEqual(asset.status, StrategyStatus.VALIDATED.value)


class SealedLineageTests(unittest.TestCase):
    def test_contaminated_lineage_refused(self) -> None:
        lab = new_agent_lab()
        mark_sealed_revealed(
            lab,
            strategy_id="s",
            parent_version=1,
            sealed_dataset_id="holdout-A",
            sealed_attempt_id="a1",
        )
        with self.assertRaises(MarketSimError) as ctx:
            assert_lineage_holdout_clean(
                lab, strategy_id="s", parent_version=1, sealed_dataset_id="holdout-A"
            )
        self.assertEqual(ctx.exception.code, "HOLDOUT_LINEAGE_CONTAMINATED")
        # New epoch/holdout is fine
        assert_lineage_holdout_clean(
            lab, strategy_id="s", parent_version=1, sealed_dataset_id="holdout-B"
        )


class TournamentAndTrajectoryTests(unittest.TestCase):
    def test_tournament_val_first_and_elo_honesty(self) -> None:
        crit = AcceptanceCriteria(min_trades=1, max_drawdown_pct=50)
        report = run_tournament(
            entrants=[
                {
                    "agent_id": "a",
                    "strategy_id": "sa",
                    "val_metrics": {"trade_count": 5, "max_drawdown_pct": 5, "total_return_pct": 10},
                    "sealed_metrics": {"trade_count": 5, "max_drawdown_pct": 5, "total_return_pct": 9},
                },
                {
                    "agent_id": "b",
                    "strategy_id": "sb",
                    "val_metrics": {"trade_count": 0, "max_drawdown_pct": 5},  # rejected pre sealed
                },
                {
                    "agent_id": "c",
                    "strategy_id": "sc",
                    "val_metrics": {"trade_count": 5, "max_drawdown_pct": 5, "total_return_pct": 3},
                    "sealed_metrics": {"trade_count": 5, "max_drawdown_pct": 5, "total_return_pct": 2},
                },
            ],
            criteria=crit,
        )
        self.assertEqual(len(report["rejected_pre_sealed"]), 1)
        self.assertEqual(report["ranking"][0]["agent_id"], "a")
        self.assertTrue(report["truth"]["elo_does_not_prove_profitability"])
        w, l = EloRating("w"), EloRating("l")
        elo_update(w, l)
        self.assertGreater(w.rating, l.rating)

    def test_trajectory_export_strips_private_cot(self) -> None:
        traj = {
            "trajectory_id": "t1",
            "run_id": "r1",
            "steps": [
                {
                    "observation": {"px": 1},
                    "action": {"side": "BUY"},
                    "reward": {"value": 0.1},
                    "done": False,
                    "private_cot": "secret",
                    "info": {"hidden_reasoning": "nope"},
                }
            ],
        }
        registered = []
        out = export_lab_trajectory_for_training(
            trajectory_public=traj,
            dataset_register=lambda a: registered.append(a) or {"status": "FILE_ONLY"},
        )
        self.assertEqual(out["measurement"], "MEASURED")
        step = out["artifact"]["steps"][0]
        self.assertNotIn("private_cot", step)
        self.assertNotIn("info", step)
        self.assertTrue(out["artifact"]["truth"]["no_hidden_cot"])
        self.assertEqual(len(registered), 1)

    def test_lesson_retrieve_before_new_candidate(self) -> None:
        lab = new_agent_lab()
        store_lesson(lab, claim="avoid chase", evidence_refs=["e1"], applies_to=["trend"])
        found = retrieve_lessons(lab.lessons, applies_to="trend")
        self.assertEqual(len(found), 1)
        evaluate_candidate_pipeline(
            lab,
            strategy_id="s",
            strategy_version=2,
            hypothesis="retry",
            train_metrics={"trade_count": 10, "max_drawdown_pct": 1},
            val_metrics={"trade_count": 10, "max_drawdown_pct": 1},
            robustness_metrics={"trade_count": 10, "max_drawdown_pct": 1},
        )
        self.assertTrue(lab.candidates[-1].metadata["prior_lesson_ids"])


if __name__ == "__main__":
    unittest.main()
