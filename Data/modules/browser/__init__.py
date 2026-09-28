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
from .errors import (
    BROWSER_ERROR_HTTP_STATUS,
    BROWSER_QA_RESUME_DIVERGED,
    BROWSER_SESSION_EXPIRED,
    BROWSER_SESSION_LOST,
    BROWSER_TARGET_BLOCKED,
    BrowserDomainError,
)
from .readiness import (
    BrowserReadinessCache,
    BrowserReadinessSnapshot,
    global_browser_readiness_cache,
)

# Compatibility aliases (GI9 naming variants).
CrawlConfig = CrawlBudget
JourneyReport = CrawlReport

__all__ = [
    "BROWSER_ERROR_HTTP_STATUS",
    "BROWSER_QA_RESUME_DIVERGED",
    "BROWSER_SESSION_EXPIRED",
    "BROWSER_SESSION_LOST",
    "BROWSER_TARGET_BLOCKED",
    "BrowserAction",
    "BrowserAutomationStub",
    "BrowserBackendKind",
    "BrowserDomainError",
    "BrowserJob",
    "BrowserJobStatus",
    "BrowserJourneyCrawler",
    "BrowserObservation",
    "BrowserReadinessCache",
    "BrowserReadinessSnapshot",
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
    "global_browser_readiness_cache",
    "resolve_browser_backend",
]
