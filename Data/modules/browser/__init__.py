"""Browser automation — fixture (test-only) + local DOM + optional Playwright."""

from .worker import (
    BrowserAction,
    BrowserAutomationStub,
    BrowserBackendKind,
    BrowserJob,
    BrowserJobStatus,
    BrowserObservation,
    BrowserSession,
    BrowserWorker,
    FixtureBrowserBackend,
    resolve_browser_backend,
)

__all__ = [
    "BrowserAction",
    "BrowserAutomationStub",
    "BrowserBackendKind",
    "BrowserJob",
    "BrowserJobStatus",
    "BrowserObservation",
    "BrowserSession",
    "BrowserWorker",
    "FixtureBrowserBackend",
    "resolve_browser_backend",
]
