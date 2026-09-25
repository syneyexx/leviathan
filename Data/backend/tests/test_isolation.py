from __future__ import annotations

import unittest

from Data.backend.config import Settings
from Data.modules.isolation import IsolationGuard, IsolationMode, IsolationRequest
from dataclasses import replace


class IsolationGuardTests(unittest.TestCase):
    def test_baseline_network_posture_follows_outbound_setting(self) -> None:
        """Outbound ON (production default) → no NETWORK_DENY; OFF → NETWORK_DENY."""
        settings = Settings.from_env()
        # Production default: outbound allowed.
        self.assertTrue(settings.network.allow_outbound)
        guard = IsolationGuard(settings)
        report = guard.evaluate()
        self.assertNotIn(IsolationMode.NETWORK_DENY, report.effective.effective)
        self.assertIn(IsolationMode.PROCESS, report.effective.effective)
        self.assertIn(IsolationMode.WORKSPACE, report.effective.effective)
        self.assertFalse(report.effective.matched)
        self.assertTrue(report.public_dict()["truth"]["requested_isolation_is_not_effective_isolation"])

        denied = replace(settings, network=replace(settings.network, allow_outbound=False))
        denied_report = IsolationGuard(denied).evaluate()
        self.assertIn(IsolationMode.NETWORK_DENY, denied_report.effective.effective)

    def test_requested_subset_matches(self) -> None:
        settings = Settings.from_env()
        guard = IsolationGuard(settings)
        report = guard.evaluate(
            IsolationRequest(requested=(IsolationMode.PROCESS, IsolationMode.WORKSPACE))
        )
        self.assertTrue(report.effective.matched)


if __name__ == "__main__":
    unittest.main()
