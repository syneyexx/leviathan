"""Wave 8/22/27 — data certification, TCA matching, qualification worker capability."""

from __future__ import annotations

import unittest

from Data.modules.execution.builtins import build_default_catalog
from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES
from Data.modules.market_sim.institutional_core.data_governance import (
    DataCertificationPolicy,
    certify_dataset_from_evidence,
)
from Data.modules.market_sim.institutional_core.status import MeasurementState
from Data.modules.market_sim.institutional_core.tca import (
    ExecutionObservation,
    ExecutionPrediction,
    match_execution_gap,
)


class DataCertificationW8Tests(unittest.TestCase):
    def test_caller_boolean_alone_not_certified(self) -> None:
        cert = certify_dataset_from_evidence(
            dataset_id="d1",
            dataset_version_id="v1",
            dataset_hash="h" * 64,
            evidence={"certified": True},
            policy=DataCertificationPolicy(require_pit=True),
        )
        self.assertNotEqual(cert.certification_state, MeasurementState.PASS.value)
        self.assertIn("CALLER_BOOLEAN_NOT_CERTIFICATION", cert.blockers)

    def test_bar_evidence_can_pass(self) -> None:
        cert = certify_dataset_from_evidence(
            dataset_id="d1",
            dataset_version_id="v1",
            dataset_hash="h" * 64,
            evidence={
                "content_hash": "c" * 64,
                "source_id": "csv_local",
                "timestamp_normalized": True,
                "ordering_ok": True,
                "duplicate_handling": "drop",
                "gap_report": {"gap_ratio": 0.01},
                "ohlc_invariants_ok": True,
                "available_at_semantics": True,
                "license_state": "PUBLIC_TERMS_APPLY",
            },
            policy=DataCertificationPolicy(
                require_pit=True,
                require_historical_universe=False,
                require_revision_lineage=False,
                require_corporate_actions=False,
                require_license_known=True,
            ),
            source_id="csv_local",
        )
        self.assertEqual(cert.certification_state, MeasurementState.PASS.value)
        self.assertEqual(cert.pit_state, MeasurementState.PASS.value)


class TcaMatchingW22Tests(unittest.TestCase):
    def test_unmatched_stays_unmeasured(self) -> None:
        pred = ExecutionPrediction(
            decision_id="d1",
            order_id="o1",
            symbol="AAPL",
            side="BUY",
            qty=10,
            predicted_slippage_bps=5.0,
            execution_model_id="bar_v1",
            execution_model_version="1",
        )
        gap = match_execution_gap(pred, None)
        self.assertFalse(gap.matched)
        self.assertEqual(gap.state, MeasurementState.UNMEASURED.value)

    def test_lineage_match(self) -> None:
        pred = ExecutionPrediction(
            decision_id="d1",
            order_id="o1",
            symbol="AAPL",
            side="BUY",
            qty=10,
            predicted_slippage_bps=5.0,
            predicted_latency_ms=100.0,
            execution_model_id="bar_v1",
            execution_model_version="1",
        )
        obs = ExecutionObservation(
            paper_order_id="o1",
            matched_decision_id="d1",
            actual_fill_price=100.1,
            observed_spread_bps=7.0,
            observed_latency_ms=120.0,
            actual_fill_fraction=1.0,
        )
        gap = match_execution_gap(pred, obs)
        self.assertTrue(gap.matched)
        self.assertEqual(gap.state, MeasurementState.OBSERVED.value)
        self.assertAlmostEqual(gap.slippage_gap_bps or 0, 2.0)


class QualificationWorkerCapabilityW27Tests(unittest.TestCase):
    def test_capability_registered(self) -> None:
        cat = build_default_catalog()
        self.assertIsNotNone(cat.get("market_sim.qualification_run"))
        self.assertIn("market_sim.qualification_run", EXTERNAL_WORKER_CAPABILITIES)
        self.assertIsNotNone(cat.get("market_sim.portfolio_risk.loosen"))
        loosen = cat.get("market_sim.portfolio_risk.loosen")
        self.assertTrue((loosen.metadata or {}).get("approval_identity"))


if __name__ == "__main__":
    unittest.main()
