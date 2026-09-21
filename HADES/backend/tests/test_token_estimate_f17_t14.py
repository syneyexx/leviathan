"""T14/F-17: calibrated token estimates for NL prose and code."""

from __future__ import annotations

import unittest

from reasoning.provider_budget import enforce_provider_payload_budget
from reasoning.token_estimate import (
    CALIBRATION_MAX_REL_ERROR,
    REFERENCE_SNIPPETS,
    calibration_report,
    detect_domain,
    estimate_tokens,
    reference_token_count,
)


class TokenEstimateCalibrationTests(unittest.TestCase):
    def test_calibration_within_margin_for_nl_and_code(self) -> None:
        report = calibration_report()
        self.assertTrue(report["all_within_margin"], report)
        self.assertEqual(report["max_rel_error"], CALIBRATION_MAX_REL_ERROR)
        for row in report["snippets"]:
            self.assertLessEqual(row["rel_error"], CALIBRATION_MAX_REL_ERROR, row)

    def test_domain_detection(self) -> None:
        self.assertEqual(detect_domain(str(REFERENCE_SNIPPETS["nl_prose"]["text"])), "nl_prose")
        self.assertEqual(detect_domain(str(REFERENCE_SNIPPETS["code_py"]["text"])), "code")

    def test_chars_div_4_is_worse_than_calibrated_for_nl(self) -> None:
        text = str(REFERENCE_SNIPPETS["nl_prose"]["text"])
        ref = reference_token_count(text)
        naive = max(1, len(text) // 4)
        calibrated = estimate_tokens(text, domain="nl_prose").tokens
        naive_err = abs(naive - ref) / max(1, ref)
        cal_err = abs(calibrated - ref) / max(1, ref)
        self.assertLessEqual(cal_err, CALIBRATION_MAX_REL_ERROR)
        self.assertLessEqual(cal_err, naive_err + 1e-9)

    def test_overflow_is_explicit_not_silent_ok(self) -> None:
        huge = "woord " * 5000
        decision = enforce_provider_payload_budget(
            {"messages": [{"role": "system", "content": "policy"}, {"role": "user", "content": huge}]},
            max_chars=200,
            reserve_output_chars=50,
            capacity_source="test",
        )
        self.assertFalse(decision.ok)
        self.assertTrue(decision.overflow)
        self.assertIn("context_limit_exceeded_explicit", decision.notes)
        self.assertIsNotNone(decision.used_tokens_est)


if __name__ == "__main__":
    unittest.main()
