"""Cached browser readiness — measured by the browser worker, read by FastAPI.

A readiness probe that launches Chromium is process work. FastAPI must never
call sync_playwright().start() / chromium.launch(); it only reads this cache.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BrowserReadinessSnapshot:
    measured_at: float = 0.0
    worker_state: str = "UNAVAILABLE"  # READY | STARTING | DEGRADED | UNAVAILABLE
    backend_kind: str = "unknown"  # PLAYWRIGHT | LOCAL_DOM | FIXTURE
    chromium: str = "UNAVAILABLE"  # AVAILABLE | UNAVAILABLE
    playwright_package: bool = False
    chromium_executable: bool = False
    driver_started: bool = False
    chromium_launched: bool = False
    navigation_ok: bool = False
    observation_ok: bool = False
    detail: str = ""
    production_capable: bool = False
    truth: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "worker": self.worker_state,
            "backend": self.backend_kind,
            "chromium": self.chromium,
            "playwright_package": self.playwright_package,
            "chromium_executable": self.chromium_executable,
            "driver_started": self.driver_started,
            "chromium_launched": self.chromium_launched,
            "navigation_ok": self.navigation_ok,
            "observation_ok": self.observation_ok,
            "detail": self.detail,
            "production_capable": self.production_capable,
            "measured_at": self.measured_at,
            "stale": self.measured_at <= 0,
            "truth": {
                "package_alone_is_not_ready": True,
                "cached_status_does_not_launch_chromium": True,
                "fixture_is_not_production": self.backend_kind.upper() == "FIXTURE",
                **dict(self.truth),
            },
        }


class BrowserReadinessCache:
    """Process-local readiness cache written by the browser worker."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot = BrowserReadinessSnapshot()

    def read(self) -> BrowserReadinessSnapshot:
        with self._lock:
            return BrowserReadinessSnapshot(**self._snapshot.__dict__)

    def write(self, snapshot: BrowserReadinessSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot

    def update_from_backend_readiness(
        self,
        readiness: dict[str, Any],
        *,
        backend_kind: str,
        worker_state: str = "READY",
    ) -> BrowserReadinessSnapshot:
        ready = bool(readiness.get("ready"))
        snap = BrowserReadinessSnapshot(
            measured_at=time.time(),
            worker_state=worker_state if ready else "DEGRADED",
            backend_kind=str(backend_kind or "unknown").upper(),
            chromium="AVAILABLE" if ready and str(backend_kind).lower() == "playwright" else (
                "UNAVAILABLE" if str(backend_kind).lower() == "playwright" else "N/A"
            ),
            playwright_package=bool(readiness.get("package_available", readiness.get("playwright_package"))),
            chromium_executable=bool(readiness.get("executable_exists", readiness.get("chromium_executable"))),
            driver_started=bool(readiness.get("driver_started", ready)),
            chromium_launched=bool(readiness.get("chromium_launched", ready)),
            navigation_ok=bool(readiness.get("navigation_ok", ready)),
            observation_ok=bool(readiness.get("observation_ok", ready)),
            detail=str(readiness.get("detail") or readiness.get("reason") or ""),
            production_capable=ready and str(backend_kind).lower() != "fixture",
            truth=dict(readiness.get("truth") or {}),
        )
        if str(backend_kind).lower() == "fixture":
            snap.worker_state = "DEGRADED"
            snap.production_capable = False
            snap.detail = snap.detail or "fixture backend is test-only"
        self.write(snap)
        return snap


# Module-level cache so status projection can be shared if co-located in tests.
_GLOBAL_CACHE = BrowserReadinessCache()


def global_browser_readiness_cache() -> BrowserReadinessCache:
    return _GLOBAL_CACHE
