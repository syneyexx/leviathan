"""W60 — Durable state-machine helpers for JobRuntime (not a second queue).

Provides checkpointed step progression that callers persist via jobs.JobRuntime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .status import MeasurementState, DEFAULT_TRUTH


@dataclass(frozen=True)
class WorkflowStep:
    step_id: str
    name: str
    optional: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {"stepId": self.step_id, "name": self.name, "optional": self.optional}


@dataclass
class WorkflowCheckpoint:
    workflow_id: str
    run_id: str
    current_index: int
    status: str  # PENDING | RUNNING | COMPLETED | FAILED | CANCELLED
    step_results: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "workflowId": self.workflow_id,
            "runId": self.run_id,
            "currentIndex": self.current_index,
            "status": self.status,
            "stepResults": dict(self.step_results),
            "error": self.error,
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "not_a_second_job_queue": True,
                "for_job_runtime_substrate": True,
            },
        }


@dataclass
class DurableWorkflow:
    workflow_id: str
    steps: tuple[WorkflowStep, ...]

    def public_dict(self) -> dict[str, Any]:
        return {
            "workflowId": self.workflow_id,
            "steps": [s.public_dict() for s in self.steps],
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "extends_job_runtime": True,
                "not_job_runtime_v2": True,
            },
        }


def start_workflow(workflow: DurableWorkflow, *, run_id: str) -> WorkflowCheckpoint:
    return WorkflowCheckpoint(
        workflow_id=workflow.workflow_id,
        run_id=run_id,
        current_index=0,
        status="PENDING" if workflow.steps else "COMPLETED",
    )


def advance_workflow(
    workflow: DurableWorkflow,
    checkpoint: WorkflowCheckpoint,
    *,
    step_handler: Callable[[WorkflowStep, WorkflowCheckpoint], Mapping[str, Any]] | None = None,
    mark_failed: bool = False,
    error: str | None = None,
) -> WorkflowCheckpoint:
    """Advance one step. Caller must persist checkpoint via JobRuntime — we do not queue."""
    if checkpoint.status in {"COMPLETED", "CANCELLED"}:
        return checkpoint
    if mark_failed:
        checkpoint.status = "FAILED"
        checkpoint.error = error or "failed"
        return checkpoint

    if checkpoint.current_index >= len(workflow.steps):
        checkpoint.status = "COMPLETED"
        return checkpoint

    step = workflow.steps[checkpoint.current_index]
    checkpoint.status = "RUNNING"
    result: dict[str, Any]
    if step_handler is None:
        result = {"status": MeasurementState.OBSERVED.value, "skippedHandler": True}
    else:
        result = dict(step_handler(step, checkpoint))

    if result.get("status") == MeasurementState.FAIL.value and not step.optional:
        checkpoint.step_results[step.step_id] = result
        checkpoint.status = "FAILED"
        checkpoint.error = str(result.get("error") or "step_failed")
        return checkpoint

    checkpoint.step_results[step.step_id] = result
    checkpoint.current_index += 1
    if checkpoint.current_index >= len(workflow.steps):
        checkpoint.status = "COMPLETED"
    else:
        checkpoint.status = "RUNNING"
    return checkpoint


def resume_from_checkpoint(
    workflow: DurableWorkflow,
    checkpoint: Mapping[str, Any] | WorkflowCheckpoint,
) -> WorkflowCheckpoint:
    if isinstance(checkpoint, WorkflowCheckpoint):
        return checkpoint
    return WorkflowCheckpoint(
        workflow_id=str(checkpoint.get("workflow_id") or checkpoint.get("workflowId") or workflow.workflow_id),
        run_id=str(checkpoint.get("run_id") or checkpoint.get("runId") or ""),
        current_index=int(checkpoint.get("current_index") or checkpoint.get("currentIndex") or 0),
        status=str(checkpoint.get("status") or "PENDING"),
        step_results=dict(checkpoint.get("step_results") or checkpoint.get("stepResults") or {}),
        error=checkpoint.get("error"),
    )


def workflow_progress(checkpoint: WorkflowCheckpoint, workflow: DurableWorkflow) -> dict[str, Any]:
    total = len(workflow.steps)
    done = min(checkpoint.current_index, total)
    return {
        "done": done,
        "total": total,
        "ratio": (done / total) if total else 1.0,
        "status": checkpoint.status,
        "truth": {"progress_is_not_success_claim": checkpoint.status != "COMPLETED"},
    }
