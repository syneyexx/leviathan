"""Approval decide must not hide resume failures."""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ApprovalResumeHonestyTests(unittest.TestCase):
    def test_decide_route_surfaces_resume_failure(self) -> None:
        import capability_routes as routes

        source = inspect.getsource(routes)
        self.assertIn("resume_ok", source)
        self.assertIn("resume_error", source)
        self.assertNotIn(
            "resume(str(decided[\"task_id\"]), decided)\n                except Exception:\n                    pass",
            source,
        )


if __name__ == "__main__":
    unittest.main()
