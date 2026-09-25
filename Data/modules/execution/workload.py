"""Execution workload classification — where heavy work may run.

INLINE_SAFE
    Small/bounded work that may run in the API/control-plane process.

EXTERNAL_PREFERRED
    Moderate work that should prefer durable workers when available.

EXTERNAL_REQUIRED
    Heavy/long/network/model/file work that MUST NOT run inline in the API
    when ``LEVIATHAN_WORKERS_EXTERNALIZE_API`` is enabled.

Classification does not bypass authorization / approval rules.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Any, Mapping

class ExecutionWorkloadClass(str, Enum):
    INLINE_SAFE = "INLINE_SAFE"
    EXTERNAL_PREFERRED = "EXTERNAL_PREFERRED"
    EXTERNAL_REQUIRED = "EXTERNAL_REQUIRED"


def _external_worker_capabilities() -> frozenset[str]:
    """Lazy import to avoid jobs.runtime ↔ execution.workload cycles."""
    try:
        from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES

        return EXTERNAL_WORKER_CAPABILITIES
    except Exception:  # noqa: BLE001
        return frozenset()


# Capability ids that are known-heavy even if metadata is incomplete.
# Includes FunctionRuntime capabilities that must not parse large files in API.
KNOWN_EXTERNAL_REQUIRED_EXTRA: frozenset[str] = frozenset(
    {
        "file.parse_pdf",
    }
)

# Prefixes that default to EXTERNAL_REQUIRED when metadata is silent.
_EXTERNAL_REQUIRED_PREFIXES: tuple[str, ...] = (
    "source_ingestion.",
    "research.",
    "dataset.",
    "knowledge.prepare",
    "knowledge.commit",
    "knowledge.ingest",
    "embedding.",
    "rerank.",
    "evaluation.",
    "training.",
    "model_download.",
    "backup.",
    "maintenance.",
    "market_sim.",
    "agent.",
    "agent_signal.",
    "workflow.",
    "provider.",
    "mcp.call",
    "document_ai.",
    "ocr.",
)

# Cheap control-plane / trivial capabilities.
KNOWN_INLINE_SAFE: frozenset[str] = frozenset(
    {
        "compute.numeric",
        "file.read",
        "file.inspect_csv",
        "file.write",
        "file.list",
        "git.status",
        "git.diff",
        "git.log",
    }
)

_EXTERNAL_PREFERRED_PREFIXES: tuple[str, ...] = (
    "browser.",
    "media.",
    "voice.",
)


def parse_execution_class(value: Any) -> ExecutionWorkloadClass | None:
    if value is None:
        return None
    if isinstance(value, ExecutionWorkloadClass):
        return value
    text = str(value).strip().upper().replace("-", "_")
    if not text:
        return None
    # Soft aliases
    aliases = {
        "INLINE": ExecutionWorkloadClass.INLINE_SAFE,
        "SAFE": ExecutionWorkloadClass.INLINE_SAFE,
        "LOCAL": ExecutionWorkloadClass.INLINE_SAFE,
        "PREFERRED": ExecutionWorkloadClass.EXTERNAL_PREFERRED,
        "ASYNC": ExecutionWorkloadClass.EXTERNAL_PREFERRED,
        "REQUIRED": ExecutionWorkloadClass.EXTERNAL_REQUIRED,
        "EXTERNAL": ExecutionWorkloadClass.EXTERNAL_REQUIRED,
        "HEAVY": ExecutionWorkloadClass.EXTERNAL_REQUIRED,
        "WORKER": ExecutionWorkloadClass.EXTERNAL_REQUIRED,
    }
    if text in aliases:
        return aliases[text]
    try:
        return ExecutionWorkloadClass(text)
    except ValueError:
        return None


def classify_capability(
    capability_id: str,
    *,
    metadata: Mapping[str, Any] | None = None,
    provider_kind: str | None = None,
) -> ExecutionWorkloadClass:
    """Resolve workload class for a capability id.

    Precedence:
    1. Explicit metadata ``execution_class`` / ``workload_class``
    2. Known EXTERNAL_REQUIRED / INLINE_SAFE registries
    3. Prefix heuristics
    4. provider_kind == external → EXTERNAL_REQUIRED
    5. Default INLINE_SAFE
    """
    cap = str(capability_id or "").strip()
    meta = dict(metadata or {})
    # normalized metadata may nest extras
    extra = meta.get("extra") if isinstance(meta.get("extra"), dict) else {}

    explicit = parse_execution_class(
        meta.get("execution_class")
        or meta.get("workload_class")
        or extra.get("execution_class")
        or extra.get("workload_class")
    )
    if explicit is not None:
        return explicit

    known_required = _external_worker_capabilities() | KNOWN_EXTERNAL_REQUIRED_EXTRA
    if cap in known_required:
        return ExecutionWorkloadClass.EXTERNAL_REQUIRED
    if cap in KNOWN_INLINE_SAFE:
        return ExecutionWorkloadClass.INLINE_SAFE

    for prefix in _EXTERNAL_REQUIRED_PREFIXES:
        if cap == prefix.rstrip(".") or cap.startswith(prefix):
            return ExecutionWorkloadClass.EXTERNAL_REQUIRED

    for prefix in _EXTERNAL_PREFERRED_PREFIXES:
        if cap.startswith(prefix):
            return ExecutionWorkloadClass.EXTERNAL_PREFERRED

    kind = (provider_kind or meta.get("provider_kind") or "").strip().lower()
    if kind == "external":
        return ExecutionWorkloadClass.EXTERNAL_REQUIRED

    # worker_kind hint without explicit class → preferred (not forced) unless
    # the worker kind maps to a specialist heavy pool.
    worker_kind = str(meta.get("worker_kind") or extra.get("worker_kind") or "").strip()
    if worker_kind and worker_kind not in {"general", "compute", ""}:
        heavy_kinds = {
            "research",
            "source_ingestion",
            "dataset",
            "knowledge_prepare",
            "knowledge_commit",
            "embedding",
            "rerank",
            "evaluation",
            "training_control",
            "model_download",
            "provider_io",
            "mcp_execution",
            "backup",
            "maintenance",
            "agents",
            "coding",
            "workflow",
            "market_sim",
            "document_ai",
        }
        if worker_kind in heavy_kinds:
            return ExecutionWorkloadClass.EXTERNAL_REQUIRED
        return ExecutionWorkloadClass.EXTERNAL_PREFERRED

    return ExecutionWorkloadClass.INLINE_SAFE


def is_external_required(
    capability_id: str,
    *,
    metadata: Mapping[str, Any] | None = None,
    provider_kind: str | None = None,
) -> bool:
    return (
        classify_capability(
            capability_id,
            metadata=metadata,
            provider_kind=provider_kind,
        )
        == ExecutionWorkloadClass.EXTERNAL_REQUIRED
    )


def externalize_api_enabled() -> bool:
    raw = (os.environ.get("LEVIATHAN_WORKERS_EXTERNALIZE_API") or "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def running_in_worker_process() -> bool:
    return bool(os.environ.get("LEVIATHAN_WORKER_ID"))


def api_may_execute_inline(
    capability_id: str,
    *,
    metadata: Mapping[str, Any] | None = None,
    provider_kind: str | None = None,
) -> bool:
    """False when API must enqueue rather than run the implementation inline."""
    if running_in_worker_process():
        return True
    if not externalize_api_enabled():
        return True
    cls = classify_capability(
        capability_id,
        metadata=metadata,
        provider_kind=provider_kind,
    )
    return cls != ExecutionWorkloadClass.EXTERNAL_REQUIRED


def execution_class_metadata(cls: ExecutionWorkloadClass | str) -> dict[str, str]:
    """Metadata fragment to attach on CapabilityDefinition."""
    parsed = parse_execution_class(cls) or ExecutionWorkloadClass.INLINE_SAFE
    return {"execution_class": parsed.value}
