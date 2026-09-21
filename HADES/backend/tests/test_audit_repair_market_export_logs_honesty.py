"""Plugin repair/marketplace/build, pack export, native bench, empty logs honesty."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class RepairMarketExportLogsHonestyTests(unittest.TestCase):
    def test_plugins_repair_market_build_toasts(self) -> None:
        page = (ROOT / "components" / "hades" / "pages" / "plugins-page-core.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("Repair mislukt (status:", page)
        self.assertIn("Ready/health niet bewezen", page)
        self.assertIn(".HadesPlugin build eindigde in status:", page)
        self.assertNotIn(
            'toast.success(result.plugin.status === "ready" ? "Dependencies en runtime zijn gereed." : "Repair afgerond; review blijft nodig.")',
            page,
        )
        self.assertNotIn(
            'toast.success(proof ? `${pluginId} geïnstalleerd (Ready/health ok).` : `${pluginId} geïnstalleerd — controleer Ready-status.`)',
            page,
        )

    def test_knowledge_pack_export_empty_message(self) -> None:
        page = (ROOT / "components" / "hades" / "pages" / "memory-page.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("Knowledge pack geëxporteerd maar leeg (0 items).", page)

    def test_native_benchmark_requires_timings(self) -> None:
        page = (ROOT / "components" / "hades" / "native-runtime-panel.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("geen echo-timings gemeten", page)
        self.assertIn('typeof row.python_process_echo_ms === "number"', page)

    def test_empty_service_logs_fail_closed_markers(self) -> None:
        src = (ROOT / "backend" / "platform_services_core.py").read_text(encoding="utf-8")
        self.assertIn('error=None if has_output else "empty_service_logs"', src)
        self.assertIn('status="completed" if has_output else "failed"', src)


if __name__ == "__main__":
    unittest.main()
