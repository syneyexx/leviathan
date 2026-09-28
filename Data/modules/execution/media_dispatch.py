"""Centralized external dispatch for media processing work.

Production media operations always enqueue onto the ``media`` pool.
``via_job`` is accepted for compatibility but never selects inline execution.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from Data.modules.execution.workload import ExecutionWorkloadClass
from Data.modules.jobs.states import JobState, TERMINAL_JOB_STATES
from Data.modules.workers.pools import pool_for_capability

DEFAULT_INTERACTIVE_WAIT_SECONDS = 8.0
DEFAULT_BATCH_WAIT_SECONDS = 0.5

MEDIA_LIVE_CAPABILITIES = frozenset(
    {
        "media.probe",
        "media.thumbnail",
        "media.image_generate",
        "media.image_edit",
        "media.video_ingest",
        "media.vision_inspect",
        "media.cross_modal_search",
        "media.transcode",
        "media.convert",
        "media.audio.process",
        "media.video.process",
        "media.image.batch",
    }
)

MEDIA_INLINE_SAFE_CAPABILITIES = frozenset(
    {
        "media.status",
    }
)


def resource_class_for_media_capability(capability_id: str) -> str:
    cap = str(capability_id or "")
    if cap in {
        "media.transcode",
        "media.convert",
        "media.video.process",
        "media.audio.process",
        "media.video_ingest",
        "media.image.batch",
    }:
        return "CPU_HEAVY"
    if cap in {"media.thumbnail", "media.image_generate", "media.image_edit", "media.vision_inspect"}:
        return "MEMORY_HEAVY"
    return "IO_HEAVY"


def latency_class_for_media_capability(capability_id: str) -> str:
    cap = str(capability_id or "")
    if cap in {
        "media.transcode",
        "media.convert",
        "media.video.process",
        "media.audio.process",
        "media.video_ingest",
        "media.image.batch",
        "media.image_generate",
    }:
        return "background"
    return "interactive"


def enqueue_media_job(
    job_runtime: Any,
    *,
    capability_id: str,
    arguments: Mapping[str, Any] | None = None,
    approval_id: str | None = None,
    requested_by: str = "api.media",
    run_id: str | None = None,
    trace_id: str | None = None,
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
    timeout_seconds: float | None = 600.0,
) -> Any:
    """Enqueue a durable media job. Never executes inline / process_next."""
    pool = pool_for_capability(capability_id)
    if pool != "media" and (
        capability_id.startswith("media.") or capability_id in MEDIA_LIVE_CAPABILITIES
    ):
        pool = "media"
    meta = {
        "execution_class": ExecutionWorkloadClass.EXTERNAL_REQUIRED.value,
        "offload_reason": "media_external_required",
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
        resource_class=resource_class_for_media_capability(capability_id),
        domain="media",
        consumer=requested_by,
        latency_class=latency_class_for_media_capability(capability_id),
        timeout_seconds=timeout_seconds,
        metadata=meta,
    )


def await_media_job(
    job_runtime: Any,
    job: Any,
    *,
    wait_seconds: float | None = None,
    poll_seconds: float = 0.05,
) -> Any:
    """Bounded wait for an externally executed media job. No process_next."""
    job_id = getattr(job, "job_id", None) or str(job)
    deadline = time.monotonic() + float(
        DEFAULT_INTERACTIVE_WAIT_SECONDS if wait_seconds is None else wait_seconds
    )
    current = job_runtime.get(job_id) or job
    while time.monotonic() < deadline:
        state = getattr(current, "state", None)
        if state in TERMINAL_JOB_STATES or (
            isinstance(state, str) and state.upper() in {"COMPLETED", "FAILED", "CANCELLED"}
        ):
            return current
        time.sleep(max(0.01, float(poll_seconds)))
        refreshed = job_runtime.get(job_id)
        if refreshed is not None:
            current = refreshed
    return current


def enqueue_and_maybe_await_media(
    job_runtime: Any,
    *,
    capability_id: str,
    arguments: Mapping[str, Any] | None = None,
    approval_id: str | None = None,
    requested_by: str = "api.media",
    run_id: str | None = None,
    trace_id: str | None = None,
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
    wait_seconds: float | None = None,
    timeout_seconds: float | None = 600.0,
) -> dict[str, Any]:
    """Enqueue media work and optionally await a bounded external result."""
    job = enqueue_media_job(
        job_runtime,
        capability_id=capability_id,
        arguments=arguments,
        approval_id=approval_id,
        requested_by=requested_by,
        run_id=run_id,
        trace_id=trace_id,
        idempotency_key=idempotency_key,
        metadata=metadata,
        timeout_seconds=timeout_seconds,
    )
    if wait_seconds is not None and float(wait_seconds) <= 0:
        final = job
    else:
        final = await_media_job(job_runtime, job, wait_seconds=wait_seconds)
    state = getattr(final, "state", None)
    terminal = state in TERMINAL_JOB_STATES or (
        isinstance(state, str) and state.upper() in {"COMPLETED", "FAILED", "CANCELLED"}
    )
    public = final.public_dict() if hasattr(final, "public_dict") else {"job_id": getattr(final, "job_id", None)}
    return {
        "job": public,
        "job_id": getattr(final, "job_id", None),
        "capability_id": capability_id,
        "queued": not terminal,
        "terminal": bool(terminal),
        "state": state.value if isinstance(state, JobState) else str(state or ""),
        "truth": {
            "requires_capability_gateway": True,
            "no_private_media_bypass": True,
            "executed_inline": False,
            "via_job_ignored_for_topology": True,
            "process_next_forbidden": True,
            "worker_pool": "media",
            "execution_class": ExecutionWorkloadClass.EXTERNAL_REQUIRED.value,
            "fixture_is_not_production": True,
        },
    }
