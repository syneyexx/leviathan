"""Wave 12 — promotion qualification adapter (store integration tests)."""

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


class PromotionStoreIntegrationW12Tests(unittest.TestCase):
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
        self.assertEqual(out["live_trading"], "BLOCKED")

    def test_qualified_decision_from_store(self) -> None:
        auth = QualificationAuthority(store=self.store)
        policy = default_institutional_policy(policy_id="p_promo")
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
        self.assertNotIn("QUALIFICATION_REQUIRED", out["qualification_blockers"])
        self.assertEqual(out["live_trading"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
