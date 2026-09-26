"""W6 — Verification tiers + system capability self-knowledge."""

from __future__ import annotations

import unittest

from Data.modules.verification import (
    SystemCapabilityState,
    VerificationEngine,
    VerificationOutcome,
    VerificationTier,
    build_system_capability_state,
)


class FakeEvidenceStore:
    def list(self, *, status=None, run_id=None, limit: int = 100):
        return []


class VerificationTierTests(unittest.TestCase):
    def test_deterministic_tier_labelled_on_verify(self) -> None:
        engine = VerificationEngine(FakeEvidenceStore())
        report = engine.verify([])
        self.assertEqual(report.outcome, VerificationOutcome.UNMEASURED)
        self.assertEqual(
            report.metadata.get("verification_tier"),
            VerificationTier.DETERMINISTIC_VERIFICATION.value,
        )

    def test_self_critique_not_independent(self) -> None:
        engine = VerificationEngine(FakeEvidenceStore())
        report = engine.self_critique(
            text="looks fine",
            critic_findings=[{"severity": "high", "message": "fabricated tool claim"}],
        )
        self.assertEqual(
            report.metadata.get("verification_tier"),
            VerificationTier.SELF_CRITIQUE.value,
        )
        self.assertTrue(
            report.metadata["truth"]["self_critique_is_not_independent_verification"]
        )
        self.assertEqual(report.outcome, VerificationOutcome.FAILED)

    def test_cross_model_unmeasured_without_secondary(self) -> None:
        engine = VerificationEngine(FakeEvidenceStore())
        report = engine.cross_model_verify(secondary_model_available=False)
        self.assertEqual(report.outcome, VerificationOutcome.UNMEASURED)
        self.assertEqual(
            report.metadata.get("verification_tier"),
            VerificationTier.CROSS_MODEL_VERIFICATION.value,
        )


class CapabilitySelfKnowledgeTests(unittest.TestCase):
    def test_brain_percentage_unmeasured(self) -> None:
        state = build_system_capability_state(
            capability_ids=["knowledge.search"],
            web_configured=False,
            browser_configured=True,
            browser_ready=False,
            network_allow_outbound=True,
            behavior_version="v1",
        )
        pub = state.public_dict()
        self.assertEqual(pub["brain_percentage"]["status"], "UNMEASURED")
        self.assertTrue(pub["truth"]["never_invents_brain_percentage"])
        self.assertEqual(pub["web_availability"], "NOT_CONFIGURED")
        self.assertEqual(pub["browser_availability"], "UNAVAILABLE")
        self.assertEqual(pub["network_authority"], "AVAILABLE")
        self.assertIsInstance(state, SystemCapabilityState)


if __name__ == "__main__":
    unittest.main()
