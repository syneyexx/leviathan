"""GI8 — Playwright Chromium runtime: unit + environment-gated real browser."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.artifacts import ArtifactStore
from Data.modules.browser import (
    BrowserAction,
    BrowserBackendKind,
    BrowserJobStatus,
    BrowserWorker,
    PlaywrightBrowserBackend,
    PlaywrightUnavailable,
    resolve_browser_backend,
)
from Data.modules.browser.playwright_backend import chromium_executable_exists


def _playwright_ready() -> tuple[bool, dict]:
    backend = PlaywrightBrowserBackend()
    info = backend.readiness()
    try:
        backend.close()
    except Exception:  # noqa: BLE001
        pass
    return bool(info.get("ready")), info


class PlaywrightReadinessUnitTests(unittest.TestCase):
    def test_package_alone_is_not_ready_marker(self) -> None:
        backend = PlaywrightBrowserBackend()
        info = backend.readiness()
        self.assertIn("package_alone_is_not_ready", info["truth"])
        self.assertIn("unavailable_is_not_ready", info["truth"])
        # Without a measured Chromium path, must not claim READY.
        if not info.get("package_installed"):
            self.assertFalse(info["ready"])
            self.assertEqual(info["status"], "UNAVAILABLE")
        if info.get("package_installed") and not info.get("chromium_exists"):
            self.assertFalse(info["ready"])
            self.assertEqual(info["status"], "UNAVAILABLE")

    def test_resolve_playwright_backend_kind(self) -> None:
        backend = resolve_browser_backend("playwright")
        self.assertEqual(backend.kind, BrowserBackendKind.PLAYWRIGHT)

    def test_unavailable_action_is_unsupported_not_fabricated(self) -> None:
        backend = PlaywrightBrowserBackend()
        # Force unavailable without probing success.
        backend._pkg_ok = False
        backend._ready = False
        backend._readiness["ready"] = False
        backend._readiness["detail"] = "forced unavailable for unit test"
        worker = BrowserWorker(backend=backend)
        result = worker.execute(
            action=BrowserAction.NAVIGATE,
            arguments={"url": "data:text/html,<p>x</p>"},
        )
        self.assertEqual(result["status"], BrowserJobStatus.UNSUPPORTED.value)
        self.assertTrue(result["truth"]["unavailable_is_not_ready"])

    def test_chromium_executable_probe_honest(self) -> None:
        exists, path = chromium_executable_exists()
        if not exists:
            self.assertTrue(path is None or not Path(str(path)).is_file())


@unittest.skipUnless(
    _playwright_ready()[0],
    "Playwright Chromium not READY in this environment (NOT_TESTED)",
)
class PlaywrightRealChromiumTests(unittest.TestCase):
    """Environment-gated — only runs when Chromium launch+navigate+observe succeeds."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.artifacts = ArtifactStore(root / "artifacts.db", root / "artifacts")
        self.artifacts.initialize()
        self.backend = PlaywrightBrowserBackend()
        self.worker = BrowserWorker(backend=self.backend, artifact_store=self.artifacts)
        self.page = root / "demo.html"
        self.page.write_text(
            """<!DOCTYPE html>
            <html><head><title>PW Demo</title></head>
            <body>
              <h1>Hello Chromium</h1>
              <label for="email">Email</label>
              <input id="email" name="email" placeholder="you@example.invalid" />
              <button id="go" type="button">Go</button>
              <a id="next" href="#done">Next</a>
              <div id="done" hidden>Done</div>
            </body></html>
            """,
            encoding="utf-8",
        )
        self.upload = root / "upload.txt"
        self.upload.write_text("payload", encoding="utf-8")

    def tearDown(self) -> None:
        try:
            self.backend.close()
        except Exception:  # noqa: BLE001
            pass
        self.tmp.cleanup()

    def test_navigate_observe_all_actions(self) -> None:
        url = self.page.resolve().as_uri()
        nav = self.worker.execute(
            action=BrowserAction.NAVIGATE,
            arguments={"url": url},
            run_id="pw1",
        )
        self.assertEqual(nav["status"], BrowserJobStatus.COMPLETED.value)
        self.assertEqual(nav["backend"], "playwright")
        self.assertIn("Hello Chromium", nav["observation"]["dom_text"])
        self.assertTrue(nav["observation"]["interactive_elements"])
        sid = nav["session_id"]

        extracted = self.worker.execute(
            action=BrowserAction.EXTRACT_TEXT,
            arguments={"session_id": sid},
            run_id="pw1",
        )
        self.assertEqual(extracted["status"], BrowserJobStatus.COMPLETED.value)

        typed = self.worker.execute(
            action=BrowserAction.TYPE,
            arguments={"session_id": sid, "label": "Email", "text": "qa@example.invalid"},
            run_id="pw1",
        )
        self.assertEqual(typed["status"], BrowserJobStatus.APPLIED_UNVERIFIED.value)

        filled = self.worker.execute(
            action=BrowserAction.FORM_FILL,
            arguments={"session_id": sid, "fields": {"email": "qa2@example.invalid"}},
            run_id="pw1",
        )
        self.assertEqual(filled["status"], BrowserJobStatus.APPLIED_UNVERIFIED.value)

        clicked = self.worker.execute(
            action=BrowserAction.CLICK,
            arguments={"session_id": sid, "selector": "#go"},
            run_id="pw1",
        )
        self.assertEqual(clicked["status"], BrowserJobStatus.APPLIED_UNVERIFIED.value)

        verified = self.worker.execute(
            action=BrowserAction.VERIFY_STATE,
            arguments={
                "session_id": sid,
                "predicates": [
                    {
                        "attribute_equals": {
                            "selector": "#email",
                            "attr": "value",
                            "value": "qa2@example.invalid",
                        }
                    }
                ],
            },
            run_id="pw1",
        )
        self.assertEqual(verified["status"], BrowserJobStatus.COMPLETED.value)

        self.worker.execute(
            action=BrowserAction.SCROLL,
            arguments={"session_id": sid, "direction": "down"},
            run_id="pw1",
        )
        self.worker.execute(
            action=BrowserAction.WAIT,
            arguments={"session_id": sid, "ms": 50},
            run_id="pw1",
        )
        self.worker.execute(
            action=BrowserAction.KEYPRESS,
            arguments={"session_id": sid, "key": "Tab", "selector": "#email"},
            run_id="pw1",
        )

        shot = self.worker.execute(
            action=BrowserAction.SCREENSHOT,
            arguments={"session_id": sid},
            run_id="pw1",
        )
        self.assertEqual(shot["status"], BrowserJobStatus.COMPLETED.value)
        self.assertEqual(shot["metadata"].get("screenshot_kind"), "chromium_framebuffer_png")
        self.assertIsNotNone(shot.get("artifact_id"))
        # Must never claim HTML DOM snapshot is a framebuffer.
        self.assertNotEqual(shot["metadata"].get("screenshot_kind"), "html_dom_snapshot")

        up = self.worker.execute(
            action=BrowserAction.UPLOAD,
            arguments={
                "session_id": sid,
                "selector": "input[type=file]",
                "path": str(self.upload),
            },
            run_id="pw1",
        )
        # No file input on page — expect REJECTED, not fabricated success.
        self.assertEqual(up["status"], BrowserJobStatus.REJECTED.value)


class PlaywrightHonestyWhenNotReady(unittest.TestCase):
    def test_not_tested_marker_when_chromium_absent(self) -> None:
        ready, info = _playwright_ready()
        if ready:
            self.skipTest("Chromium READY — real tests cover this path")
        # Document NOT_TESTED honesty for CI without browsers.
        self.assertFalse(info.get("ready"))
        self.assertIn(info.get("status"), {"UNAVAILABLE", "UNKNOWN"})


if __name__ == "__main__":
    unittest.main()
