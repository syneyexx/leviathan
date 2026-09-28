"""Execution workload classification — where heavy work may run.

INLINE_SAFE
    Small/bounded work that may run in the API/control-plane process.

EXTERNAL_PREFERRED
    Moderate work that should prefer durable workers when available.

EXTERNAL_REQUIRED
    Heavy/long/network/model/file work that MUST NOT run inline in the API
    when ``LEVIATHAN_WORKERS_EXTERNALIZE_API`` is enabled.

Static classification (``classify_capability``) is the baseline.
Request-aware classification (``classify_request_workload``) may ESCALATE
INLINE_SAFE → EXTERNAL_REQUIRED for large / recursive / unbounded filesystem
work after path confinement. It never silently downgrades EXTERNAL_REQUIRED.

Classification does not bypass authorization / approval rules.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .file_io_thresholds import (
    FILE_IO_ALWAYS_EXTERNAL,
    FILE_IO_CAPABILITIES,
    FileIoThresholds,
    load_file_io_thresholds,
)


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
# Full CSV parse/profile, parquet, and recursive scans are always external;
# small file.read / file.write / inspect_csv remain INLINE_SAFE statically and
# escalate via classify_request_workload when oversized.
KNOWN_EXTERNAL_REQUIRED_EXTRA: frozenset[str] = frozenset(
    {
        "file.parse_pdf",
        *FILE_IO_ALWAYS_EXTERNAL,
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
    "knowledge.reconcile",
    "embedding.",
    "rerank.",
    "memory.",
    "brain.",
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
        "system.inspect",
        "file.read",
        "file.inspect_csv",
        "file.write",
        "file.hash",
        "file.copy",
        "file.list",
        "workspace.list",
        "git.status",
        "git.diff",
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
    """Resolve static workload class for a capability id.

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
            "file_io",
        }
        if worker_kind in heavy_kinds:
            return ExecutionWorkloadClass.EXTERNAL_REQUIRED
        return ExecutionWorkloadClass.EXTERNAL_PREFERRED

    return ExecutionWorkloadClass.INLINE_SAFE


def _safe_stat_size(path: Path) -> int | None:
    """Cheap size probe for already-confined paths. Never follows escape."""
    try:
        if not path.exists() or not path.is_file():
            return None
        return int(path.stat().st_size)
    except OSError:
        return None


def _content_byte_size(arguments: Mapping[str, Any]) -> int | None:
    if "content" in arguments and arguments["content"] is not None:
        content = arguments["content"]
        if isinstance(content, bytes):
            return len(content)
        return len(str(content).encode("utf-8"))
    if arguments.get("artifact_ref") or arguments.get("content_artifact_id"):
        # Large payloads arrive by reference — treat as external-sized.
        return None
    return 0


def _request_escalates_filesystem(
    capability_id: str,
    arguments: Mapping[str, Any],
    *,
    thresholds: FileIoThresholds,
) -> bool:
    """Return True when request size/scope exceeds inline thresholds.

    Paths in ``arguments`` MUST already be confined. This function may stat
    confined paths for size; it must not be called on raw user paths.
    """
    cap = str(capability_id or "").strip()
    args = dict(arguments or {})

    if cap in FILE_IO_ALWAYS_EXTERNAL:
        return True

    if cap == "file.read":
        max_bytes = args.get("max_bytes")
        if max_bytes is not None and int(max_bytes) > thresholds.max_inline_read_bytes:
            return True
        path = args.get("path")
        if path:
            size = _safe_stat_size(Path(str(path)))
            if size is not None and size > thresholds.max_inline_read_bytes:
                return True
            # Explicit byte range larger than inline ceiling.
            offset = args.get("offset")
            length = args.get("length")
            if length is not None and int(length) > thresholds.max_inline_read_bytes:
                return True
            if offset is not None and size is not None:
                remaining = max(0, size - max(0, int(offset)))
                if remaining > thresholds.max_inline_read_bytes and length is None:
                    return True
        return False

    if cap == "file.write":
        size = _content_byte_size(args)
        if size is None:
            # artifact_ref / staged payload — external
            return True
        if size > thresholds.max_inline_write_bytes:
            return True
        return False

    if cap == "file.hash":
        path = args.get("path") or args.get("source_path")
        if path:
            size = _safe_stat_size(Path(str(path)))
            if size is not None and size > thresholds.max_inline_hash_bytes:
                return True
        return False

    if cap == "file.copy":
        path = args.get("source_path") or args.get("path")
        if path:
            size = _safe_stat_size(Path(str(path)))
            if size is not None and size > thresholds.max_inline_copy_bytes:
                return True
        return False

    if cap == "file.inspect_csv":
        max_bytes = args.get("max_bytes")
        if max_bytes is not None and int(max_bytes) > thresholds.max_inline_csv_bytes:
            return True
        max_rows = args.get("max_rows")
        if max_rows is not None and int(max_rows) > thresholds.max_inline_csv_rows:
            return True
        if args.get("full") or args.get("profile") or args.get("parse_all"):
            return True
        path = args.get("path")
        if path:
            size = _safe_stat_size(Path(str(path)))
            if size is not None and size > thresholds.max_inline_csv_bytes:
                return True
        return False

    if cap in {"workspace.list", "file.list"}:
        if bool(args.get("recursive")):
            return True
        max_entries = args.get("max_entries")
        if max_entries is not None and int(max_entries) > thresholds.max_inline_directory_entries:
            return True
        depth = args.get("max_depth")
        if depth is not None and int(depth) > thresholds.max_inline_recursion_depth:
            return True
        return False

    if cap == "workspace.search":
        # Content search can touch unbounded trees / large files.
        if bool(args.get("recursive", True)):
            # Default search is recursive over workspace — escalate when scope is wide.
            max_hits = args.get("max_hits")
            if max_hits is not None and int(max_hits) > 500:
                return True
            # Path-scoped small searches stay inline; whole-tree without bound escalates
            # only when explicitly marked heavy or max_file_bytes is raised.
            max_file_bytes = args.get("max_file_bytes")
            if max_file_bytes is not None and int(max_file_bytes) > thresholds.max_inline_read_bytes:
                return True
        return False

    if cap == "filesystem.scan":
        return True

    return False


