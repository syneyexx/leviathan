"""Externalized cognition advance — durable ``cognition.advance`` jobs.

Deep / long-running cognitive loops enqueue one-step (or small-batch) advances
onto the cognition worker pool instead of blocking the API process.
CognitiveRuntime remains the sole orchestration authority; workers only call
into it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


COGNITION_ADVANCE_CAPABILITY = "cognition.advance"
COGNITION_WORKER_POOL = "cognition"


@dataclass(frozen=True)
class AdvanceJobResult:
    run_id: str
    status: str
    terminal: bool
    iterations_advanced: int
    pending_job_id: str | None = None
    error: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "terminal": self.terminal,
            "iterations_advanced": self.iterations_advanced,
            "pending_job_id": self.pending_job_id,
            "error": self.error,
            "truth": {
                "cognition_advance_is_externalized": True,
                "not_a_second_runtime": True,
                "parent_runtime_remains_authority": True,
            },
        }


def should_externalize_advance(
    *,
    mode: str | None,
    externalize_deep: bool = True,
    force: bool = False,
    job_runtime_bound: bool = False,
) -> bool:
    """Decide whether iterative cognition should leave the API process."""
    if force:
        return True
    if not job_runtime_bound or not externalize_deep:
        return False
    mode_s = str(mode or "").upper()
    return mode_s in {"DEEP", "MAXIMUM"}


def enqueue_cognition_advance(
    job_runtime: Any,
    *,
    run_id: str,
    max_iterations: int = 1,
    cursor_iteration: int = 0,
    requested_by: str = "cognition",
    trace_id: str | None = None,
    parent_job_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """Enqueue an idempotent cognition.advance job for ``run_id``."""
    if job_runtime is None:
        raise RuntimeError("job_runtime not bound; cannot enqueue cognition.advance")
    key = f"cognition.advance:{run_id}:{int(cursor_iteration)}"
    return job_runtime.enqueue(
        capability_id=COGNITION_ADVANCE_CAPABILITY,
        arguments={
            "run_id": run_id,
            "max_iterations": max(1, int(max_iterations)),
            "cursor_iteration": int(cursor_iteration),
        },
        run_id=run_id,
        requested_by=requested_by,
        idempotency_key=key,
        domain="cognition",
        domain_entity_type="cognitive_run",
        domain_entity_id=run_id,
        worker_pool=COGNITION_WORKER_POOL,
        parent_job_id=parent_job_id,
        trace_id=trace_id,
        metadata=dict(metadata or {}) | {"kind": "cognition.advance"},
        resource_class="CPU_HEAVY",
        latency_class="background",
    )
