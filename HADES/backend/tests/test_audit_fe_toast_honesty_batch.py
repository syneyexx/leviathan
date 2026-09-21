"""FE toasts must not greenwash skill/native/files failures or empty work."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class FeToastHonestyBatchTests(unittest.TestCase):
    def test_mission_skill_execute_uses_error_on_failed(self) -> None:
        page = (ROOT / "components" / "hades" / "pages" / "mission-control-page.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn('toast.error("Skill executed with failures")', page)
        self.assertNotIn(
            'toast.success(executed.passed ? "Skill executed" : "Skill executed with failures")',
            page,
        )

    def test_files_add_rescan_gate_ready_zero(self) -> None:
        page = (ROOT / "components" / "hades" / "pages" / "files-page.tsx").read_text(encoding="utf-8")
        self.assertIn("ready <= 0 && (failed > 0 || unsupported > 0)", page)
        self.assertIn("toast.message(`Map toegevoegd zonder nieuwe indexering", page)
        self.assertIn("if (ready > 0)", page)
        self.assertIn("toast.message(message)", page)

    def test_native_restart_errors_when_disconnected(self) -> None:
        page = (ROOT / "components" / "hades" / "native-runtime-panel.tsx").read_text(encoding="utf-8")
        self.assertIn('toast.error("Native runtime niet verbonden na herstart.")', page)
        self.assertNotIn(
            'toast.success(next.connected ? "Native runtime herstart."',
            page,
        )


if __name__ == "__main__":
    unittest.main()
