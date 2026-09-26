"""Bridge DurableWorkflow checkpoints into JobRuntime / InstitutionalRepository.

Not a second job queue — checkpoints ride on existing JobRuntime jobs when provided,
and always persist to institutional_workflow_checkpoints.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from .durable_workflows import (
    DurableWorkflow,
    WorkflowCheckpoint,
    WorkflowStep,
    advance_workflow,
    start_workflow,
)
from .persistence import InstitutionalRepository
from .timeutil import now_canonical


def persist_checkpoint(
    repo: InstitutionalRepository,
    checkpoint: WorkflowCheckpoint,
    *,
    job_id: str = "",
) -> dict[str, Any]:
    return repo.upsert_workflow_checkpoint(
        {
            "workflow_id": checkpoint.workflow_id,
            "job_id": job_id or checkpoint.run_id,
            "step_index": checkpoint.current_index,
            "state": checkpoint.public_dict(),
            "status": checkpoint.status,
            "idempotency_key": checkpoint.workflow_id,
        }
    )


def load_checkpoint(
    repo: InstitutionalRepository,
    workflow_id: str,
) -> WorkflowCheckpoint | None:
    row = repo.get_workflow_checkpoint(workflow_id)
    if row is None:
        return None
    state = row.get("state") or {}
    return WorkflowCheckpoint(
        workflow_id=str(state.get("workflowId") or row["workflow_id"]),
        run_id=str(state.get("runId") or row.get("job_id") or ""),
        current_index=int(state.get("currentIndex") or row.get("step_index") or 0),
        status=str(state.get("status") or row.get("status") or "RUNNING"),
        step_results=dict(state.get("stepResults") or {}),
        error=state.get("error"),
    )


def run_workflow_with_persistence(
    *,
    repo: InstitutionalRepository,
    workflow: DurableWorkflow,
    run_id: str,
    step_handler: Callable[[WorkflowStep, WorkflowCheckpoint], Mapping[str, Any]] | None = None,
    job_runtime: Any | None = None,
    job_type: str = "institutional_workflow",
) -> WorkflowCheckpoint:
    """Execute workflow steps with durable checkpoints.

    If job_runtime is provided, enqueue a tracking job (best-effort) but do not
    create a second queue implementation.
    """
    job_id = run_id
    if job_runtime is not None and hasattr(job_runtime, "enqueue"):
        try:
            job = job_runtime.enqueue(
                job_type=job_type,
                payload={
                    "workflow_id": workflow.workflow_id,
                    "run_id": run_id,
                    "ts": now_canonical(),
                },
            )
            if isinstance(job, dict):
                job_id = str(job.get("job_id") or job.get("id") or run_id)
            elif hasattr(job, "job_id"):
                job_id = str(job.job_id)
        except Exception:  # noqa: BLE001
            job_id = run_id

    existing = load_checkpoint(repo, workflow.workflow_id)
    checkpoint = existing or start_workflow(workflow, run_id=run_id)
    persist_checkpoint(repo, checkpoint, job_id=job_id)

    while checkpoint.status not in {"COMPLETED", "FAILED", "CANCELLED"}:
        checkpoint = advance_workflow(
            workflow, checkpoint, step_handler=step_handler
        )
        persist_checkpoint(repo, checkpoint, job_id=job_id)
        if checkpoint.status == "RUNNING" and checkpoint.current_index >= len(workflow.steps):
            checkpoint.status = "COMPLETED"
            persist_checkpoint(repo, checkpoint, job_id=job_id)
            break
    return checkpoint
