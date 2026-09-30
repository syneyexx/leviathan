"""Workflow pool entrypoint — durable one-node/step continuation."""

from __future__ import annotations

from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState
    from Data.modules.workflows.runtime import WorkflowRuntime
    from Data.modules.workflows.store import WorkflowStore
    from Data.modules.workflows.types import WorkflowExecutionState, WorkflowState

    args = dict(getattr(job, "arguments", None) or {})
    workflow_id = str(args.get("workflow_id") or args.get("execution_id") or "")
    if not workflow_id:
        fenced_transition(
            ctx["job_store"],
            job.job_id,
            JobState.FAILED,
            error="missing workflow_id",
            worker_id=str(ctx.get("worker_id") or ""),
            ctx=ctx,
        )
        return {}
    store = WorkflowStore(ctx["settings"].database_path)
    store.initialize()
    runtime = WorkflowRuntime(store, ctx["gateway"], job_runtime=ctx.get("job_runtime"))
    # Optional schedule store for durable delay resumes.
    try:
        from Data.modules.schedules.store import ScheduleStore

        schedules = ScheduleStore(ctx["settings"].database_path)
        schedules.initialize()
        runtime.bind_schedule_store(schedules)
    except Exception:  # noqa: BLE001
        pass
    record = runtime.advance_one_step(workflow_id)
    meta = dict(record.metadata or {})
    wait = str(meta.get("wait_reason") or "")
    execution = store.get_execution(workflow_id)
    exec_state = execution.state if execution is not None else None

    # Waiting on child/delay: do NOT busy-wait. Soft re-queue with distinct generation.
    if record.state == WorkflowState.RUNNING and wait == "WAITING_CHILD":
        try:
            runtime.enqueue_advance(
                workflow_id,
                requested_by="workflow_worker",
                parent_job_id=job.job_id,
                generation=f"wait:{meta.get('pending_child_job_id')}:{record.current_step}",
            )
        except Exception:  # noqa: BLE001
            pass
    elif exec_state == WorkflowExecutionState.WAITING and wait == "WAITING_DELAY":
        # Delay resume is owned by ScheduleRunner one-shot; do not spin.
        pass
    elif exec_state in {
        WorkflowExecutionState.RUNNING,
        WorkflowExecutionState.STARTING,
        WorkflowExecutionState.QUEUED,
    } or (record.state == WorkflowState.RUNNING and not wait):
        # More graph/linear work remains.
        more = False
        if execution is not None and execution.current_node_id:
            more = True
        elif record.current_step < len(record.steps):
            more = True
        if more and wait not in {"WAITING_APPROVAL", "WAITING_DELAY"}:
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
            "execution_id": execution.execution_id if execution else record.workflow_id,
            "state": (execution.state.value if execution else record.state.value),
            "current_step": record.current_step,
            "current_node_id": execution.current_node_id if execution else None,
            "steps_total": len(record.steps),
            "wait_reason": wait or None,
            "pending_child_job_id": meta.get("pending_child_job_id"),
        },
        worker_id=str(ctx.get("worker_id") or ""),
        ctx=ctx,
    )
    return {
        "workflow_id": workflow_id,
        "state": execution.state.value if execution else record.state.value,
        "wait_reason": wait or None,
    }


def main(argv: list[str] | None = None) -> int:
    return main_for_pool("workflow", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
