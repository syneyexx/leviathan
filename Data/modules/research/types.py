"""Research workspace domain types — projects, sources, evidence, claims, reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ResearchStatus(str, Enum):
    DRAFT = "draft"
    PLANNED = "planned"
    QUEUED = "queued"
    RESEARCHING = "researching"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class ResearchDepth(str, Enum):
    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"
    EXPERT = "expert"


class ResearchExecutionMode(str, Enum):
    NORMAL = "normal"
    CUSTOM = "custom"


class ClaimStatus(str, Enum):
    SUPPORTED = "supported"
    WEAKLY_SUPPORTED = "weakly_supported"
    DISPUTED = "disputed"
    UNSUPPORTED = "unsupported"
    UNRESOLVED = "unresolved"


class SourceType(str, Enum):
    KNOWLEDGE = "knowledge"
    LOCAL_FILE = "local_file"
    WEB_PAGE = "web_page"
    WEB_SEARCH = "web_search"
    SEED = "seed"


class ParseStatus(str, Enum):
    PENDING = "pending"
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"


class BrainStatus(str, Enum):
    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_APPLICABLE = "not_applicable"


class ResearchPhase(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    SOURCE_INGESTION = "source_ingestion"
    LOCAL_RETRIEVAL = "local_retrieval"
    WEB_SEARCH = "web_search"
    SOURCE_FETCH = "source_fetch"
    SOURCE_PARSE = "source_parse"
    EVIDENCE_EXTRACTION = "evidence_extraction"
    CLAIM_ANALYSIS = "claim_analysis"
    CONFLICT_ANALYSIS = "conflict_analysis"
    QUERY_ADAPTATION = "query_adaptation"
    SYNTHESIS = "synthesis"
    REPORT_GENERATION = "report_generation"
    BRAIN_SYNC = "brain_sync"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkerStatus(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    RETRIEVING_LOCAL = "retrieving_local"
    SEARCHING_WEB = "searching_web"
    FETCHING_SOURCE = "fetching_source"
    PARSING_SOURCE = "parsing_source"
    EXTRACTING_EVIDENCE = "extracting_evidence"
    ANALYZING = "analyzing"
    WAITING_AT_BARRIER = "waiting_at_barrier"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AnalysisMode(str, Enum):
    DETERMINISTIC_FALLBACK = "deterministic_fallback"
    MODEL = "model"


TERMINAL_STATUSES = frozenset(
    {
        ResearchStatus.COMPLETED,
        ResearchStatus.CANCELLED,
        ResearchStatus.FAILED,
    }
)

ACTIVE_STATUSES = frozenset(
    {
        ResearchStatus.QUEUED,
        ResearchStatus.RESEARCHING,
        ResearchStatus.SYNTHESIZING,
        ResearchStatus.CANCELLING,
    }
)


@dataclass(frozen=True)
class ResearchBudget:
    search_queries: int
    urls_per_query: int
    max_sources: int
    rounds: int
    research_workers: int
    max_local_hits: int = 12
    max_evidence_per_source: int = 4

    def public_dict(self) -> dict[str, Any]:
        return {
            "search_queries": self.search_queries,
            "urls_per_query": self.urls_per_query,
            "max_sources": self.max_sources,
            "rounds": self.rounds,
            "research_workers": self.research_workers,
            "max_local_hits": self.max_local_hits,
            "max_evidence_per_source": self.max_evidence_per_source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ResearchBudget":
        raw = dict(data or {})
        return cls(
            search_queries=int(raw.get("search_queries", 2)),
            urls_per_query=int(raw.get("urls_per_query", 4)),
            max_sources=int(raw.get("max_sources", 10)),
            rounds=int(raw.get("rounds", 1)),
            research_workers=int(raw.get("research_workers", 1)),
            max_local_hits=int(raw.get("max_local_hits", 12)),
            max_evidence_per_source=int(raw.get("max_evidence_per_source", 4)),
        )


@dataclass(frozen=True)
class ResearchPlan:
    interpreted_question: str
    scope: str
    assumptions: list[str]
    subquestions: list[str]
    retrieval_queries: list[str]
    preferred_source_types: list[str]
    local_scopes: list[str]
    exclusion_criteria: list[str]
    rounds: int
    budget: ResearchBudget
    notes: str = ""
    stopping_criteria: list[str] = field(default_factory=list)
    evidence_coverage_targets: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "interpreted_question": self.interpreted_question,
            "scope": self.scope,
            "assumptions": list(self.assumptions),
            "subquestions": list(self.subquestions),
            "retrieval_queries": list(self.retrieval_queries),
            "preferred_source_types": list(self.preferred_source_types),
            "local_scopes": list(self.local_scopes),
            "exclusion_criteria": list(self.exclusion_criteria),
            "rounds": self.rounds,
            "budget": self.budget.public_dict(),
            "notes": self.notes,
            "stopping_criteria": list(self.stopping_criteria),
            "evidence_coverage_targets": dict(self.evidence_coverage_targets),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ResearchPlan | None":
        if not data:
            return None
        return cls(
            interpreted_question=str(data.get("interpreted_question") or ""),
            scope=str(data.get("scope") or ""),
            assumptions=list(data.get("assumptions") or []),
            subquestions=list(data.get("subquestions") or []),
            retrieval_queries=list(data.get("retrieval_queries") or []),
            preferred_source_types=list(data.get("preferred_source_types") or []),
            local_scopes=list(data.get("local_scopes") or []),
            exclusion_criteria=list(data.get("exclusion_criteria") or []),
            rounds=int(data.get("rounds") or 1),
            budget=ResearchBudget.from_dict(data.get("budget")),
            notes=str(data.get("notes") or ""),
            stopping_criteria=list(data.get("stopping_criteria") or []),
            evidence_coverage_targets=dict(data.get("evidence_coverage_targets") or {}),
        )


@dataclass(frozen=True)
class CoverageSummary:
    planned_questions: list[str]
    answered_questions: list[str]
    unresolved_questions: list[str]
    source_count: int
    unique_domains: list[str]
    claims_supported: int
    claims_with_conflicts: int
    claims_unsupported: int
    rounds_completed: int
    web_status: str
    notes: list[str] = field(default_factory=list)
    critical_gaps_count: int = 0
    independent_support_ratio: float | None = None
    primary_source_count: int = 0

    def public_dict(self) -> dict[str, Any]:
        return {
            "planned_questions": list(self.planned_questions),
            "answered_questions": list(self.answered_questions),
            "unresolved_questions": list(self.unresolved_questions),
            "source_count": self.source_count,
            "unique_domains": list(self.unique_domains),
            "claims_supported": self.claims_supported,
            "claims_with_conflicts": self.claims_with_conflicts,
            "claims_unsupported": self.claims_unsupported,
            "rounds_completed": self.rounds_completed,
            "web_status": self.web_status,
            "notes": list(self.notes),
            "critical_gaps_count": self.critical_gaps_count,
            "independent_support_ratio": self.independent_support_ratio,
            "primary_source_count": self.primary_source_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CoverageSummary | None":
        if not data:
            return None
        indep_raw = data.get("independent_support_ratio")
        indep: float | None
        if indep_raw is None or indep_raw == "":
            indep = None
        else:
            indep = float(indep_raw)
        return cls(
            planned_questions=list(data.get("planned_questions") or []),
            answered_questions=list(data.get("answered_questions") or []),
            unresolved_questions=list(data.get("unresolved_questions") or []),
            source_count=int(data.get("source_count") or 0),
            unique_domains=list(data.get("unique_domains") or []),
            claims_supported=int(data.get("claims_supported") or 0),
            claims_with_conflicts=int(data.get("claims_with_conflicts") or 0),
            claims_unsupported=int(data.get("claims_unsupported") or 0),
            rounds_completed=int(data.get("rounds_completed") or 0),
            web_status=str(data.get("web_status") or "not_applicable"),
            notes=list(data.get("notes") or []),
            critical_gaps_count=int(data.get("critical_gaps_count") or 0),
            independent_support_ratio=indep,
            primary_source_count=int(data.get("primary_source_count") or 0),
        )


@dataclass(frozen=True)
class ResearchEvent:
    event_id: str
    project_id: str
    event_type: str
    message: str
    payload: dict[str, Any]
    created_at: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "project_id": self.project_id,
            "event_type": self.event_type,
            "message": self.message,
            "payload": dict(self.payload),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ResearchSource:
    source_id: str
    project_id: str
    source_type: SourceType
    created_at: str
    original_uri: str | None = None
    canonical_uri: str | None = None
    title: str | None = None
    author: str | None = None
    published_at: str | None = None
    fetched_at: str | None = None
    content_hash: str | None = None
    mime_type: str | None = None
    snapshot_path: str | None = None
    parse_status: ParseStatus = ParseStatus.PENDING
    parser: str | None = None
    brain_status: BrainStatus = BrainStatus.NOT_APPLICABLE
    brain_document_id: str | None = None
    brain_error: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "project_id": self.project_id,
            "source_type": self.source_type.value,
            "original_uri": self.original_uri,
            "canonical_uri": self.canonical_uri,
            "title": self.title,
            "author": self.author,
            "published_at": self.published_at,
            "fetched_at": self.fetched_at,
            "content_hash": self.content_hash,
            "mime_type": self.mime_type,
            "snapshot_path": self.snapshot_path,
            "parse_status": self.parse_status.value,
            "parser": self.parser,
            "brain_status": self.brain_status.value,
            "brain_document_id": self.brain_document_id,
            "brain_error": self.brain_error,
            "provenance": dict(self.provenance),
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }


@dataclass
class ResearchWorker:
    worker_id: str
    project_id: str
    run_id: str
    worker_index: int
    status: WorkerStatus
    total_rounds: int
    created_at: str
    updated_at: str
    phase: str = ""
    current_round: int = 0
    current_query: str | None = None
    current_task: str | None = None
    sources_added: int = 0
    evidence_added: int = 0
    started_at: str | None = None
    heartbeat_at: str | None = None
    finished_at: str | None = None
    last_error: str | None = None
    completed_rounds: int = 0

    def public_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "project_id": self.project_id,
            "run_id": self.run_id,
            "worker_index": self.worker_index,
            "status": self.status.value,
            "phase": self.phase,
            "current_round": self.current_round,
            "total_rounds": self.total_rounds,
            "completed_rounds": self.completed_rounds,
            "current_query": self.current_query,
            "current_task": self.current_task,
            "sources_added": self.sources_added,
            "evidence_added": self.evidence_added,
            "started_at": self.started_at,
            "heartbeat_at": self.heartbeat_at,
            "finished_at": self.finished_at,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class ResearchRun:
    run_id: str
    project_id: str
    status: ResearchStatus
    execution_mode: ResearchExecutionMode
    workers: int
    rounds_per_worker: int
    created_at: str
    updated_at: str
    phase: ResearchPhase = ResearchPhase.IDLE
    completed_worker_rounds: int = 0
    total_worker_rounds: int = 0
    progress_pct: float = 0.0
    analysis_mode: AnalysisMode = AnalysisMode.DETERMINISTIC_FALLBACK
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "project_id": self.project_id,
            "status": self.status.value,
            "execution_mode": self.execution_mode.value,
            "workers": self.workers,
            "rounds_per_worker": self.rounds_per_worker,
            "phase": self.phase.value,
            "completed_worker_rounds": self.completed_worker_rounds,
            "total_worker_rounds": self.total_worker_rounds,
            "progress_pct": self.progress_pct,
            "analysis_mode": self.analysis_mode.value,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class ResearchEvidence:
    evidence_id: str
    project_id: str
    source_id: str
    span_text: str
    created_at: str
    chunk_id: str | None = None
    location: dict[str, Any] = field(default_factory=dict)
    retrieval_method: str | None = None
    associated_claim_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def citation_key(self) -> str:
        return f"e:{self.evidence_id}"

    def public_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "project_id": self.project_id,
            "source_id": self.source_id,
            "chunk_id": self.chunk_id,
            "span_text": self.span_text,
            "location": dict(self.location),
            "retrieval_method": self.retrieval_method,
            "associated_claim_ids": list(self.associated_claim_ids),
            "citation_key": self.citation_key(),
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ResearchClaim:
    claim_id: str
    project_id: str
    proposition: str
    status: ClaimStatus
    created_at: str
    updated_at: str
    raw_wording: str | None = None
    supporting_evidence_ids: list[str] = field(default_factory=list)
    contradicting_evidence_ids: list[str] = field(default_factory=list)
    source_diversity: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "project_id": self.project_id,
            "proposition": self.proposition,
            "raw_wording": self.raw_wording,
            "status": self.status.value,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "contradicting_evidence_ids": list(self.contradicting_evidence_ids),
            "source_diversity": self.source_diversity,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ResearchConflict:
    conflict_id: str
    project_id: str
    summary: str
    created_at: str
    claim_id: str | None = None
    supporting_evidence_ids: list[str] = field(default_factory=list)
    contradicting_evidence_ids: list[str] = field(default_factory=list)
    analysis: dict[str, Any] = field(default_factory=dict)
    unresolved_questions: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "project_id": self.project_id,
            "claim_id": self.claim_id,
            "summary": self.summary,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "contradicting_evidence_ids": list(self.contradicting_evidence_ids),
            "analysis": dict(self.analysis),
            "unresolved_questions": list(self.unresolved_questions),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ResearchReport:
    report_id: str
    project_id: str
    version: int
    title: str
    body_markdown: str
    created_at: str
    body_html: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    model_profile: dict[str, Any] = field(default_factory=dict)
    generation_trace: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "project_id": self.project_id,
            "version": self.version,
            "title": self.title,
            "body_markdown": self.body_markdown,
            "body_html": self.body_html,
            "evidence_ids": list(self.evidence_ids),
            "source_ids": list(self.source_ids),
            "model_profile": dict(self.model_profile),
            "generation_trace": dict(self.generation_trace),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class CitationResolution:
    citation_key: str
    resolved: bool
    evidence_id: str | None = None
    source_id: str | None = None
    snapshot_path: str | None = None
    span_text: str | None = None
    reason: str | None = None
    location: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "citation_key": self.citation_key,
            "resolved": self.resolved,
            "evidence_id": self.evidence_id,
            "source_id": self.source_id,
            "snapshot_path": self.snapshot_path,
            "span_text": self.span_text,
            "reason": self.reason,
            "location": dict(self.location),
        }


@dataclass
class ResearchProject:
    project_id: str
    title: str
    topic: str
    status: ResearchStatus
    created_at: str
    updated_at: str
    objective: str = ""
    depth: ResearchDepth = ResearchDepth.STANDARD
    allow_web: bool = False
    respect_robots_txt: bool = True
    model_profile: dict[str, Any] = field(default_factory=dict)
    budget: ResearchBudget = field(default_factory=lambda: ResearchBudget(2, 4, 10, 1, 1))
    plan: ResearchPlan | None = None
    coverage: CoverageSummary | None = None
    local_scopes: list[str] = field(default_factory=list)
    seed_sources: list[str] = field(default_factory=list)
    connected_datasets: list[dict[str, Any]] = field(default_factory=list)
    current_round: int = 0
    total_rounds: int = 1
    error: str | None = None
    cancel_requested: bool = False
    worker_pid: int | None = None
    trace_id: str | None = None
    report_version: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    execution_mode: ResearchExecutionMode = ResearchExecutionMode.CUSTOM
    phase: ResearchPhase = ResearchPhase.IDLE
    progress_pct: float = 0.0
    analysis_mode: AnalysisMode = AnalysisMode.DETERMINISTIC_FALLBACK
    active_run_id: str | None = None
    completed_worker_rounds: int = 0
    total_worker_rounds: int = 0
    # Runtime-only counters filled by service when listing.
    source_count: int = 0
    claim_count: int = 0
    evidence_count: int = 0
    conflict_count: int = 0
    web_unavailable_reason: str | None = None
    workers: list[dict[str, Any]] = field(default_factory=list)
    # Kernel job / wait linkage (physical research.advance ownership surface).
    kernel_job_id: str | None = None
    wait_reason: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "title": self.title,
            "topic": self.topic,
            "objective": self.objective,
            "status": self.status.value,
            "depth": self.depth.value,
            "allow_web": self.allow_web,
            "respect_robots_txt": self.respect_robots_txt,
            "model_profile": dict(self.model_profile),
            "budget": self.budget.public_dict(),
            "plan": self.plan.public_dict() if self.plan else None,
            "coverage": self.coverage.public_dict() if self.coverage else None,
            "local_scopes": list(self.local_scopes),
            "seed_sources": list(self.seed_sources),
            "connected_datasets": [dict(d) for d in self.connected_datasets],
            "current_round": self.current_round,
            "total_rounds": self.total_rounds,
            "error": self.error,
            "cancel_requested": self.cancel_requested,
            "worker_pid": self.worker_pid,
            "trace_id": self.trace_id,
            "report_version": self.report_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "execution_mode": self.execution_mode.value,
            "phase": self.phase.value,
            "progress_pct": self.progress_pct,
            "analysis_mode": self.analysis_mode.value,
            "active_run_id": self.active_run_id,
            "completed_worker_rounds": self.completed_worker_rounds,
            "total_worker_rounds": self.total_worker_rounds,
            "source_count": self.source_count,
            "claim_count": self.claim_count,
            "evidence_count": self.evidence_count,
            "conflict_count": self.conflict_count,
            "web_unavailable_reason": self.web_unavailable_reason,
            "workers": list(self.workers),
            "kernel_job_id": self.kernel_job_id,
            "wait_reason": self.wait_reason,
        }


class ResearchError(Exception):
    """Domain error with machine-usable code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}

    def public_dict(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }
