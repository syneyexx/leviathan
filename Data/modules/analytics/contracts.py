"""Typed contracts and metric semantics for the LLM / Statistieken dashboard.

Analytics is a READ MODEL. Canonical ownership remains with Knowledge, Dataset,
Research, Agent Fleet, JobRuntime, and system telemetry authorities.
"""

from __future__ import annotations

from typing import Any, Final


ALLOWED_RANGES: Final[frozenset[str]] = frozenset({"1h", "24h", "7d", "30d", "90d"})
DEFAULT_CHART_RANGE: Final[str] = "30d"
DEFAULT_RANKING_RANGE: Final[str] = "7d"
DEFAULT_ACTIVITY_LIMIT: Final[int] = 10
MAX_ACTIVITY_LIMIT: Final[int] = 50

# ---------------------------------------------------------------------------
# KPI metric definitions (server contract)
# ---------------------------------------------------------------------------
#
# knowledgeItems:
#   COUNT(*) FROM knowledge_documents on KNOWLEDGE DB.
#   Canonical Knowledge document record — NOT chunks.
#
# datasets:
#   COUNT(*) FROM datasets on KNOWLEDGE DB. Inventory count, not dataset jobs.
#
# documents:
#   Subset of knowledge_documents whose item-type class is "document"
#   (see ITEM_TYPE_MAP). Distinct from chunks.
#
# researchJobs:
#   COUNT(*) FROM research_runs on CONTROL DB. Durable research runs only —
#   not generic JobRuntime jobs.
#
# avgProcessingSeconds:
#   Weighted average of (finished_at - started_at) for terminal COMPLETED jobs
#   whose capability_id matches PROCESSING_CAPABILITY_PREFIXES.
#   Excludes non-terminal jobs. UNMEASURED when no valid durations exist.
#
# systemUsagePercent:
#   Canonical ResourcePressureSample.pressure * 100 when at least one measured
#   telemetry component exists. NOT (CPU+RAM+GPU+Disk)/4.
#   UNMEASURED when no measurable signals.
#
# Delta semantics:
#   current window [now-range, now] vs previous equal window
#   [now-2*range, now-range). Insufficient previous history → delta null ("—").
#   Direction: lowerIsBetter for processing duration and resource pressure.

METRIC_DEFS: Final[dict[str, dict[str, Any]]] = {
    "knowledgeItems": {
        "unit": "count",
        "source": "knowledge_documents",
        "domain": "KNOWLEDGE",
        "lowerIsBetter": False,
    },
    "datasets": {
        "unit": "count",
        "source": "datasets",
        "domain": "KNOWLEDGE",
        "lowerIsBetter": False,
    },
    "documents": {
        "unit": "count",
        "source": "knowledge_documents (item_type=document)",
        "domain": "KNOWLEDGE",
        "lowerIsBetter": False,
    },
    "researchJobs": {
        "unit": "count",
        "source": "research_runs",
        "domain": "CONTROL",
        "lowerIsBetter": False,
    },
    "avgProcessingSeconds": {
        "unit": "seconds",
        "source": "jobs.started_at/finished_at",
        "domain": "CONTROL",
        "lowerIsBetter": True,
    },
    "systemUsagePercent": {
        "unit": "percent",
        "source": "resource_pressure",
        "domain": "TELEMETRY",
        "lowerIsBetter": True,
    },
}

# Item type classes for knowledge_documents (document.source / chunk.source_type).
# Unknown/legacy → "other" (UI: Overig) — never guessed into Manual.
ITEM_TYPE_MAP: Final[dict[str, str]] = {
    "document": "document",
    "documents": "document",
    "file": "document",
    "pdf": "document",
    "local_file": "document",
    "doc": "document",
    "note": "note",
    "notes": "note",
    "manual_note": "note",
    "web": "web",
    "web_page": "web",
    "web_content": "web",
    "web_search": "web",
    "url": "web",
    "code": "code",
    "code_snippet": "code",
    "snippet": "code",
    "dataset": "dataset",
    "datasets": "dataset",
}

ITEM_TYPE_LABELS: Final[dict[str, str]] = {
    "document": "Documenten",
    "note": "Notities",
    "web": "Web Content",
    "code": "Code Snippets",
    "dataset": "Datasets",
    "other": "Overig",
    "unknown": "Onbekend",
}

# Source provenance classes (document.source + provenance.kind).
SOURCE_CLASS_MAP: Final[dict[str, str]] = {
    "web": "web_scraping",
    "web_page": "web_scraping",
    "web_search": "web_scraping",
    "web_scraping": "web_scraping",
    "scrape": "web_scraping",
    "manual": "manual",
    "operator": "manual",
    "user": "manual",
    "handmatig": "manual",
    "agent": "agent_research",
    "agent_research": "agent_research",
    "research": "agent_research",
    "import": "import",
    "imported": "import",
    "upload": "import",
    "local": "import",
    "local_file": "import",
    "file": "import",
    "api": "api",
    "huggingface": "api",
    "hf": "api",
}

SOURCE_CLASS_LABELS: Final[dict[str, str]] = {
    "web_scraping": "Web Scraping",
    "manual": "Handmatig",
    "agent_research": "Agent Research",
    "import": "Import",
    "api": "API",
    "other": "Overig",
    "unknown": "Onbekend",
}

