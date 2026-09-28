"""Centralized external dispatch helper for size-aware filesystem work.

Preserves ExecutionGateway as authority. Callers use this instead of
per-route size logic when a request is classified EXTERNAL_REQUIRED.
"""

from __future__ import annotations

from typing import Any, Mapping

from Data.modules.execution.file_io_thresholds import FILE_IO_CAPABILITIES
from Data.modules.execution.workload import (
    ExecutionWorkloadClass,
    classify_request_workload,
)
from Data.modules.workers.pools import pool_for_capability


def resource_class_for_file_capability(capability_id: str) -> str:
    cap = str(capability_id or "")
    if cap in {"file.hash", "file.parse_csv", "file.profile_csv", "file.process_parquet"}:
        return "CPU_HEAVY"
    if cap in {"file.read", "file.write", "file.copy", "filesystem.scan", "workspace.list"}:
        return "IO_HEAVY"
    return "IO_HEAVY"


def enqueue_file_io_job(
    job_runtime: Any,
    *,
    capability_id: str,
    arguments: Mapping[str, Any] | None = None,
    approval_id: str | None = None,
    requested_by: str = "api",
    run_id: str | None = None,
    trace_id: str | None = None,
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
    timeout_seconds: float | None = 600.0,
) -> Any:
    """Enqueue a durable file_io job. Does not execute inline."""
    pool = pool_for_capability(capability_id)
    if pool != "file_io" and capability_id in FILE_IO_CAPABILITIES:
        pool = "file_io"
    meta = {
        "execution_class": ExecutionWorkloadClass.EXTERNAL_REQUIRED.value,
        "offload_reason": "file_io_request_workload",
        **(metadata or {}),
    }
    return job_runtime.enqueue(
        capability_id=capability_id,
        arguments=dict(arguments or {}),
        approval_id=approval_id,
        requested_by=requested_by,
        run_id=run_id,
        trace_id=trace_id,
        idempotency_key=idempotency_key,
        worker_pool=pool,
        resource_class=resource_class_for_file_capability(capability_id),
        domain="file_io",
        consumer=requested_by,
        latency_class="background",
        timeout_seconds=timeout_seconds,
        metadata=meta,
    )


def classify_and_maybe_enqueue(
    *,
    capability_id: str,
    arguments: Mapping[str, Any],
    job_runtime: Any | None,
    metadata: Mapping[str, Any] | None = None,
    provider_kind: str | None = None,
    filesystem_root: Any = None,
    approval_id: str | None = None,
    requested_by: str = "api",
    run_id: str | None = None,
    trace_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Classify confined request; enqueue when EXTERNAL_REQUIRED.

    Returns:
      {"execution_class": ..., "queued": bool, "job": ...|None}
    """
    cls = classify_request_workload(
        capability_id,
        arguments,
        metadata=metadata,
        provider_kind=provider_kind,
        filesystem_root=filesystem_root,
    )
    if cls != ExecutionWorkloadClass.EXTERNAL_REQUIRED:
        return {
            "execution_class": cls.value,
            "queued": False,
            "job": None,
        }
    if job_runtime is None:
        return {
            "execution_class": cls.value,
            "queued": False,
            "job": None,
            "error": "WORKER_UNAVAILABLE",
            "reason": "worker_required",
        }
    job = enqueue_file_io_job(
        job_runtime,
        capability_id=capability_id,
        arguments=arguments,
        approval_id=approval_id,
        requested_by=requested_by,
        run_id=run_id,
        trace_id=trace_id,
        idempotency_key=idempotency_key,
    )
    return {
        "execution_class": cls.value,
        "queued": True,
        "job": job,
        "job_id": getattr(job, "job_id", None),
    }
