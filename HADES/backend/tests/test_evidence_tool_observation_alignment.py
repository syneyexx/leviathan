from __future__ import annotations

import unittest

from reasoning.evidence_coverage import assess_coverage
from reasoning.evidence_package import bind_claims_to_evidence, build_evidence_package


class ToolObservationEvidenceAlignmentTests(unittest.TestCase):
    def test_single_unrelated_tool_ref_cannot_factually_verify_claim(self) -> None:
        package = build_evidence_package(
            tool_log=[
                {
                    "call_id": "weather-check",
                    "status": "completed",
                    "plugin_id": "weather",
                    "tool_name": "current",
                    "output": "Amsterdam temperature is 12 C.",
                }
            ]
        )
        claims = bind_claims_to_evidence(
            ["The production database migration completed successfully."],
            package,
            critic_refs=["tool:weather-check"],
        )

        report = assess_coverage(
            claims,
            known_refs=package.known_refs(),
            evidence_texts=package.evidence_texts(),
            evidence_kinds=package.evidence_kinds(),
            require_factual=True,
        )

        self.assertFalse(report.factual_verified)
        self.assertFalse(report.sufficient)
        self.assertEqual(report.verification_label, "unverified")
        self.assertEqual(report.claims[0].support_level, "insufficient")

    def test_direct_unrelated_tool_ref_is_not_sufficient(self) -> None:
        report = assess_coverage(
            [
                {
                    "text": "The production database migration completed successfully.",
                    "evidence_refs": ["tool:weather-check"],
                    "is_tool_observation": True,
                }
            ],
            known_refs={"tool:weather-check"},
            evidence_texts={"tool:weather-check": "Amsterdam temperature is 12 C."},
            evidence_kinds={"tool:weather-check": "tool_observation"},
            require_factual=True,
        )

        self.assertFalse(report.factual_verified)
        self.assertFalse(report.sufficient)
        self.assertEqual(report.claims[0].support_level, "insufficient")
        self.assertIn("tool_observation_content_not_aligned", report.claims[0].notes)

    def test_terse_aligned_test_output_remains_direct_observation(self) -> None:
        report = assess_coverage(
            [
                {
                    "text": "Tests passed for add()",
                    "evidence_refs": ["tool:test-add"],
                    "is_tool_observation": True,
                }
            ],
            known_refs={"tool:test-add"},
            evidence_texts={"tool:test-add": "test_add ... ok"},
            evidence_kinds={"tool:test-add": "tool_observation"},
            require_factual=True,
        )

        self.assertTrue(report.factual_verified)
        self.assertTrue(report.sufficient)
        self.assertEqual(report.claims[0].support_level, "direct_observation")
        self.assertIn("content_alignment_verified", report.claims[0].notes)


if __name__ == "__main__":
    unittest.main()
