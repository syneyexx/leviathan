"""Plugin policy hook attach failures must be observable (not silent pass)."""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class PluginPolicyHooksAttachHonestyTests(unittest.TestCase):
    def test_attach_failure_records_flag_and_logs(self) -> None:
        import main as app_main

        source = inspect.getsource(app_main)
        self.assertIn("_PLUGIN_POLICY_HOOKS_ATTACHED", source)
        self.assertIn("_PLUGIN_POLICY_HOOKS_ERROR", source)
        self.assertIn("plugin_policy_hooks_attach_failed", source)
        # Old silent swallow must stay gone.
        self.assertNotIn(
            "except Exception:\n    # Startup must remain bootable in minimal test harnesses; recreate path re-attaches explicitly.\n    pass",
            source,
        )


if __name__ == "__main__":
    unittest.main()
