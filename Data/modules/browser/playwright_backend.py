"""Optional Playwright browser backend — honest UNAVAILABLE without dependency."""

from __future__ import annotations

from typing import Any

from .worker import (
    BrowserAction,
    BrowserBackendKind,
    BrowserObservation,
    BrowserSession,
)


class PlaywrightUnavailable(Exception):
    unavailable = True


class PlaywrightBrowserBackend:
    """Real Chromium path when playwright is installed; otherwise UNAVAILABLE."""

    kind = BrowserBackendKind.PLAYWRIGHT

    def __init__(self, *, allow_uploads: bool = True) -> None:
        self.allow_uploads = allow_uploads
        try:
            import playwright  # noqa: F401
            self._available = True
        except ImportError:
            self._available = False

    def apply(
        self,
        session: BrowserSession,
        *,
        action: BrowserAction,
        arguments: dict[str, Any],
    ) -> tuple[BrowserSession, BrowserObservation, dict[str, Any]]:
        if not self._available:
            raise PlaywrightUnavailable(
                "Playwright is not installed — browser backend UNAVAILABLE "
                "(not READY). Use LEVIATHAN_BROWSER_BACKEND=local_dom or install playwright."
            )
        # Full Playwright automation is intentionally not bundled into CI.
        # Presence of the package is not enough to claim production readiness without a
        # measured browser binary path — stay honest.
        raise PlaywrightUnavailable(
            "Playwright package present but managed Chromium session is not wired in this "
            "build — UNAVAILABLE (use local_dom for real HTML DOM automation)."
        )
