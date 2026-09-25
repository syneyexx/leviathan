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
    CrawlReport,
    CrawlStatus,
    HostNotAllowed,
    JourneyPersona,
)
from .playwright_backend import PlaywrightBrowserBackend, PlaywrightUnavailable

# Compatibility aliases (GI9 naming variants).
CrawlBudgets = CrawlBudget
CrawlConfig = CrawlBudget
JourneyReport = CrawlReport
LocalUserJourneyCrawler = BrowserJourneyCrawler

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
