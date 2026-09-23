"""Research subsystem — local/web research with evidence ledger and citations."""

from .budgets import budget_catalog, budget_for_depth, list_presets
from .evidence import EvidenceLedger
from .graph import (
    ClaimEvidenceGraph,
    ClaimEvidenceGraphBuilder,
    ReproducibilityBundle,
    ReproducibilityBundleExporter,
    citation_entailment_check,
)
from .local_retrieval import LocalResearchRetriever, build_default_local_retriever
from .planner import apply_plan_edits, build_plan
from .reports import ReportBuilder
from .runner import ResearchRunner
from .service import ResearchService
from .ssrf import SsrfDecision, assert_safe_url, validate_url_for_fetch
from .store import ResearchStore
from .types import (
    AnalysisMode,
    BrainStatus,
    ClaimStatus,
    CitationResolution,
    CoverageSummary,
    ResearchBudget,
    ResearchClaim,
    ResearchConflict,
    ResearchDepth,
    ResearchError,
    ResearchEvent,
    ResearchEvidence,
    ResearchExecutionMode,
    ResearchPhase,
    ResearchPlan,
    ResearchProject,
    ResearchReport,
    ResearchSource,
    ResearchStatus,
    ResearchWorker,
    SourceType,
    WorkerStatus,
)
from .web import HttpWebProvider, UnconfiguredWebProvider, build_web_provider

__all__ = [
    "AnalysisMode",
    "BrainStatus",
    "ClaimEvidenceGraph",
    "ClaimEvidenceGraphBuilder",
    "ClaimStatus",
    "CitationResolution",
    "CoverageSummary",
    "EvidenceLedger",
    "HttpWebProvider",
    "LocalResearchRetriever",
    "ReportBuilder",
    "ReproducibilityBundle",
    "ReproducibilityBundleExporter",
    "ResearchBudget",
    "ResearchClaim",
    "ResearchConflict",
    "ResearchDepth",
    "ResearchError",
    "ResearchEvidence",
    "ResearchEvent",
    "ResearchExecutionMode",
    "ResearchPhase",
    "ResearchPlan",
    "ResearchProject",
    "ResearchReport",
    "ResearchRunner",
    "ResearchService",
    "ResearchSource",
    "ResearchStatus",
    "ResearchStore",
    "ResearchWorker",
    "SourceType",
    "SsrfDecision",
    "UnconfiguredWebProvider",
    "WorkerStatus",
    "apply_plan_edits",
    "assert_safe_url",
    "budget_catalog",
    "budget_for_depth",
    "build_default_local_retriever",
    "build_plan",
    "build_web_provider",
    "citation_entailment_check",
    "list_presets",
    "validate_url_for_fetch",
]
