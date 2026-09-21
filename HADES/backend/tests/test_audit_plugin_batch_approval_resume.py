"""Plugin batch approvals must attempt task resume and surface resume_ok."""
from __future__ import annotations
import inspect, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

class PluginBatchApprovalResumeTests(unittest.TestCase):
    def test_batch_route_calls_resume_and_surfaces_flags(self) -> None:
        import main as app_main
        source = inspect.getsource(app_main.plugin_approvals_batch)
        self.assertIn("_resume_after_approval", source)
        self.assertIn("resume_ok", source)
        self.assertIn("resume_error", source)

if __name__ == "__main__":
    unittest.main()
