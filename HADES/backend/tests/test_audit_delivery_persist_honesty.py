"""Coding delivery phase must not be claimed when artifact persist fails."""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class DeliveryPersistHonestyTests(unittest.TestCase):
    def test_delivery_artifact_phase_requires_successful_write(self) -> None:
        import coding_agent as ca

        source = inspect.getsource(ca)
        self.assertIn("delivery_persist_failed", source)
        self.assertIn("persist_error", source)
        # Must append delivery_artifact only after successful write in the report path.
        self.assertIn("write_delivery_artifact(work_root, delivery)\n                phases_completed.append(\"delivery_artifact\")", source)


if __name__ == "__main__":
    unittest.main()
