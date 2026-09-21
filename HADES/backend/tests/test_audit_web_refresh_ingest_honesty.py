"""Auto web-refresh must not count unverified ingest as indexed success."""
from __future__ import annotations
import asyncio, inspect, sys, unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

class WebRefreshIngestHonestyTests(unittest.TestCase):
    def test_source_checks_verification_failed(self) -> None:
        import main as app_main
        source = inspect.getsource(app_main.maybe_refresh_web_knowledge)
        self.assertIn("verification_failed", source)
        self.assertIn("verification_passed", source)

    def test_unverified_ingest_is_not_indexed(self) -> None:
        import main as app_main
        async def _run() -> dict:
            with (
                patch.object(app_main, "runtime_values", return_value={"auto_web_research": True, "network_policy": "allow"}),
                patch.object(app_main, "ensure_platform_services"),
                patch.object(app_main.web_research, "discover_duckduckgo", AsyncMock(return_value=["https://example.test/a"])),
                patch.object(app_main.web_research, "ingest_url", AsyncMock(return_value={
                    "id": "src-1",
                    "status": "verification_failed",
                    "persistence": {"verification_passed": False},
                })),
            ):
                return await app_main.maybe_refresh_web_knowledge("laatste nieuws vandaag")
        result = asyncio.run(_run())
        self.assertTrue(result.get("attempted"))
        self.assertEqual(result.get("indexed"), 0)
        self.assertFalse(result.get("ok"))
        self.assertTrue(result.get("errors"))

if __name__ == "__main__":
    unittest.main()
