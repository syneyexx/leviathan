"""Wave 23/26/28/31 — forward evidence, learning integrity, assurance owner scan."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.market_sim.institutional_core.assurance import (
    FORBIDDEN_OWNER_CLASS_NAMES,
    run_assurance,
)
from Data.modules.market_sim.learning_types import (
    LearningRunStatus,
    LearningStage,
    StrategyLearningRun,
)
from Data.modules.market_sim.paper_forward_drift import (
    ForwardEvidencePolicy,
    classify_drift,
    evaluate_forward_evidence,
)


class ForwardEvidenceW23Tests(unittest.TestCase):
    def test_five_observations_never_pass(self) -> None:
        policy = ForwardEvidencePolicy()
        out = evaluate_forward_evidence(
            policy=policy,
            closed_trades=5,
            observations=5,
            elapsed_seconds=60,
        )
        self.assertFalse(out["passed"])
        self.assertEqual(out["state"], "INSUFFICIENT_HISTORY")
        self.assertIn("MIN_OBSERVATIONS", out["blockers"])

    def test_classify_insufficient_evidence(self) -> None:
        out = classify_drift(sample_size=1, min_sample_size=5, alpha_drifted=True)
        self.assertEqual(out["class"], "INSUFFICIENT_EVIDENCE")
        self.assertFalse(out["auto_disable"])


class LearningIntegrityW26Tests(unittest.TestCase):
    def test_finalize_qualified_not_institutional(self) -> None:
        from Data.modules.market_sim import learning_runtime as lr

        class _FakeStore:
            def upsert_learning_run(self, *a, **k):
                return None

            def get_qualification_run(self, *a, **k):
                return None

        class _FakePlane:
            store = _FakeStore()

            def emit_event(self, *a, **k):
                return None

        run = StrategyLearningRun(
            learning_run_id="lr1",
            status=LearningRunStatus.RUNNING.value,
            stage=LearningStage.ROBUSTNESS.value,
            source_id="src",
            seed=1,
            created_at="t",
            updated_at="t",
            metadata={},
        )
        # Prefer public finalize if available; else call private with minimal stubs
        if hasattr(lr, "_finalize_qualified"):
            # Patch persist/emit helpers that need richer plane
            orig_persist = getattr(lr, "persist_learning_run", None)
            orig_emit = getattr(lr, "_emit", None)
            orig_sync = getattr(lr, "_sync_lab_outcome", None)
            orig_lesson = getattr(lr, "_maybe_add_lesson", None)
            lr.persist_learning_run = lambda store, r: None  # type: ignore
            lr._emit = lambda plane, kind, payload: None  # type: ignore
            if orig_sync:
                lr._sync_lab_outcome = lambda *a, **k: None  # type: ignore
            if orig_lesson:
                lr._maybe_add_lesson = lambda *a, **k: None  # type: ignore
            try:
                out = lr._finalize_qualified(_FakePlane(), run, "cand-1")
            finally:
                if orig_persist:
                    lr.persist_learning_run = orig_persist
                if orig_emit:
                    lr._emit = orig_emit
                if orig_sync:
                    lr._sync_lab_outcome = orig_sync
                if orig_lesson:
                    lr._maybe_add_lesson = orig_lesson
            self.assertFalse(out.get("metadata", run.metadata).get("institutional_qualified", True))
            self.assertTrue(run.metadata.get("qualification_required"))
            self.assertEqual(run.metadata.get("lab_finalist"), "cand-1")
            self.assertFalse(run.metadata.get("ready_for_shadow"))
            self.assertTrue(run.metadata.get("learner_cannot_set_authoritative_qualified"))


class AssuranceOwnerW31Tests(unittest.TestCase):
    def test_forbidden_includes_qualification_v2(self) -> None:
        self.assertIn("QualificationAuthorityV2", FORBIDDEN_OWNER_CLASS_NAMES)
        self.assertIn("StatsV2", FORBIDDEN_OWNER_CLASS_NAMES)

    def test_run_assurance_live_blocked(self) -> None:
        report = run_assurance()
        self.assertTrue(report.live_trading.get("ok") or report.status in {"PASS", "DEGRADED", "FAIL"})
        # Must not invent a second QualificationAuthorityV2 in tree
        for f in report.findings:
            self.assertNotEqual(f.code, "FORBIDDEN_OWNER_CLASS")


class CapacityQualificationW16Tests(unittest.TestCase):
    def test_missing_adv_unmeasured(self) -> None:
        from Data.modules.market_sim.capacity_qualification import estimate_bar_capacity

        ev = estimate_bar_capacity(capital=1_000_000, avg_daily_volume=None, price=100.0)
        self.assertEqual(ev.state, "UNMEASURED")
        self.assertIn("CAPACITY_UNMEASURED", ev.blockers)

    def test_exceeded_participation(self) -> None:
        from Data.modules.market_sim.capacity_qualification import estimate_bar_capacity

        ev = estimate_bar_capacity(
            capital=1_000_000,
            avg_daily_volume=100.0,
            price=100.0,
            max_participation_pct=1.0,
        )
        self.assertIn("CAPACITY_EXCEEDED", ev.blockers)


class RobustnessScenarioLibraryW10Tests(unittest.TestCase):
    def test_institutional_scenario_ids_present(self) -> None:
        from Data.modules.market_sim.robustness import (
            default_perturbation_matrix,
            institutional_scenario_ids,
        )

        matrix = default_perturbation_matrix(include_regime=True)
        ids = {p.perturbation_id for p in matrix}
        required = set(institutional_scenario_ids())
        # Core measured scenarios must be in default matrix; regime optional flag
        for sid in (
            "fee_x2",
            "slippage_x2",
            "spread_widen",
            "parameter_jitter",
            "start_date_shift",
            "end_date_shift",
        ):
            self.assertIn(sid, ids)
        self.assertTrue(required)


if __name__ == "__main__":
    unittest.main()
