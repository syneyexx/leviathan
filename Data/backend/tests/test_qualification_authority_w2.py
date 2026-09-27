"""Wave 2 — QualificationAuthority policy immutability + fail-closed gates."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.institutional_core.status import MeasurementState
from Data.modules.market_sim.qualification import (
    GATE_ORDER,
    QualificationAuthority,
    QualificationContext,
    default_institutional_policy,
    hash_policy,
)
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore


def _plane(tmp: Path) -> MarketSimControlPlane:
    db = tmp / "market.db"
    store = MarketSimStore(db)
    store.initialize()
    data = MarketDataStore(store, tmp / "markets")
    return MarketSimControlPlane(store, data, enabled=False)


def _context(qid: str = "qual-w2-1") -> QualificationContext:
    return QualificationContext(
        qualification_id=qid,
        experiment_id=None,
        learning_run_id=None,
        candidate_id=None,
        strategy_id="strat-a",
        strategy_version=1,
        strategy_hash="shash",
        source_id="src-1",
        dataset_id="ds-1",
        dataset_version_id="dsv-1",
        dataset_hash="dhash",
        git_sha="abc123",
        code_version="1.0.0",
        seed=42,
        sealed_attempt_id=None,
        trial_family_id="family-1",
    )


class QualificationAuthorityWave2Tests(unittest.TestCase):
    def test_policy_hash_immutable_and_stable(self) -> None:
        p1 = default_institutional_policy(policy_id="pol-a", version=1)
        p2 = default_institutional_policy(policy_id="pol-b", version=1)
        # Same thresholds → same content hash (policy_id excluded).
        self.assertEqual(hash_policy(p1), hash_policy(p2))
        p3 = replace(p1, max_pbo=0.9)
        self.assertNotEqual(hash_policy(p1), hash_policy(p3))
        # Frozen: cannot mutate fields in place.
        with self.assertRaises(Exception):
            p1.max_pbo = 0.1  # type: ignore[misc]

    def test_create_and_evaluate_fail_closed_without_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane = _plane(Path(tmp))
            auth = QualificationAuthority(plane, plane.store)
            policy = default_institutional_policy(policy_id="pol-fc")
            ctx = _context("qual-fc-1")
            created = auth.create_run(ctx, policy)
            self.assertEqual(created.state, "CREATED")
            self.assertFalse(created.qualified)
            self.assertTrue(created.policy_hash)
            self.assertEqual(created.policy_hash, hash_policy(policy))

            # Persisted policy hash must not change after create.
            stored = plane.store.get_qualification_policy(policy.policy_id)
            assert stored is not None
            self.assertEqual(stored["policy_hash"], created.policy_hash)

            decision = auth.evaluate(ctx.qualification_id)
            self.assertFalse(decision.qualified)
            self.assertIn(decision.state, {"BLOCKED", "REJECTED", "FAILED"})
            self.assertEqual(len(decision.gate_results), len(GATE_ORDER))
            # First required gate fails closed → later gates BLOCKED (not PASS).
            first = decision.gate_results[0]
            self.assertFalse(first.passed)
            self.assertNotEqual(first.state, MeasurementState.PASS.value)
            later = decision.gate_results[1:]
            self.assertTrue(later, msg="expected later gates after hard failure")
            for g in later:
                self.assertFalse(g.passed)
                self.assertEqual(g.state, MeasurementState.BLOCKED.value)

    def test_caller_cannot_inject_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane = _plane(Path(tmp))
            auth = QualificationAuthority(plane, plane.store)
            policy = default_institutional_policy(policy_id="pol-inj")
            ctx = _context("qual-inj-1")
            # Caller tries to smuggle acceptance.passed=True via context.extra.
            ctx.extra["acceptance"] = {"passed": True}
            ctx.extra["passed"] = True
            auth.create_run(ctx, policy)
            decision = auth.evaluate(ctx.qualification_id)
            self.assertFalse(decision.qualified)
            # No gate may be PASS solely because of caller boolean.
            for g in decision.gate_results:
                if g.passed:
                    self.fail(f"gate {g.gate_id} passed without evidence under caller injection")
            # Explicit single-gate path also rejects caller boolean as authority.
            q01 = auth.evaluate_gate(ctx.qualification_id, "Q01")
            self.assertFalse(q01.passed)


if __name__ == "__main__":
    unittest.main()
