"""Phase-2 vertical slice tests: regression candidates, stale evidence, info-gain."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claim_register import STALE, ClaimRegister
from gen2.flight_recorder import record
from gen2.regression_candidates import (
    REVIEW_PENDING,
    SPLIT_DEVELOPMENT,
    build_regression_candidate_from_flight,
    promote_candidate,
    run_effect_ledger_contradiction_case,
)
from gen2.store import Gen2Store
from platform_db import PlatformDatabase
from platform_services_core import KnowledgeService
from reasoning.information_gain import compare_efficiency, rank_research_steps
from runtime.effect_ledger import EffectLedger


class RegressionCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "gen2.db"))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_effect_ledger_case_passes_after_fix(self) -> None:
        result = run_effect_ledger_contradiction_case()
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["observed_class"], "REQUIRES_RECONCILIATION")
        self.assertEqual(result["split"], SPLIT_DEVELOPMENT)
        self.assertFalse(result["model_invoked"])

    def test_effect_ledger_case_fails_under_old_or_logic(self) -> None:
        """Pinned reproduction of the pre-fix SAFE_TO_RETRY bug via old OR rule."""
        with tempfile.TemporaryDirectory() as tmp:
            ledger = EffectLedger(Path(tmp) / "effects.db")
            rec = ledger.prepare(tool="t", arguments={"a": 1}, effect_class="plugin_side_effect")
            ledger.mark_failed(
                rec.effect_id,
                detail={"effect_applied": True, "failure_stage": "before_execute"},
            )
            record = ledger.get(rec.effect_id)
            assert record is not None
            detail = record.detail or {}
            stage = str(detail.get("failure_stage") or "").lower()
            effect_applied = detail.get("effect_applied")
            # Old buggy rule:
            old_safe = effect_applied is False or stage in {"before_execute", "validation", "policy"}
            self.assertTrue(old_safe)
            fixed = ledger.classify_on_restart(rec.effect_id)
            self.assertEqual(fixed["class"], "REQUIRES_RECONCILIATION")

    def test_failed_flight_becomes_pending_review_candidate(self) -> None:
        run_id = "run_fail_reg_1"
        record(self.store, run_id, "TOOL_RESULT", {"tool": "echo", "ok": False, "status": "failed"})
        record(self.store, run_id, "RUN_FAILED", {"status": "failed", "error_category": "tool_failed"})
        candidate = build_regression_candidate_from_flight(self.store, run_id)
        self.assertTrue(candidate.get("ok"), candidate)
        self.assertEqual(candidate.get("review_status"), REVIEW_PENDING)
        self.assertEqual(candidate.get("split"), SPLIT_DEVELOPMENT)
        self.assertTrue(candidate.get("dependencies", {}).get("forbid_external_mutations"))
        promoted = promote_candidate(candidate, approve=True)
        self.assertTrue(promoted.get("promoted_to_regression"))
        self.assertTrue(promoted.get("holdout_untouched"))


class StaleEvidenceInvalidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.reg = ClaimRegister(Path(self.temp.name) / "claims.db")
        # Point default register used by KnowledgeService at this temp register.
        import claim_register as cr

        self._prev = cr.default_claim_register
        cr.default_claim_register = self.reg
        self.db = PlatformDatabase(str(Path(self.temp.name) / "platform.db"))
        self.db.initialize()
        self.knowledge = KnowledgeService(self.db, Path(self.temp.name))

    def tearDown(self) -> None:
        import claim_register as cr

        cr.default_claim_register = self._prev
        self.reg.detach()
        self.temp.cleanup()

    def test_source_change_marks_only_dependent_claims(self) -> None:
        first = self.knowledge.ingest_text(
            title="Latency notes",
            text="Latency improved under load.",
            source_type="note",
            uri="local://latency",
        )
        source_id = first["id"]
        dependent = self.reg.add_claim(
            text="Latency improved",
            provenance=source_id,
            source_kind="derived_analysis",
        )
        self.reg.attach_evidence(
            dependent,
            evidence_id=source_id,
            relation="supports",
            source_hash=first["content_hash"],
        )
        independent = self.reg.add_claim(
            text="Unrelated fact",
            provenance="local://other",
            source_kind="primary",
            supports=["local://other"],
        )
        self.reg.attach_evidence(
            independent,
            evidence_id="local://other",
            relation="supports",
            source_hash="abc",
        )

        second = self.knowledge.ingest_text(
            title="Latency notes",
            text="Latency worsened under load.",
            source_type="note",
            uri="local://latency",
        )
        self.assertTrue(second.get("reimported"))
        self.assertGreaterEqual(second.get("dependent_claims_marked_for_recheck") or 0, 1)

        dep = self.reg.get(dependent)
        ind = self.reg.get(independent)
        assert dep is not None and ind is not None
        self.assertEqual(dep["verification_status"], STALE)
        self.assertTrue(dep.get("recheck_required"))
        self.assertTrue(dep.get("historical_snapshots"))
        self.assertNotEqual(ind["verification_status"], STALE)


class InformationGainTests(unittest.TestCase):
    def test_skips_duplicates_and_stops_on_acceptance(self) -> None:
        ranked = rank_research_steps(
            candidates=[
                {"query": "latency SLA region", "open_question": "What is the SLA?"},
                {"query": "latency SLA region", "open_question": "duplicate"},
            ],
            searched_queries=["latency SLA region"],
            known_evidence_text="",
        )
        self.assertEqual(ranked["selected"], [])
        self.assertTrue(any(s["skip_reason"] == "duplicate_searched_query" for s in ranked["skipped"]))

        stopped = rank_research_steps(
            candidates=[{"query": "anything new here"}],
            acceptance_satisfied=True,
        )
        self.assertEqual(stopped["stop_reason"], "acceptance_criteria_satisfied")
        self.assertTrue(stopped["mandatory_verification_preserved"])

    def test_prefers_contradiction_addressing_and_reports_budget(self) -> None:
        ranked = rank_research_steps(
            candidates=[
                {
                    "query": "explain latency conflict alpha beta",
                    "open_question": "Why do sources conflict on latency?",
                    "cost_tool_calls": 1,
                },
                {
                    "query": "unrelated weather forecast tomorrow",
                    "open_question": "Weather?",
                    "cost_tool_calls": 1,
                },
            ],
            searched_queries=[],
            known_evidence_text="alpha improved beta worsened",
            open_questions=["Why do sources conflict on latency?"],
            contradictions=["alpha ↔ beta latency"],
            remaining_tool_budget=1,
        )
        self.assertTrue(ranked["selected"])
        self.assertIn("conflict", ranked["selected"][0]["query"])

        over = rank_research_steps(
            candidates=[{"query": "needs more sources about SLA", "cost_tool_calls": 5}],
            remaining_tool_budget=1,
        )
        self.assertTrue(over["ask_for_budget_expansion"])
        self.assertTrue(over["mandatory_verification_preserved"])

    def test_efficiency_win_requires_quality(self) -> None:
        win = compare_efficiency(
            baseline={"tool_calls": 5, "tokens": 2000, "duration_ms": 9000},
            candidate={"tool_calls": 2, "tokens": 900, "duration_ms": 4000},
            quality_preserved=True,
        )
        self.assertTrue(win["efficiency_win"])
        lose = compare_efficiency(
            baseline={"tool_calls": 5, "tokens": 2000, "duration_ms": 9000},
            candidate={"tool_calls": 2, "tokens": 900, "duration_ms": 4000},
            quality_preserved=False,
        )
        self.assertFalse(lose["efficiency_win"])


if __name__ == "__main__":
    unittest.main()
