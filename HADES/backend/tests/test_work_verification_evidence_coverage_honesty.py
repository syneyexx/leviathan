from __future__ import annotations

import unittest
from pathlib import Path

from reasoning.evidence_coverage import assess_coverage
from reasoning.verification import parse_verification_result


class WorkVerificationEvidenceCoverageHonestyTests(unittest.TestCase):
    def test_proposed_final_with_unrelated_step_evidence_is_insufficient(self) -> None:
        parsed = parse_verification_result(
            '{"passed":true,"issues":[],"final":"The production database migration completed successfully.",'
            '"evidence_refs":["step:1"],"incomplete":false,'
            '"criteria_checklist":[{"id":"c1","criterion":"Migration completed","met":true}]}'
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.final_answer, "")
        self.assertIn("database migration", parsed.proposed_final_answer)

        coverage = assess_coverage(
            [{"text": parsed.proposed_final_answer, "evidence_refs": parsed.evidence_refs}],
            known_refs={"step:1"},
            evidence_texts={"step:1": "Amsterdam temperature is 12 C."},
            require_factual=True,
        )
        self.assertFalse(coverage.sufficient)
        self.assertFalse(coverage.factual_verified)
        self.assertEqual(coverage.verification_label, "unverified")
        self.assertEqual(coverage.claims[0].support_level, "insufficient")

    def test_work_runtime_checks_candidate_final_and_blocks_insufficient_coverage(self) -> None:
        """Characterize the current Work false-success wiring without importing main.

        ``parse_verification_result`` intentionally stores critic text in
        ``proposed_final_answer`` and leaves ``final_answer`` empty. Work must
        therefore coverage-check the candidate it will actually return and must
        not write a verified checkpoint when that coverage is insufficient.
        """
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        start = source.index("allowed, reason = verification_allows_success(\n                result,")
        end = source.index("            issues = result.issues if result else [reason]", start)
        work_verification = source[start:end]

        self.assertNotIn(
            '[{"text": result.final_answer, "evidence_refs": result.evidence_refs}]',
            work_verification,
            "Work coverage must not inspect the intentionally empty final_answer field.",
        )
        self.assertIn(
            "result.proposed_final_answer",
            work_verification,
            "Work must coverage-check the candidate final it may actually return.",
        )
        self.assertTrue(
            "not coverage.sufficient" in work_verification
            or "coverage.factual_verified" in work_verification,
            "Insufficient factual coverage must be able to revoke allowed=True before phase=verified.",
        )


if __name__ == "__main__":
    unittest.main()