# Dataset semantic categories → dashboard display buckets.
# Uses canonical DatasetCategory values; unknown → Onbekend/Overig.
DATASET_TYPE_BUCKETS: Final[dict[str, str]] = {
    "EDUCATION_LANGUAGE": "training",
    "TECHNOLOGY_SOFTWARE": "training",
    "GENERAL": "training",
    "FINANCE_TRADING": "market",
    "CRYPTO_BLOCKCHAIN": "market",
    "BUSINESS_ECONOMICS": "market",
    "RESEARCH_PUBLICATIONS": "research",
    "SCIENCE_ENGINEERING": "research",
    "HEALTH_MEDICINE": "research",
    "LAW_REGULATION": "research",
    "NEWS_MEDIA": "research",
    # evaluation / synthetic are set via metadata flags when present
}

DATASET_TYPE_LABELS: Final[dict[str, str]] = {
    "training": "Training Data",
    "market": "Marktdata",
    "research": "Onderzoeksdata",
    "evaluation": "Evaluatie Data",
    "synthetic": "Synthetische Data",
    "other": "Overig",
    "unknown": "Onbekend",
}

# Research activity series categories (product semantics ← durable fields).
# Prefer typed project/run metadata over name substring matching.
RESEARCH_ACTIVITY_LABELS: Final[dict[str, str]] = {
    "web_research": "Web Research",
    "analyse": "Analyse",
    "trading": "Trading",
    "agent_research": "Agent Research",
    "other": "Overig",
}

# Job capability prefixes → processing task class.
PROCESSING_CAPABILITY_PREFIXES: Final[dict[str, tuple[str, ...]]] = {
    "document_processing": (
        "knowledge.ingest",
        "knowledge.parse",
        "knowledge.process",
        "knowledge.prepare",
        "source_ingestion",
    ),
    "web_scraping": (
        "research.web",
        "browser.",
        "research.fetch",
    ),
    "embedding_generation": (
        "embedding.",
        "knowledge.embed",
    ),
    "knowledge_extraction": (
        "knowledge.extract",
        "research.claim",
        "research.synth",
        "research.analyze",
    ),
    "dataset_processing": (
        "dataset.",
    ),
}

PROCESSING_TASK_LABELS: Final[dict[str, str]] = {
    "document_processing": "Document Verwerking",
    "web_scraping": "Web Scraping",
    "embedding_generation": "Embedding Generatie",
    "knowledge_extraction": "Kennis Extractie",
    "dataset_processing": "Dataset Verwerking",
}

TERMINAL_JOB_STATES: Final[frozenset[str]] = frozenset(
    {"COMPLETED", "completed", "SUCCEEDED", "succeeded", "READY", "ready"}
)
FAILED_JOB_STATES: Final[frozenset[str]] = frozenset(
    {"FAILED", "failed", "ERROR", "error", "UNVERIFIED", "interrupted", "INTERRUPTED"}
)

ACTIVITY_EVENT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "knowledge_added",
        "dataset_processed",
        "research_completed",
        "sync",
        "embeddings",
        "other",
    }
)


def normalize_range(range_key: str | None, *, default: str = DEFAULT_CHART_RANGE) -> str:
    key = (range_key or default).strip().lower()
    return key if key in ALLOWED_RANGES else default


def classify_item_type(raw: str | None) -> str:
    if raw is None or not str(raw).strip():
        return "unknown"
    key = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    return ITEM_TYPE_MAP.get(key, "other" if key else "unknown")


def classify_source(raw: str | None) -> str:
    if raw is None or not str(raw).strip():
        return "unknown"
    key = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    return SOURCE_CLASS_MAP.get(key, "other" if key else "unknown")


def classify_dataset_type(
    *,
    primary_category: str | None,
    metadata: dict[str, Any] | None = None,
) -> str:
    meta = metadata or {}
    # Explicit flags win over category heuristics.
    if meta.get("isSynthetic") or meta.get("synthetic") or str(meta.get("kind") or "").lower() == "synthetic":
        return "synthetic"
    if meta.get("isEvaluation") or meta.get("evaluation") or str(meta.get("split") or "").lower() in {
        "eval",
        "evaluation",
        "test",
        "validation",
    }:
        return "evaluation"
    cat = (primary_category or "").strip().upper()
    if not cat or cat in {"UNCATEGORIZED", "OTHER"}:
        return "unknown" if not cat or cat == "UNCATEGORIZED" else "other"
    return DATASET_TYPE_BUCKETS.get(cat, "other")


def classify_research_activity(
    *,
    allow_web: bool | None = None,
    execution_mode: str | None = None,
    topic: str | None = None,
    analysis_mode: str | None = None,
    connected_datasets: list[Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Map durable research project/run fields to activity series.

    Order: explicit metadata category → trading signals → web → team/agent → analyse → other.
    Does not classify from arbitrary title substrings alone when typed fields exist.
    """
    meta = metadata or {}
    explicit = str(meta.get("activityCategory") or meta.get("activity_category") or "").strip().lower()
    if explicit in RESEARCH_ACTIVITY_LABELS:
        return explicit

    topic_l = (topic or "").strip().lower()
    mode = (execution_mode or "").strip().lower()
    analysis = (analysis_mode or "").strip().lower()

    trading_hint = bool(meta.get("trading") or meta.get("marketSim") or meta.get("market_sim"))
    if trading_hint or "trading" in topic_l or "market" in topic_l:
        return "trading"
    if allow_web is True:
        return "web_research"
    if mode == "team" or bool(meta.get("agentId") or meta.get("agent_id")):
        return "agent_research"
    if analysis and analysis not in {"deterministic_fallback", ""}:
        return "analyse"
    if connected_datasets:
        return "analyse"
    return "other"


def processing_task_for_capability(capability_id: str | None) -> str | None:
    cap = (capability_id or "").strip().lower()
    if not cap:
        return None
    for task, prefixes in PROCESSING_CAPABILITY_PREFIXES.items():
        for prefix in prefixes:
            if cap.startswith(prefix.lower()) or prefix.lower() in cap:
                return task
    return None
