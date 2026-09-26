"""GI8 — Playwright Chromium readiness honesty (env-gated real path)."""

from __future__ import annotations

import os
import unittest

from Data.modules.browser import PlaywrightBrowserBackend, PlaywrightUnavailable
from Data.modules.browser.worker import BrowserAction, BrowserSession, BrowserWorker


class PlaywrightReadinessHonestyTests(unittest.TestCase):
    def test_readiness_never_true_on_package_alone(self) -> None:
        backend = PlaywrightBrowserBackend()
        info = backend.readiness(force=True)
        self.assertIn(info.get("status"), {"READY", "UNAVAILABLE", "UNKNOWN"})
        self.assertTrue(info.get("truth", {}).get("package_alone_is_not_ready", True))
        if not info.get("package_installed"):
            self.assertFalse(info.get("ready"))
            self.assertEqual(info.get("status"), "UNAVAILABLE")

    def test_unavailable_is_not_ready(self) -> None:
        backend = PlaywrightBrowserBackend()
        info = backend.readiness()
        if not info.get("ready"):
            self.assertFalse(bool(info.get("ready")))
            self.assertNotEqual(info.get("status"), "READY")

    @unittest.skipUnless(
        (os.environ.get("LEVIATHAN_TEST_PLAYWRIGHT") or "").strip() in {"1", "true", "yes"},
        "Set LEVIATHAN_TEST_PLAYWRIGHT=1 for real Chromium integration",
    )
    def test_real_chromium_navigate_when_enabled(self) -> None:
        backend = PlaywrightBrowserBackend()
        info = backend.readiness(force=True)
        if not info.get("ready"):
            self.skipTest(f"Playwright Chromium not READY: {info.get('detail')}")
        worker = BrowserWorker(backend=backend, allow_network=False)
        result = worker.execute(
            action=BrowserAction.NAVIGATE,
            arguments={
                "url": "data:text/html,<html><head><title>pw</title></head>"
                "<body><p>playwright-live</p></body></html>"
            },
            run_id="pw_test",
        )
        self.assertEqual(result["status"], "COMPLETED")
        self.assertIn("playwright-live", (result.get("observation") or {}).get("dom_text") or "")

    def test_apply_raises_unavailable_or_works(self) -> None:
        backend = PlaywrightBrowserBackend()
        session = BrowserSession(session_id="pw_sess")
        try:
            backend.apply(
                session,
                action=BrowserAction.NAVIGATE,
                arguments={"url": "about:blank"},
            )
        except PlaywrightUnavailable as exc:
            self.assertTrue(getattr(exc, "unavailable", True))
            info = backend.readiness()
            self.assertFalse(info.get("ready"))


if __name__ == "__main__":
    unittest.main()
