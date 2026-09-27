"""Wave 35 — institutional research E2E (qualification → promotion denial without evidence).

Uses production QualificationAuthority + promotion adapter. External network mocked only.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.market_sim.promotion import evaluate_promotion
from Data.modules.market_sim.qualification import (
    QualificationAuthority,
    QualificationContext,
    default_institutional_policy,
)
from Data.modules.market_sim.store import MarketSimStore


class InstitutionalQualificationE2EW35Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "market.db"
        self.store = MarketSimStore(db)
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _ctx(self, **kw) -> QualificationContext:
        base = dict(
            qualification_id="qual_e2e_1",
            experiment_id="exp1",
            learning_run_id="lr1",
            candidate_id="cand1",
            strategy_id="strat1",
            strategy_version=1,
            strategy_hash="s" * 64,
            source_id="src1",
            dataset_id="ds1",
            dataset_version_id="v1",
            dataset_hash="d" * 64,
            git_sha="a" * 40,
            code_version="1.0.0",
            seed=7,
            sealed_attempt_id=None,
            trial_family_id="family1",
            feature_pipeline_hash="f" * 64,
            execution_model_hash="e" * 64,
            cost_model_hash="c" * 64,
            risk_model_hash="r" * 64,
            sizing_model_hash="z" * 64,
            split_manifest_hash="m" * 64,
        )
        base.update(kw)
        return QualificationContext(**base)

    def test_missing_evidence_rejects_and_blocks_promotion(self) -> None:
        auth = QualificationAuthority(plane=None, store=self.store)
        policy = default_institutional_policy()
        decision = auth.create_run(self._ctx(), policy)
        evaluated = auth.evaluate(decision.qualification_id)
        self.assertFalse(evaluated.qualified)
        self.assertNotEqual(evaluated.state, "QUALIFIED")

        promo = evaluate_promotion(
            target_level="A3",
            qualification_decision_id=evaluated.qualification_id,
            store=self.store,
        )
        self.assertFalse(promo.get("promotable"))
        self.assertEqual(str(promo.get("live_trading") or "BLOCKED").upper(), "BLOCKED")

    def test_caller_passed_cannot_bypass(self) -> None:
        auth = QualificationAuthority(plane=None, store=self.store)
        decision = auth.create_run(
            self._ctx(qualification_id="qual_e2e_2"),
            default_institutional_policy(),
        )
        auth.evaluate(decision.qualification_id)
        promo = evaluate_promotion(
            target_level="A3",
            extra_evidence={"acceptance": {"passed": True}},
            store=self.store,
        )
        self.assertFalse(promo.get("promotable"))


if __name__ == "__main__":
    unittest.main()
