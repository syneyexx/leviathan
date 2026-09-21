"""Deterministic tests for claim/evidence verification states."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claim_register import (
    CLAIM_VERIFICATION_STATES,
    CONTRADICTED,
    PARTIALLY_SUPPORTED,
    STALE,
    SUPERSEDED,
    SUPPORTED,
    UNVERIFIED,
    ClaimRegister,
    assess_verification_state,
    derive_confidence_from_signals,
    honest_research_metric_kind,
    normalize_verification_status,
    register_research_contradiction_claims,
)
from research_coverage import summarize_research_coverage


class ClaimVerificationStateTests(unittest.TestCase):
    def test_canonical_states_exist(self) -> None:
        expected = {
            SUPPORTED,
            PARTIALLY_SUPPORTED,
            CONTRADICTED,
            UNVERIFIED,
            STALE,
            SUPERSEDED,
        }
        self.assertEqual(CLAIM_VERIFICATION_STATES, expected)
        self.assertEqual(normalize_verification_status("supported"), SUPPORTED)
        self.assertEqual(normalize_verification_status("partially-supported"), PARTIALLY_SUPPORTED)
        self.assertEqual(normalize_verification_status("revised"), UNVERIFIED)
        self.assertEqual(normalize_verification_status("superseded"), SUPERSEDED)

    def test_unverified_withholds_confidence(self) -> None:
        reg = ClaimRegister()
        cid = reg.add_claim(text="Sky is green", provenance="user:guess", source_kind="user")
        claim = reg.get(cid)
        assert claim is not None
        self.assertEqual(claim["verification_status"], UNVERIFIED)
        self.assertIsNone(claim["confidence"])
        self.assertEqual(claim["confidence_basis"], "observable_evidence_signals")

    def test_partial_then_supported_from_independent_evidence(self) -> None:
        reg = ClaimRegister()
        cid = reg.add_claim(
            text="HADES is offline-first",
            provenance="file:/docs/policy.md",
            source_kind="primary",
            supports=["file:/docs/policy.md"],
        )
        partial = reg.get(cid)
        assert partial is not None
        self.assertEqual(partial["verification_status"], PARTIALLY_SUPPORTED)
        self.assertEqual(partial["confidence"], 1.0)
        self.assertEqual(partial["confidence_basis"], "observable_evidence_signals")

        updated = reg.attach_evidence(cid, evidence_id="file:/docs/architecture.md", relation="supports")
        self.assertEqual(updated["verification_status"], SUPPORTED)
        self.assertEqual(updated["evidence_signals"]["distinct_independent_support_count"], 1)
        # Two supports listed (provenance + second file); ratio stays 1.0 with no contradicts.
        self.assertEqual(updated["confidence"], 1.0)

    def test_contradicted_from_observable_conflict(self) -> None:
        reg = ClaimRegister()
        cid = reg.add_claim(
            text="Rate is 5%",
            provenance="file:/a",
            source_kind="primary",
            supports=["file:/a"],
        )
        updated = reg.attach_evidence(cid, evidence_id="file:/b", relation="contradicts")
        self.assertEqual(updated["verification_status"], CONTRADICTED)
        signals = updated["evidence_signals"]
        self.assertGreaterEqual(signals["contradict_count"], 1)
        # Confidence is support/(support+contradict) from distinct independent counts.
        self.assertIsNotNone(updated["confidence"])
        self.assertLess(updated["confidence"], 1.0)

    def test_derived_evidence_does_not_confirm(self) -> None:
        reg = ClaimRegister()
        cid = reg.add_claim(
            text="Derived claim",
            provenance="knowledge:derived:chat-summary",
            source_kind="derived_analysis",
        )
        self.assertFalse(reg.allows_independent_confirmation(cid, evidence_id="knowledge:derived:chat-summary"))
        updated = reg.attach_evidence(cid, evidence_id="knowledge:derived:chat-summary", relation="supports")
        self.assertEqual(updated["verification_status"], UNVERIFIED)
        self.assertIsNone(updated["confidence"])
        self.assertGreaterEqual(updated["evidence_signals"]["derived_support_count"], 1)

    def test_stale_from_valid_until(self) -> None:
        reg = ClaimRegister()
        cid = reg.add_claim(
            text="Old window",
            provenance="file:/old",
            source_kind="primary",
            supports=["file:/a", "file:/b"],
            valid_until="2020-01-01T00:00:00Z",
        )
        claim = reg.reassess(cid, now="2026-09-09T12:00:00Z")
        self.assertEqual(claim["verification_status"], STALE)
        marked = reg.mark_stale(cid, reason="expired_window")
        self.assertEqual(marked["verification_status"], STALE)
        self.assertIsNone(marked["confidence"])

    def test_superseded_status_canonical(self) -> None:
        reg = ClaimRegister()
        cid = reg.add_claim(text="v1", provenance="file:/a", source_kind="primary")
        new_id = reg.supersede(cid, new_text="v2", provenance="file:/b", reason="correction")
        self.assertTrue(new_id)
        self.assertEqual(reg.get(cid)["verification_status"], SUPERSEDED)
        self.assertIsNone(reg.get(cid)["confidence"])
        self.assertEqual(reg.get(new_id)["verification_status"], UNVERIFIED)

    def test_confidence_only_from_signals(self) -> None:
        empty = derive_confidence_from_signals(
            {"independent_support_count": 0, "contradict_count": 0, "derived_support_count": 2}
        )
        self.assertIsNone(empty["confidence"])
        self.assertEqual(empty["confidence_basis"], "observable_evidence_signals")

        ratio = derive_confidence_from_signals(
            {"independent_support_count": 2, "contradict_count": 2, "derived_support_count": 0}
        )
        self.assertEqual(ratio["confidence"], 0.5)
        self.assertEqual(ratio["signal_ratio_numerator"], 2)
        self.assertEqual(ratio["signal_ratio_denominator"], 4)

    def test_sqlite_persists_canonical_status(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "claims.sqlite"
        reg = ClaimRegister(db)
        cid = reg.add_claim(
            text="persisted",
            provenance="file:/x",
            source_kind="primary",
            supports=["file:/x", "file:/y"],
        )
        reg.detach()
        reg2 = ClaimRegister(db)
        loaded = reg2.get(cid)
        assert loaded is not None
        self.assertEqual(loaded["verification_status"], SUPPORTED)
        self.assertIn(loaded["verification_status"], CLAIM_VERIFICATION_STATES)
        reg2.detach()


class ResearchMetricKindHonestyTests(unittest.TestCase):
    def test_mastery_alias_stays_coverage_kind(self) -> None:
        self.assertEqual(honest_research_metric_kind("mastery"), "source_coverage_diversity")
        self.assertEqual(honest_research_metric_kind("expert_mastery"), "source_coverage_diversity")
        self.assertEqual(honest_research_metric_kind("source_coverage_diversity"), "source_coverage_diversity")

    def test_summarize_refuses_fake_mastery_kind(self) -> None:
        summary = summarize_research_coverage(
            {
                "id": "rp",
                "depth": "expert",
                "status": "needs_more_evidence",
                "metrics": {
                    "coverage_score": 40,
                    "mastery": 40,
                    "mastery_target": 90,
                    "source_count": 2,
                    "evidence_chunks": 1,
                    "metric_kind": "expert_mastery",
                    "status": "needs-more-evidence",
                },
            }
        )
        self.assertEqual(summary["metric_kind"], "source_coverage_diversity")
        self.assertFalse(summary["complete"])
        self.assertTrue(summary["incomplete"])

    def test_register_research_contradictions_are_contradicted(self) -> None:
        reg = ClaimRegister()
        ids = register_research_contradiction_claims(
            reg,
            topic="quantum",
            contradictions=["Paper A ↔ Paper B"],
            task_id="rp_1",
            metric_kind="mastery",
        )
        self.assertEqual(len(ids), 1)
        claim = reg.get(ids[0])
        assert claim is not None
        self.assertEqual(claim["verification_status"], CONTRADICTED)
        self.assertEqual(claim["metric_kind"], "source_coverage_diversity")
        self.assertIn("not expert mastery", claim["metric_note"].lower())


class AssessPureFunctionTests(unittest.TestCase):
    def test_mixed_evidence_partial_when_supports_dominate(self) -> None:
        result = assess_verification_state(
            {
                "provenance": "file:/root",
                "source_kind": "primary",
                "supports": ["file:/a", "file:/b", "file:/c"],
                "contradicts": ["file:/x"],
                "superseded_by": None,
            }
        )
        self.assertEqual(result["verification_status"], PARTIALLY_SUPPORTED)
        self.assertEqual(result["confidence_basis"], "observable_evidence_signals")
        self.assertIsNotNone(result["confidence"])


if __name__ == "__main__":
    unittest.main()
