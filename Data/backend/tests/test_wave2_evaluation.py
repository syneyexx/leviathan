"""Wave 2 — Evaluation as release authority (U321–U340)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.evaluation import (
    EvalCase,
    EvalOutcome,
    EvaluationHarness,
    EvaluationPlatform,
    EvaluationStore,
    JudgmentKind,
    MeasurementState,
    RegressionCase,
    build_scorecard,
    measurement_is_pass,
)
from Data.modules.execution import build_default_catalog
from Data.modules.release import GateSeverity, evaluation_relevance_gate


class MeasurementHonestyTests(unittest.TestCase):
    def test_unmeasured_is_never_pass(self) -> None:
        self.assertFalse(measurement_is_pass(MeasurementState.UNMEASURED))
        self.assertFalse(measurement_is_pass(MeasurementState.PARTIAL))
        self.assertFalse(measurement_is_pass(MeasurementState.DEGRADED))
        self.assertTrue(measurement_is_pass(MeasurementState.PASS))

    def test_foundation_suite_exposes_judgment_and_measurement(self) -> None:
        harness = EvaluationHarness(catalog=build_default_catalog())
        report = harness.run_suite(
            "foundation",
            harness.default_foundation_suite(),
            suite_id="foundation",
        )
        embedding = next(r for r in report.results if r.case_id == "embedding-quality")
        self.assertEqual(embedding.outcome, EvalOutcome.UNMEASURED)
        self.assertEqual(embedding.resolved_measurement(), MeasurementState.UNMEASURED)
        self.assertEqual(embedding.judgment_kind, JudgmentKind.DETERMINISTIC)
        payload = report.public_dict()
        self.assertTrue(payload["truth"]["unmeasured_is_not_passed"])
        self.assertGreaterEqual(payload["measurement_summary"]["UNMEASURED"], 1)
        self.assertEqual(report.suite_id, "foundation")


class EvaluationStorePlatformTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "eval.db"
        MigrationRunner(self.db).apply_all()
        self.harness = EvaluationHarness(catalog=build_default_catalog())
        self.store = EvaluationStore(self.db)
        self.platform = EvaluationPlatform(
            harness=self.harness,
            store=self.store,
            enabled=True,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_persist_report_and_scorecard(self) -> None:
        report = self.platform.run_foundation(persist=True)
        self.assertIsNotNone(report.report_id)
        loaded = self.platform.get_report(report.report_id or "")
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded["suite_id"], "foundation")

        scorecard = self.platform.build_system_scorecard()
        self.assertTrue(scorecard.public_dict()["truth"]["unmeasured_is_not_passed"])
        # Foundation has UNMEASURED embedding → system is not PASS
        self.assertNotEqual(scorecard.system_measurement, MeasurementState.PASS)
        self.assertIn(
            scorecard.system_measurement,
            {
                MeasurementState.UNMEASURED,
                MeasurementState.PARTIAL,
            },
        )

    def test_regression_corpus_seeded_and_runnable(self) -> None:
        regs = self.platform.list_regressions()
        self.assertGreaterEqual(len(regs), 2)
        report = self.platform.run_regression_corpus(persist=True)
        self.assertEqual(report.suite_id, "regression")
        self.assertGreaterEqual(report.summary["total"], 2)
        unmeasured = next(
            r for r in report.results if r.case_id == "reg-unmeasured-invariant"
        )
        self.assertEqual(unmeasured.resolved_measurement(), MeasurementState.UNMEASURED)

    def test_promotion_requires_pass_not_unmeasured(self) -> None:
        self.platform.run_foundation(persist=True)
        promo = self.platform.promotion_gate(suite_id="foundation")
        self.assertTrue(promo["recorded"])
        self.assertFalse(promo["promotable"])  # UNMEASURED embedding blocks promotion
        self.assertTrue(promo["truth"]["unmeasured_is_not_passed"])

    def test_add_custom_regression(self) -> None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        item = RegressionCase(
            regression_id="reg-custom-1",
            title="Custom incident",
            incident_ref="inc-1",
            case=EvalCase(
                case_id="reg-custom-case",
                name="custom",
                description="custom regression",
                check="capability_exists",
                params={"capability_id": "file.read"},
                suite_id="regression",
                component="execution",
                sealed=True,
            ),
            created_at=now,
        )
        self.platform.add_regression(item)
        ids = {r["regression_id"] for r in self.platform.list_regressions()}
        self.assertIn("reg-custom-1", ids)


class ScorecardAggregationTests(unittest.TestCase):
    def test_empty_scorecard_is_unmeasured(self) -> None:
        card = build_scorecard([], name="empty", required_components=("evaluation",))
        self.assertEqual(card.system_measurement, MeasurementState.UNMEASURED)
        self.assertFalse(measurement_is_pass(card.system_measurement))


class ReleaseEvalGateTests(unittest.TestCase):
    def test_missing_eval_blocks(self) -> None:
        gate = evaluation_relevance_gate(
            {
                "recorded": False,
                "measurement": "UNMEASURED",
                "detail": "no relevant eval report recorded",
                "promotable": False,
            },
            severity=GateSeverity.BLOCK,
            require_pass=False,
        )
        self.assertFalse(gate.passed)

    def test_unmeasured_fails_require_pass(self) -> None:
        gate = evaluation_relevance_gate(
            {
                "recorded": True,
                "measurement": "UNMEASURED",
                "detail": "latest has unmeasured",
                "promotable": False,
            },
            severity=GateSeverity.BLOCK,
            require_pass=True,
        )
        self.assertFalse(gate.passed)
        self.assertIn("UNMEASURED", gate.detail)

    def test_pass_promotable(self) -> None:
        gate = evaluation_relevance_gate(
            {
                "recorded": True,
                "measurement": "PASS",
                "detail": "ok",
                "promotable": True,
            },
            severity=GateSeverity.BLOCK,
            require_pass=True,
        )
        self.assertTrue(gate.passed)


if __name__ == "__main__":
    unittest.main()
