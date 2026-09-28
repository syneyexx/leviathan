"""Centralized external dispatch for browser automation / QA work.

Production browser actions always enqueue onto the singleton ``browser`` pool.
``via_job`` is accepted for compatibility but never selects inline execution.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from Data.modules.execution.workload import ExecutionWorkloadClass
from Data.modules.jobs.states import JobState, TERMINAL_JOB_STATES
from Data.modules.workers.pools import pool_for_capability

# Interactive browser actions may briefly await an external result.
DEFAULT_INTERACTIVE_WAIT_SECONDS = 8.0
# Background QA work returns queued immediately (or after a short ack wait).
DEFAULT_QA_WAIT_SECONDS = 0.5

BROWSER_LIVE_CAPABILITIES = frozenset(
    {
        "browser.navigate",
        "browser.extract_text",
        "browser.screenshot",
        "browser.click",
        "browser.type",
        "browser.form_fill",
        "browser.download",
        "browser.upload",
        "browser.verify_state",
        "browser.scroll",
        "browser.wait",
        "browser.keypress",
        "browser.qa.crawl",
        "browser.qa.advance",
        "browser.qa.replay",
    }
)

BROWSER_INLINE_SAFE_CAPABILITIES = frozenset(
    {
        "browser.qa.status",
        "browser.qa.cancel",
        "browser.qa.report",
        "browser.status",
    }
)


def resource_class_for_browser_capability(capability_id: str) -> str:
    cap = str(capability_id or "")
    if cap.startswith("browser.qa."):
        return "CPU_HEAVY"
    if cap in {"browser.screenshot", "browser.download", "browser.upload"}:
        return "MEMORY_HEAVY"
    return "NETWORK_BOUND"


def latency_class_for_browser_capability(capability_id: str) -> str:
    cap = str(capability_id or "")
    if cap in {"browser.qa.crawl", "browser.qa.advance", "browser.qa.replay"}:
        return "background"
    return "interactive"


def enqueue_browser_job(
    job_runtime: Any,
    *,
    capability_id: str,
    arguments: Mapping[str, Any] | None = None,
    approval_id: str | None = None,
    requested_by: str = "api.browser",
    run_id: str | None = None,
    trace_id: str | None = None,
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
    timeout_seconds: float | None = 120.0,
    domain_entity_type: str | None = None,
    domain_entity_id: str | None = None,
) -> Any:
    """Enqueue a durable browser job. Never executes inline / process_next."""
    pool = pool_for_capability(capability_id)
    if pool != "browser" and (
        capability_id.startswith("browser.") or capability_id in BROWSER_LIVE_CAPABILITIES
    ):
        pool = "browser"
    meta = {
        "execution_class": ExecutionWorkloadClass.EXTERNAL_REQUIRED.value,
        "offload_reason": "browser_external_required",
        **(metadata or {}),
    }
    kwargs: dict[str, Any] = {
        "capability_id": capability_id,
        "arguments": dict(arguments or {}),
        "approval_id": approval_id,
        "requested_by": requested_by,
        "run_id": run_id,
        "trace_id": trace_id,
        "idempotency_key": idempotency_key,
        "worker_pool": pool,
        "resource_class": resource_class_for_browser_capability(capability_id),
        "domain": "browser",
        "consumer": requested_by,
        "latency_class": latency_class_for_browser_capability(capability_id),
        "timeout_seconds": timeout_seconds,
        "metadata": meta,
    }
    if domain_entity_type is not None:
        kwargs["domain_entity_type"] = domain_entity_type
    if domain_entity_id is not None:
        kwargs["domain_entity_id"] = domain_entity_id
    return job_runtime.enqueue(**kwargs)


def await_browser_job(
    job_runtime: Any,
    job: Any,
    *,
    wait_seconds: float | None = None,
    poll_seconds: float = 0.05,
) -> Any:
    """Bounded wait for an externally executed browser job.

    Never calls process_next. On deadline expiry returns the latest job record
    (typically still QUEUED/RUNNING) so the caller can surface job_id.
    """
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


def enqueue_and_maybe_await_browser(
    job_runtime: Any,
    *,
    capability_id: str,
    arguments: Mapping[str, Any] | None = None,
    approval_id: str | None = None,
    requested_by: str = "api.browser",
    run_id: str | None = None,
    trace_id: str | None = None,
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
    wait_seconds: float | None = None,
    timeout_seconds: float | None = 120.0,
    domain_entity_type: str | None = None,
    domain_entity_id: str | None = None,
) -> dict[str, Any]:
    """Enqueue browser work and optionally await a bounded external result."""
    job = enqueue_browser_job(
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
        domain_entity_type=domain_entity_type,
        domain_entity_id=domain_entity_id,
    )
    if wait_seconds is not None and float(wait_seconds) <= 0:
        final = job
    else:
        final = await_browser_job(job_runtime, job, wait_seconds=wait_seconds)
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
            "no_private_browser_bypass": True,
            "executed_inline": False,
            "via_job_ignored_for_topology": True,
            "process_next_forbidden": True,
            "worker_pool": "browser",
            "execution_class": ExecutionWorkloadClass.EXTERNAL_REQUIRED.value,
        },
    }
