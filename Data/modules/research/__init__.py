"""Research subsystem — local/web research with evidence ledger and citations."""

from .assignments import WORKER_ROLES, ResearchAssignment, plan_assignments
from .budgets import budget_catalog, budget_for_depth, list_presets
from .citation_audit import (
    CitationAuditItem,
    CitationAuditReport,
    CitationAuditStatus,
    audit_report,
)
from .evidence import EvidenceLedger
from .gaps import GapAnalyzer, ResearchGap, select_next_queries, should_stop
from .graph import (
    ClaimEvidenceGraph,
    ClaimEvidenceGraphBuilder,
    ReproducibilityBundle,
    ReproducibilityBundleExporter,
    citation_entailment_check,
)
from .local_retrieval import LocalResearchRetriever, build_default_local_retriever
from .planner import apply_plan_edits, build_plan
from .quality_scorecard import ResearchQualityScorecard, build_quality_scorecard
from .question_model import ResearchQuestionModel, build_question_model
from .reports import ReportBuilder
from .runner import ResearchRunner
from .service import ResearchService
from .source_quality import (
    SourceAssessment,
    assess_source,
    cluster_dependent_sources,
    independent_support_count,
)
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
from .web import HttpWebProvider, UnconfiguredWebProvider, build_web_provider, ChainedWebProvider
from .web_readiness import WebResearchReadiness, build_web_readiness, probe_web_research

__all__ = [
    "AnalysisMode",
    "BrainStatus",
    "CitationAuditItem",
    "CitationAuditReport",
    "CitationAuditStatus",
    "ClaimEvidenceGraph",
    "ClaimEvidenceGraphBuilder",
    "ClaimStatus",
    "CitationResolution",
    "CoverageSummary",
    "EvidenceLedger",
    "GapAnalyzer",
    "HttpWebProvider",
    "LocalResearchRetriever",
    "ReportBuilder",
    "ReproducibilityBundle",
    "ReproducibilityBundleExporter",
    "ResearchAssignment",
    "ResearchBudget",
    "ResearchClaim",
    "ResearchConflict",
    "ResearchDepth",
    "ResearchError",
    "ResearchEvidence",
    "ResearchEvent",
    "ResearchExecutionMode",
    "ResearchGap",
    "ResearchPhase",
    "ResearchPlan",
    "ResearchProject",
    "ResearchQualityScorecard",
    "ResearchQuestionModel",
    "ResearchReport",
    "ResearchRunner",
    "ResearchService",
    "ResearchSource",
    "ResearchStatus",
    "ResearchStore",
    "ResearchWorker",
    "SourceAssessment",
    "SourceType",
    "SsrfDecision",
    "UnconfiguredWebProvider",
    "ChainedWebProvider",
    "WebResearchReadiness",
    "WORKER_ROLES",
    "WorkerStatus",
    "apply_plan_edits",
    "assert_safe_url",
    "assess_source",
    "audit_report",
    "budget_catalog",
    "budget_for_depth",
    "build_default_local_retriever",
    "build_plan",
    "build_quality_scorecard",
    "build_question_model",
    "build_web_provider",
    "build_web_readiness",
    "citation_entailment_check",
    "cluster_dependent_sources",
    "independent_support_count",
    "list_presets",
    "plan_assignments",
    "probe_web_research",
    "select_next_queries",
    "should_stop",
    "validate_url_for_fetch",
]
