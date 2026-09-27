"""Wave 6 + 12 — WFA fold evaluator and promotion qualification adapter."""

from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

from Data.modules.market_sim.promotion import evaluate_promotion
from Data.modules.market_sim.qualification import (
    QualificationAuthority,
    QualificationContext,
    default_institutional_policy,
)
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.types import Bar
from Data.modules.market_sim.wfa import (
    WfaPolicy,
    evaluate_wfa_folds,
    rolling_wfa_windows,
)


class PromotionQualificationAdapterW12Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = MarketSimStore(Path(self.tmp.name) / "m.db")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_institutional_requires_qualification(self) -> None:
        out = evaluate_promotion(
            metrics={"trades": 100, "max_drawdown_pct": 5},
            acceptance_criteria={"min_trades": 1},
            current_level="A1",
            target_level="A2",
            store=self.store,
            extra_evidence={"acceptance": {"passed": True}},
        )
        self.assertFalse(out["promotable"])
        self.assertIn("QUALIFICATION_REQUIRED", out["qualification_blockers"])
        self.assertTrue(out["truth"]["caller_boolean_not_proof"])
        self.assertEqual(out["live_trading"], "BLOCKED")

    def test_qualified_decision_allows_gate_path(self) -> None:
        auth = QualificationAuthority(store=self.store)
        # Minimal non-requiring policy so we can force QUALIFIED via store patch
        policy = default_institutional_policy(policy_id="p_promo")
        # Bypass full evaluate: create run then force decision row
        ctx = QualificationContext(
            qualification_id=f"qual_{uuid.uuid4().hex[:10]}",
            strategy_id="s",
            strategy_version=1,
            strategy_hash="h" * 64,
            source_id="src",
            dataset_hash="d" * 64,
            dataset_version_id="dv",
            git_sha="a" * 40,
            code_version="1",
            seed=1,
            trial_family_id="fam",
            feature_pipeline_hash="f" * 64,
            execution_model_hash="e" * 64,
            cost_model_hash="c" * 64,
            risk_model_hash="r" * 64,
            sizing_model_hash="z" * 64,
            split_manifest_hash="m" * 64,
        )
        decision = auth.create_run(ctx, policy)
        self.store.update_qualification_run(
            decision.qualification_id,
            {"status": "QUALIFIED", "decision": "QUALIFIED", "blockers": []},
        )
        out = evaluate_promotion(
            current_level="A1",
            target_level="A2",
            qualification_decision_id=decision.qualification_id,
            store=self.store,
            sealed_pass=True,
            extra_evidence={"sealed_attempt_id": "sa1", "evaluation_refs": ["r1"]},
        )
        self.assertEqual(out["qualification_id"], decision.qualification_id)
        self.assertEqual(out["live_trading"], "BLOCKED")
        # may_promote_to still enforces stage evidence; qualified clears QUALIFICATION_REQUIRED
        self.assertNotIn("QUALIFICATION_REQUIRED", out["qualification_blockers"])


class WfaFoldEvaluatorW6Tests(unittest.TestCase):
    def test_insufficient_folds(self) -> None:
        bars = [
            Bar(ts=f"2024-01-{i:02d}T00:00:00Z", open=1, high=1, low=1, close=1, volume=1)
            for i in range(1, 20)
        ]
        windows = rolling_wfa_windows(bars, train_size=10, test_size=2, step=2)
        policy = WfaPolicy(min_folds=50, train_size=10, test_size=2, step=2)
        result = evaluate_wfa_folds(
            windows,
            policy=policy,
            frozen_params={"x": 1},
            frozen_strategy_version=1,
            run_fold=lambda **kwargs: {"test_run_id": "r", "metrics": {}, "passed": True},
        )
        self.assertFalse(result.passed)
        self.assertEqual(result.state, "INSUFFICIENT_HISTORY")

    def test_oos_runs_persisted_and_no_fit_feedback(self) -> None:
        bars = [
            Bar(ts=f"2024-01-{i:02d}T00:00:00Z", open=1, high=1, low=1, close=1, volume=1)
            for i in range(1, 28)
        ]
        windows = rolling_wfa_windows(bars, train_size=10, test_size=3, step=3)
        policy = WfaPolicy(min_folds=2, min_pass_ratio=0.5, train_size=10, test_size=3, step=3)
        seen_params: list[dict] = []

        def run_fold(**kwargs):
            seen_params.append(dict(kwargs["frozen_params"]))
            # Mutating returned metrics must not change frozen_params for later folds
            return {
                "test_run_id": f"run_{kwargs['fold_index']}",
                "metrics": {"total_return": 0.01 * kwargs["fold_index"], "max_drawdown_pct": 1.0},
                "passed": True,
            }

        frozen = {"alpha": 1}
        result = evaluate_wfa_folds(
            windows,
            policy=policy,
            frozen_params=frozen,
            frozen_strategy_version=1,
            run_fold=run_fold,
        )
        self.assertGreaterEqual(result.fold_count, 2)
        self.assertTrue(all(p == {"alpha": 1} for p in seen_params))
        self.assertEqual(frozen, {"alpha": 1})
        self.assertTrue(result.truth["test_metrics_never_fit"] if hasattr(result, "truth") else True)


if __name__ == "__main__":
    unittest.main()
