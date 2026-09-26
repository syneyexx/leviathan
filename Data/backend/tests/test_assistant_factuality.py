"""GI3 — Claim factuality gate for assistant answers (extends VerificationEngine)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.artifacts import ArtifactStore
from Data.modules.evidence import EvidenceService, EvidenceStore
from Data.modules.verification import (
    ClaimAssessment,
    ClaimExtractor,
    ClaimKind,
    ClaimSupportStatus,
    ClaimVerifier,
    FactualityGate,
    FactualityMode,
    VerificationEngine,
    VerificationOutcome,
    VerificationPool,
)


class FakeEvidenceRefsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "v.db"
        self.artifacts = ArtifactStore(self.db, root / "artifacts")
        self.artifacts.initialize()
        self.evidence_store = EvidenceStore(self.db)
        self.evidence_store.initialize()
        self.evidence = EvidenceService(self.evidence_store, artifacts=self.artifacts)
        self.engine = VerificationEngine(self.evidence_store)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_fake_evidence_refs_fail_not_pass(self) -> None:
        claim = ClaimAssessment(
            claim_id="c-fake",
            claim_text="The file was written successfully to disk.",
            claim_kind=ClaimKind.TOOL_SUCCESS,
            status=ClaimSupportStatus.UNMEASURED,
            evidence_refs=("ev-invented-by-critic", "ev-also-fake"),
            tool_receipt_refs=(),
        )
        # Critic/model also claims verified=true — must be ignored.
        report = self.engine.verify_claim_assessments(
            [claim],
            model_verified_flags={"c-fake": True},
        )
        self.assertNotEqual(report.outcome, VerificationOutcome.PASSED)
        self.assertIn(
            report.outcome,
            {VerificationOutcome.FAILED, VerificationOutcome.UNMEASURED},
        )
        self.assertEqual(report.requirements[0].outcome, VerificationOutcome.FAILED)
        assessments = report.metadata.get("claim_assessments") or []
        self.assertTrue(assessments)
        self.assertEqual(assessments[0]["status"], ClaimSupportStatus.UNSUPPORTED.value)
        self.assertIn("invented", (assessments[0].get("reason") or "").lower())
        self.assertTrue(report.metadata["truth"]["invented_evidence_refs_rejected"])
        self.assertTrue(report.metadata["truth"]["model_verified_flag_is_not_verification"])

    def test_real_evidence_ref_can_pass(self) -> None:
        artifact = self.artifacts.create_from_bytes(
            data=b"ok",
            artifact_type="text",
            producer="test",
            filename="a.txt",
            run_id="run-r",
        )
        ev = self.evidence.claim_artifact_hash(artifact_id=artifact.artifact_id, run_id="run-r")
        claim = ClaimAssessment(
            claim_id="c-real",
            claim_text="Repository contains the expected artifact hash.",
            claim_kind=ClaimKind.REPOSITORY,
            status=ClaimSupportStatus.UNMEASURED,
            evidence_refs=(ev.evidence_id,),
        )
        report = self.engine.verify_claim_assessments([claim], run_id="run-r")
        self.assertEqual(report.outcome, VerificationOutcome.PASSED)


class ToolClaimWithoutReceiptTests(unittest.TestCase):
    def test_tool_claim_without_receipt_unsupported(self) -> None:
        gate = FactualityGate()
        draft = "I successfully wrote the configuration file to disk."
        result = gate.apply(
            draft,
            mode=FactualityMode.REQUIRED,
            pool=VerificationPool(),  # empty — no receipts
        )
        tool_claims = [
            a for a in result.assessments if a.claim_kind == ClaimKind.TOOL_SUCCESS
        ]
        self.assertTrue(tool_claims, "expected TOOL_SUCCESS claim extraction")
        self.assertEqual(tool_claims[0].status, ClaimSupportStatus.UNSUPPORTED)
        self.assertIn("receipt", (tool_claims[0].reason or "").lower())
        self.assertTrue(result.qualified)
        self.assertIn("unsupported", result.revised_text.lower())


class SelfMetricWithoutTelemetryTests(unittest.TestCase):
    def test_brain_percent_unmeasured_no_invented_pct(self) -> None:
        gate = FactualityGate()
        draft = "I am currently running at 20% brain capacity on this task."
        result = gate.apply(draft, mode=FactualityMode.LIGHT, pool=VerificationPool())
        self_claims = [a for a in result.assessments if a.claim_kind == ClaimKind.SELF_SYSTEM]
        self.assertTrue(self_claims)
        self.assertEqual(self_claims[0].status, ClaimSupportStatus.UNMEASURED)
        # Must not invent a replacement percentage; scrub or qualify.
        self.assertNotIn("20%", result.revised_text)
        self.assertTrue(
            "[unmeasured]" in result.revised_text.lower()
            or "unmeasured" in result.revised_text.lower()
        )
        # Deterministic extraction across runs.
        again = ClaimExtractor().extract(draft)
        self.assertEqual(
            [c.claim_id for c in again],
            [c.claim_id for c in ClaimExtractor().extract(draft)],
        )


class CreativeContentTests(unittest.TestCase):
    def test_creative_content_not_broken(self) -> None:
        gate = FactualityGate()
        draft = (
            "Here is a short story. Once upon a time a lantern glowed in the harbor mist, "
            "and a sailor hummed about stars."
        )
        result = gate.apply(draft, mode=FactualityMode.REQUIRED, pool=VerificationPool())
        creative = [a for a in result.assessments if a.claim_kind == ClaimKind.CREATIVE]
        self.assertTrue(creative)
        self.assertEqual(result.revised_text, draft)
        self.assertFalse(result.qualified)
        self.assertTrue(result.public_dict()["truth"]["creative_content_is_not_broken"])


class CurrentInfoWithoutFreshSourceTests(unittest.TestCase):
    def test_current_info_qualified_without_fresh_source(self) -> None:
        gate = FactualityGate()
        draft = "The current version of the library is 9.9.9 as of today."
        result = gate.apply(draft, mode=FactualityMode.LIGHT, pool=VerificationPool())
        current = [
            a for a in result.assessments if a.claim_kind == ClaimKind.CURRENT_TIME_SENSITIVE
        ]
        self.assertTrue(current)
        self.assertEqual(current[0].status, ClaimSupportStatus.UNMEASURED)
        self.assertTrue(result.qualified)
        self.assertIn("fresh source", result.revised_text.lower())

    def test_current_info_supported_with_fresh_source(self) -> None:
        gate = FactualityGate()
        draft = "The latest release currently ships feature X."
        pool = VerificationPool.from_inputs(
            evidence_ids=["ev-fresh-1"],
            fresh_source_refs=["ev-fresh-1"],
        )
        claims = ClaimExtractor().extract(draft)
        self.assertTrue(claims)
        assessed = ClaimVerifier().verify(
            [
                ClaimAssessment(
                    claim_id=claims[0].claim_id,
                    claim_text=claims[0].claim_text,
                    claim_kind=claims[0].claim_kind,
                    status=ClaimSupportStatus.UNMEASURED,
                    evidence_refs=("ev-fresh-1",),
                    freshness_requirement="fresh_source",
                )
            ],
            pool,
        )
        self.assertEqual(assessed[0].status, ClaimSupportStatus.SOURCE_SUPPORTED)


class ClaimKindContractTests(unittest.TestCase):
    def test_public_enums_cover_required_kinds(self) -> None:
        kinds = {k.value for k in ClaimKind}
        for required in (
            "SELF_SYSTEM",
            "CURRENT_TIME_SENSITIVE",
            "FILE",
            "TOOL_SUCCESS",
            "COMPUTATIONAL",
            "REPOSITORY",
            "CREATIVE",
            "ORDINARY_FACTUAL",
            "OPINION",
        ):
            self.assertIn(required, kinds)
        statuses = {s.value for s in ClaimSupportStatus}
        for required in (
            "SUPPORTED",
            "CONFLICTED",
            "UNSUPPORTED",
            "UNMEASURED",
            "INFERRED",
            "MODEL_PRIOR",
            "TOOL_VERIFIED",
            "SOURCE_SUPPORTED",
            "CORROBORATED",
            "UNAVAILABLE",
        ):
            self.assertIn(required, statuses)
        modes = {m.value for m in FactualityMode}
        self.assertEqual(modes, {"NONE", "LIGHT", "REQUIRED", "CORROBORATED"})


if __name__ == "__main__":
    unittest.main()
