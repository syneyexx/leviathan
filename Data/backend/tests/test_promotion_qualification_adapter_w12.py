"""Wave 12 — promotion.py QualificationDecision adapter."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any

from Data.modules.market_sim.promotion import evaluate_promotion
from Data.modules.market_sim.types import MarketSimError


def _passing_metrics() -> dict[str, Any]:
    return {
        "trade_count": {"value": 10, "status": "MEASURED"},
        "total_return_pct": {"value": 5.0, "status": "MEASURED"},
        "max_drawdown_pct": {"value": 2.0, "status": "MEASURED"},
    }


def _criteria() -> dict[str, Any]:
    return {"min_trades": 5, "max_drawdown_pct": 20.0, "min_total_return_pct": 0.0}


def _qualified(qid: str = "qual-1") -> SimpleNamespace:
    return SimpleNamespace(
        qualification_id=qid,
        qualified=True,
        state="QUALIFIED",
        blockers=[],
    )


def _failed(qid: str = "qual-bad") -> SimpleNamespace:
    return SimpleNamespace(
        qualification_id=qid,
        qualified=False,
        state="FAILED",
        blockers=["Q04_WALK_FORWARD"],
    )


class PromotionQualificationAdapterW12Tests(unittest.TestCase):
    def test_a1_legacy_path_without_qualification(self) -> None:
        ok = evaluate_promotion(
            metrics=_passing_metrics(),
            acceptance_criteria=_criteria(),
            current_level="A0",
            target_level="A1",
        )
        self.assertTrue(ok["promotable"])
        self.assertEqual(ok["path"], "legacy_non_institutional")
        self.assertEqual(ok["live_trading"], "BLOCKED")
        self.assertFalse(ok["truth"]["institutional_lifecycle_write"])
        self.assertIn("qualification_id", ok)
        self.assertIn("qualification_state", ok)
        self.assertIn("qualification_blockers", ok)

    def test_institutional_target_requires_qualification(self) -> None:
        blocked = evaluate_promotion(
            metrics=_passing_metrics(),
            acceptance_criteria=_criteria(),
            current_level="A1",
            target_level="A2",
            sealed_pass=True,
            extra_evidence={
                "sealed_attempt_id": "seal-1",
                "acceptance": {
                    "passed": True,
                    "run_id": "r1",
                    "metrics": _passing_metrics(),
                    "sealed_attempt_id": "seal-1",
                },
            },
        )
        self.assertFalse(blocked["promotable"])
        self.assertEqual(blocked["reason"], "QUALIFICATION_REQUIRED")
        self.assertEqual(blocked["gate"]["reason"], "QUALIFICATION_REQUIRED")
        self.assertEqual(blocked["live_trading"], "BLOCKED")

    def test_caller_acceptance_cannot_override_missing_qualification(self) -> None:
        # Scientific entry A1→A2: caller passed=true cannot bypass missing qualification.
        blocked = evaluate_promotion(
            current_level="A1",
            target_level="A2",
            sealed_pass=True,
            extra_evidence={
                "acceptance": {"passed": True, "run_id": "fake", "metrics": _passing_metrics()},
                "sealed_attempt_id": "seal-1",
            },
        )
        self.assertFalse(blocked["promotable"])
        self.assertEqual(blocked["reason"], "QUALIFICATION_REQUIRED")

    def test_a3_operational_path_without_qualification(self) -> None:
        # Wave 23: A3 may be operational when shadow receipts exist; not institutional write.
        out = evaluate_promotion(
            current_level="A2",
            target_level="A3",
            shadow_run_id="shadow-1",
            paper_shadow_pass=True,
            extra_evidence={
                "shadow_run_id": "shadow-1",
                "paper_shadow_pass": True,
                "shadow_receipt": {"status": "MEASURED", "shadow_run_id": "shadow-1"},
            },
        )
        self.assertTrue(out["promotable"])
        self.assertEqual(out["path"], "operational_paper")
        self.assertFalse(out["truth"]["institutional_lifecycle_write"])
        self.assertEqual(out["live_trading"], "BLOCKED")

    def test_failed_qualification_blocks_even_with_caller_pass(self) -> None:
        blocked = evaluate_promotion(
            current_level="A2",
            target_level="A3",
            shadow_run_id="shadow-1",
            qualification_decision=_failed(),
            extra_evidence={
                "acceptance": {"passed": True, "run_id": "r1", "metrics": _passing_metrics()},
            },
        )
        self.assertFalse(blocked["promotable"])
        self.assertEqual(blocked["reason"], "QUALIFICATION_REQUIRED")
        self.assertEqual(blocked["qualification_id"], "qual-bad")
        self.assertIn("Q04_WALK_FORWARD", blocked["qualification_blockers"])

    def test_qualified_decision_allows_institutional_when_stage_evidence_ok(self) -> None:
        ok = evaluate_promotion(
            metrics=_passing_metrics(),
            acceptance_criteria=_criteria(),
            current_level="A1",
            target_level="A2",
            sealed_pass=True,
            qualification_decision=_qualified("qual-ok"),
            extra_evidence={"sealed_attempt_id": "seal-1"},
        )
        self.assertTrue(ok["promotable"])
        self.assertEqual(ok["qualification_id"], "qual-ok")
        self.assertEqual(ok["qualification_state"], "QUALIFIED")
        self.assertEqual(ok["path"], "institutional")
        self.assertEqual(ok["live_trading"], "BLOCKED")

    def test_a3_still_needs_shadow_run_id(self) -> None:
        blocked = evaluate_promotion(
            current_level="A2",
            target_level="A3",
            qualification_decision=_qualified(),
            extra_evidence={
                "acceptance": {"passed": True, "run_id": "r1", "metrics": _passing_metrics()},
            },
        )
        self.assertFalse(blocked["promotable"])
        self.assertNotEqual(blocked.get("reason"), "QUALIFICATION_REQUIRED")

    def test_a4_still_needs_paper_deployment_id(self) -> None:
        blocked = evaluate_promotion(
            current_level="A3",
            target_level="A4",
            shadow_run_id="shadow-1",
            qualification_decision=_qualified(),
            extra_evidence={
                "acceptance": {"passed": True, "run_id": "r1", "metrics": _passing_metrics()},
            },
        )
        self.assertFalse(blocked["promotable"])

    def test_a5_still_impossible(self) -> None:
        with self.assertRaises(MarketSimError):
            evaluate_promotion(current_level="A4", target_level="A5")

    def test_resolve_qualification_from_store_by_id(self) -> None:
        class _Store:
            def get_qualification_run(self, qid: str) -> dict[str, Any]:
                assert qid == "qual-store"
                return {
                    "qualification_id": "qual-store",
                    "decision": "QUALIFIED",
                    "status": "QUALIFIED",
                    "blockers": [],
                }

        ok = evaluate_promotion(
            metrics=_passing_metrics(),
            acceptance_criteria=_criteria(),
            current_level="A1",
            target_level="A2",
            sealed_pass=True,
            qualification_decision_id="qual-store",
            store=_Store(),
            extra_evidence={"sealed_attempt_id": "seal-1"},
        )
        self.assertTrue(ok["promotable"])
        self.assertEqual(ok["qualification_id"], "qual-store")

    def test_legacy_demo_never_writes_institutional_lifecycle(self) -> None:
        demo = evaluate_promotion(
            metrics=_passing_metrics(),
            acceptance_criteria=_criteria(),
            current_level="A1",
            target_level="A2",
            sealed_pass=True,
            legacy_demo=True,
            extra_evidence={"sealed_attempt_id": "seal-1"},
        )
        self.assertEqual(demo["path"], "legacy_non_institutional")
        self.assertTrue(demo["truth"]["non_institutional_path"])
        self.assertTrue(demo["truth"]["legacy_demo"])
        self.assertFalse(demo["truth"]["institutional_lifecycle_write"])


if __name__ == "__main__":
    unittest.main()
