from __future__ import annotations

import unittest

from Data.backend.config import Settings
from Data.modules.isolation import IsolationGuard, IsolationMode, IsolationRequest


class IsolationGuardTests(unittest.TestCase):
    def test_baseline_includes_network_deny_by_default(self) -> None:
        settings = Settings.from_env()
        guard = IsolationGuard(settings)
        report = guard.evaluate()
        self.assertIn(IsolationMode.NETWORK_DENY, report.effective.effective)
        self.assertFalse(report.effective.matched)
        self.assertTrue(report.public_dict()["truth"]["requested_isolation_is_not_effective_isolation"])

    def test_requested_subset_matches(self) -> None:
        settings = Settings.from_env()
        guard = IsolationGuard(settings)
        report = guard.evaluate(
            IsolationRequest(requested=(IsolationMode.PROCESS, IsolationMode.WORKSPACE))
        )
        self.assertTrue(report.effective.matched)


if __name__ == "__main__":
    unittest.main()
