"""Tasks UI must not toast success when approval resume failed."""
from __future__ import annotations
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "components" / "hades" / "pages" / "tasks-page.tsx"

class TasksApprovalToastHonestyTests(unittest.TestCase):
    def test_approve_checks_resume_ok(self) -> None:
        text = PAGE.read_text(encoding="utf-8")
        self.assertIn("resume_ok", text)
        self.assertIn("resume_error", text)
        self.assertIn("Goedgekeurd, maar hervatten is mislukt", text)

if __name__ == "__main__":
    unittest.main()
