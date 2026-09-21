"""Service start must fail when the process dies after a healthy check."""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class StartServiceProcessHonestyTests(unittest.TestCase):
    def test_dead_process_after_health_is_failed(self) -> None:
        import platform_services_core as psc

        source = inspect.getsource(psc.PluginManager._start_service)
        self.assertIn("process_exited_after_start", source)
        self.assertIn('status="failed"', source)
        self.assertIn("poll()", source)
        # Must not finish completed while process already exited.
        dead_branch = source.split("if process.poll() is not None:")[1].split("write_service_state")[0]
        self.assertIn('status="failed"', dead_branch)
        self.assertNotIn('status="completed"', dead_branch)


if __name__ == "__main__":
    unittest.main()
