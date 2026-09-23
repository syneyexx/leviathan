"""Browser automation — fixture worker + honest stub (Wave 5)."""

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
]
