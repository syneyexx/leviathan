"""Workflow pool entrypoint — durable one-step continuation."""

from __future__ import annotations

from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState
    from Data.modules.workflows.runtime import WorkflowRuntime
    from Data.modules.workflows.store import WorkflowStore

    args = dict(getattr(job, "arguments", None) or {})
    workflow_id = str(args.get("workflow_id") or "")
    if not workflow_id:
        fenced_transition(ctx["job_store"], job.job_id, JobState.FAILED, error="missing workflow_id", worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return {}
    store = WorkflowStore(ctx["settings"].database_path)
    store.initialize()
    runtime = WorkflowRuntime(store, ctx["gateway"])
    record = runtime.advance_one_step(workflow_id)
    # If more steps remain, enqueue continuation idempotently
    if record.state.value == "RUNNING" and record.current_step < len(record.steps):
        try:
            ctx["job_runtime"].enqueue(
                capability_id="workflow.advance",
                arguments={"workflow_id": workflow_id},
                requested_by="workflow_worker",
                idempotency_key=f"workflow:advance:{workflow_id}:{record.current_step}",
                domain="workflows",
                domain_entity_type="workflow",
                domain_entity_id=workflow_id,
                worker_pool="workflow",
                parent_job_id=job.job_id,
            )
        except Exception:  # noqa: BLE001
            pass
    fenced_transition(
            ctx["job_store"],
            job.job_id,
            JobState.COMPLETED,
        result={
            "workflow_id": record.workflow_id,
            "state": record.state.value,
            "current_step": record.current_step,
            "steps_total": len(record.steps),
        },
            worker_id=str(ctx.get("worker_id") or ""),
            ctx=ctx,
        )
    return {"workflow_id": workflow_id, "state": record.state.value}


def main(argv: list[str] | None = None) -> int:
    return main_for_pool("workflow", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