def classify_request_workload(
    capability_id: str,
    arguments: Mapping[str, Any] | None = None,
    *,
    metadata: Mapping[str, Any] | None = None,
    provider_kind: str | None = None,
    filesystem_root: str | Path | None = None,
    thresholds: FileIoThresholds | None = None,
) -> ExecutionWorkloadClass:
    """Request-aware workload class. May escalate; never downgrades.

    ``filesystem_root`` is accepted for API symmetry / future probes. Path
    confinement must already have been applied to ``arguments`` before calling.
    """
    del filesystem_root  # confinement is a caller precondition
    baseline = classify_capability(
        capability_id,
        metadata=metadata,
        provider_kind=provider_kind,
    )
    if baseline == ExecutionWorkloadClass.EXTERNAL_REQUIRED:
        return baseline

    caps = thresholds or load_file_io_thresholds()
    cap = str(capability_id or "").strip()
    if cap in FILE_IO_CAPABILITIES or cap in FILE_IO_ALWAYS_EXTERNAL:
        if _request_escalates_filesystem(cap, arguments or {}, thresholds=caps):
            return ExecutionWorkloadClass.EXTERNAL_REQUIRED
    return baseline


def is_external_required(
    capability_id: str,
    *,
    metadata: Mapping[str, Any] | None = None,
    provider_kind: str | None = None,
    arguments: Mapping[str, Any] | None = None,
    filesystem_root: str | Path | None = None,
    thresholds: FileIoThresholds | None = None,
) -> bool:
    if arguments is not None:
        cls = classify_request_workload(
            capability_id,
            arguments,
            metadata=metadata,
            provider_kind=provider_kind,
            filesystem_root=filesystem_root,
            thresholds=thresholds,
        )
    else:
        cls = classify_capability(
            capability_id,
            metadata=metadata,
            provider_kind=provider_kind,
        )
    return cls == ExecutionWorkloadClass.EXTERNAL_REQUIRED


def request_escalated_filesystem(
    capability_id: str,
    arguments: Mapping[str, Any] | None = None,
    *,
    metadata: Mapping[str, Any] | None = None,
    provider_kind: str | None = None,
    thresholds: FileIoThresholds | None = None,
) -> bool:
    """True when static class was not EXTERNAL_REQUIRED but request escalated."""
    baseline = classify_capability(
        capability_id,
        metadata=metadata,
        provider_kind=provider_kind,
    )
    if baseline == ExecutionWorkloadClass.EXTERNAL_REQUIRED:
        return False
    resolved = classify_request_workload(
        capability_id,
        arguments,
        metadata=metadata,
        provider_kind=provider_kind,
        thresholds=thresholds,
    )
    return resolved == ExecutionWorkloadClass.EXTERNAL_REQUIRED


def file_io_worker_may_execute() -> bool:
    """True when this process is the file_io specialist (or developer mode)."""
    if not externalize_api_enabled():
        return True
    pool = (os.environ.get("LEVIATHAN_WORKER_POOL") or "").strip()
    if pool == "file_io":
        return True
    worker_id = (os.environ.get("LEVIATHAN_WORKER_ID") or "").strip()
    return worker_id.startswith("file_io")


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
    arguments: Mapping[str, Any] | None = None,
    filesystem_root: str | Path | None = None,
    thresholds: FileIoThresholds | None = None,
) -> bool:
    """False when API/non-owner must enqueue rather than run inline.

    Specialist workers may execute their own EXTERNAL_REQUIRED caps.
    Request-escalated filesystem work may only run inline inside ``file_io``
    (or when externalization is disabled / developer mode).
    """
    if not externalize_api_enabled():
        return True

    escalated = False
    if arguments is not None:
        escalated = request_escalated_filesystem(
            capability_id,
            arguments,
            metadata=metadata,
            provider_kind=provider_kind,
            thresholds=thresholds,
        )
        cls = classify_request_workload(
            capability_id,
            arguments,
            metadata=metadata,
            provider_kind=provider_kind,
            filesystem_root=filesystem_root,
            thresholds=thresholds,
        )
    else:
        cls = classify_capability(
            capability_id,
            metadata=metadata,
            provider_kind=provider_kind,
        )

    if cls != ExecutionWorkloadClass.EXTERNAL_REQUIRED:
        return True

    if running_in_worker_process():
        # Escalated generic filesystem work belongs to file_io — other workers
        # must not silently absorb multi-GB reads/hashes in-process.
        if escalated and str(capability_id) in FILE_IO_CAPABILITIES:
            return file_io_worker_may_execute()
        # Statically EXTERNAL file_io caps (parse_csv, scan, …) also require file_io.
        if str(capability_id) in FILE_IO_ALWAYS_EXTERNAL or str(capability_id) in {
            "file.parse_csv",
            "file.profile_csv",
            "file.process_parquet",
            "filesystem.scan",
        }:
            return file_io_worker_may_execute()
        return True

    return False


def execution_class_metadata(cls: ExecutionWorkloadClass | str) -> dict[str, str]:
    """Metadata fragment to attach on CapabilityDefinition."""
    parsed = parse_execution_class(cls) or ExecutionWorkloadClass.INLINE_SAFE
    return {"execution_class": parsed.value}
