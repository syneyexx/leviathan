"""Wave 2–3 — QualificationAuthority + MARKET persistence."""

from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

from Data.backend.db_upgrade import DOMAIN_MIGRATIONS, ensure_domain_schema
from Data.modules.common.database_domains import DatabaseDomain
from Data.modules.market_sim.qualification import (
    GATE_ORDER,
    QualificationAuthority,
    QualificationContext,
    default_institutional_policy,
    hash_policy,
)
from Data.modules.market_sim.store import MarketSimStore


class QualificationPersistenceW3Tests(unittest.TestCase):
    def test_market_domain_v3_fresh_and_idempotent(self) -> None:
        versions = [m.version for m in DOMAIN_MIGRATIONS]
        self.assertIn(3, versions)
        self.assertEqual(versions, sorted(versions))
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "market.db"
            ensure_domain_schema(path, DatabaseDomain.MARKET)
            ensure_domain_schema(path, DatabaseDomain.MARKET)  # idempotent
            store = MarketSimStore(path)
            store.initialize()
            # Tables exist via store methods
            pol = store.save_qualification_policy(
                {
                    "policy_id": "p1",
                    "version": 1,
                    "name": "t",
                    "policy_hash": "h" * 64,
                    "policy_json": {"name": "t"},
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "created_by": "test",
                }
            )
            self.assertEqual(pol["policy_id"], "p1")
            got = store.get_qualification_policy("p1")
            self.assertIsNotNone(got)
            self.assertEqual(got["policy_hash"], "h" * 64)


class QualificationAuthorityW2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "market.db"
        self.store = MarketSimStore(path)
        self.store.initialize()
        self.auth = QualificationAuthority(store=self.store)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _ctx(self, **overrides) -> QualificationContext:
        base = dict(
            qualification_id=f"qual_{uuid.uuid4().hex[:12]}",
            strategy_id="strat_a",
            strategy_version=1,
            strategy_hash="s" * 64,
            source_id="src1",
            dataset_id="ds1",
            dataset_version_id="dsv1",
            dataset_hash="d" * 64,
            git_sha="a" * 40,
            code_version="1.0.0",
            seed=7,
            trial_family_id="fam1",
            feature_pipeline_hash="f" * 64,
            execution_model_hash="e" * 64,
            cost_model_hash="c" * 64,
            risk_model_hash="r" * 64,
            sizing_model_hash="z" * 64,
            split_manifest_hash="m" * 64,
        )
        base.update(overrides)
        return QualificationContext(**base)  # type: ignore[arg-type]

    def test_policy_hash_immutable(self) -> None:
        p1 = default_institutional_policy(policy_id="pol_a", version=1)
        p2 = default_institutional_policy(policy_id="pol_b", version=1)
        # Same thresholds → same content hash regardless of policy_id
        self.assertEqual(hash_policy(p1), hash_policy(p2))
        p3 = default_institutional_policy(policy_id="pol_c", version=1, name="other")
        # name is part of policy body → different hash
        self.assertNotEqual(hash_policy(p1), hash_policy(p3))

    def test_create_and_fail_closed_without_evidence(self) -> None:
        policy = default_institutional_policy(policy_id="pol_fc")
        ctx = self._ctx()
        decision = self.auth.create_run(ctx, policy)
        self.assertEqual(decision.state, "CREATED")
        self.assertFalse(decision.qualified)
        out = self.auth.evaluate(decision.qualification_id)
        self.assertFalse(out.qualified)
        self.assertIn(out.state, {"BLOCKED", "REJECTED", "FAILED"})
        # Prior hard failure should BLOCK later gates, not PASS them
        by_id = {g.gate_id: g for g in out.gate_results}
        self.assertEqual(len(out.gate_results), len(GATE_ORDER))
        # First failing required gate; subsequent blocked
        seen_fail = False
        for gid in GATE_ORDER:
            g = by_id[gid]
            if seen_fail:
                self.assertEqual(g.state, "BLOCKED")
                self.assertFalse(g.passed)
            elif not g.passed:
                seen_fail = True

    def test_caller_passed_boolean_cannot_qualify(self) -> None:
        policy = default_institutional_policy(policy_id="pol_bool")
        ctx = self._ctx(
            extra={
                "acceptance": {"passed": True},
                "sealed_pass": True,
                "metrics": {"trades": 100, "max_drawdown_pct": 5.0},
                "split_role": "TRAIN",
            }
        )
        decision = self.auth.create_run(ctx, policy)
        out = self.auth.evaluate(decision.qualification_id)
        self.assertFalse(out.qualified)
        # TRAIN-only must never qualify
        self.assertTrue(
            any("TRAIN" in b or "SEALED" in b or "REPRODUCIBILITY" in b or "DATA" in b for b in out.blockers)
            or any(not g.passed for g in out.gate_results)
        )

    def test_gate_order_fixed(self) -> None:
        self.assertEqual(GATE_ORDER[0], "Q01_DATA_CERTIFICATION")
        self.assertEqual(GATE_ORDER[-1], "Q11_PORTFOLIO_COMPATIBILITY")
        self.assertEqual(len(GATE_ORDER), 11)


if __name__ == "__main__":
    unittest.main()
