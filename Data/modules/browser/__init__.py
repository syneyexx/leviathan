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
    CrawlIssue,
    CrawlReport,
    CrawlStatus,
    HostNotAllowed,
    JourneyPersona,
    LocalUserJourneyCrawler,
)
from .qa_repair import QaRepairBridge, RepairProposal
from .playwright_backend import PlaywrightBrowserBackend, PlaywrightUnavailable

# Compatibility aliases (GI9 naming variants).
CrawlConfig = CrawlBudget
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
    "CrawlIssue",
    "CrawlReport",
    "CrawlStatus",
    "FixtureBrowserBackend",
    "HostNotAllowed",
    "JourneyPersona",
    "JourneyReport",
    "LocalUserJourneyCrawler",
    "PlaywrightBrowserBackend",
    "PlaywrightUnavailable",
    "QaRepairBridge",
    "RepairProposal",
    "resolve_browser_backend",
]
