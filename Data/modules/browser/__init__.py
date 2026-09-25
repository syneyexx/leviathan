"""Browser automation — fixture (test-only) + local DOM + optional Playwright + QA crawler."""

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
from .qa_crawler import (
    BrowserJourneyCrawler,
    CrawlBudget,
    CrawlBudgets,
    CrawlConfig,
    CrawlReport,
    CrawlStatus,
    HostNotAllowed,
    JourneyPersona,
    LocalUserJourneyCrawler,
)
from .playwright_backend import PlaywrightBrowserBackend, PlaywrightUnavailable

# Compatibility aliases.
JourneyReport = CrawlReport

__all__ = [
    "BrowserAction",
    "BrowserAutomationStub",
    "BrowserBackendKind",
    "BrowserJob",
    "BrowserJobStatus",
    "BrowserJourneyCrawler",
    "BrowserObservation",
    "BrowserSession",
    "BrowserWorker",
    "CrawlBudget",
    "CrawlBudgets",
    "CrawlConfig",
    "CrawlReport",
    "CrawlStatus",
    "FixtureBrowserBackend",
    "HostNotAllowed",
    "JourneyPersona",
    "JourneyReport",
    "LocalUserJourneyCrawler",
    "PlaywrightBrowserBackend",
    "PlaywrightUnavailable",
    "resolve_browser_backend",
]
