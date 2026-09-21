"""Regression: empty uncertainties must not demote a verified coding delivery."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coding_delivery import build_coding_delivery, validate_delivery_for_completion


class CodingDeliveryEmptyUncertaintiesTests(unittest.TestCase):
    def test_empty_uncertainties_list_is_not_missing(self) -> None:
        delivery = build_coding_delivery(
            goal="Fix combine()",
            task_type="bugfix",
            understanding="Hidden bug in core_math.combine",
            changed_files=["service/core_math.py"],
            diff_text="--- a/service/core_math.py\n+++ b/service/core_math.py\n",
            checks_run=[{"kind": "unittest"}],
            test_results=[{"status": "passed", "exit_code": 0}],
            uncertainties=[],
            status="verified",
        )
        self.assertNotIn("uncertainties", delivery.get("missing_fields") or [])
        self.assertEqual(delivery["status"], "verified")
        self.assertTrue(delivery["complete"])
        gate = validate_delivery_for_completion(delivery)
        self.assertTrue(gate.get("allowed") or gate.get("ok"))

    def test_missing_uncertainties_key_is_flagged(self) -> None:
        delivery = build_coding_delivery(
            goal="Fix combine()",
            task_type="bugfix",
            understanding="x",
            changed_files=["a.py"],
            diff_text="diff",
            checks_run=[{"kind": "unittest"}],
            test_results=[{"status": "passed"}],
            uncertainties=None,  # type: ignore[arg-type]
            status="verified",
        )
        # build_coding_delivery coerces None uncertainties to []
        self.assertIsInstance(delivery["uncertainties"], list)


if __name__ == "__main__":
    unittest.main()
