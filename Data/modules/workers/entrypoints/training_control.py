"""Training-control worker — owns trainer subprocess (not the API)."""

from __future__ import annotations

from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState
    from Data.modules.training.service import TrainingService

    args = dict(getattr(job, "arguments", None) or {})
    training_job_id = str(args.get("training_job_id") or "")
    action = str(args.get("action") or "start")
    if not training_job_id:
        fenced_transition(ctx["job_store"], job.job_id, JobState.FAILED, error="missing training_job_id", worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return {}
    try:
        service = TrainingService(ctx["settings"], job_runtime=ctx["job_runtime"])
        if action == "start":
            result = service.execute_control_start(training_job_id)
            fenced_transition(
            ctx["job_store"],
            job.job_id,
            JobState.COMPLETED,
                result={
                    "training_job_id": training_job_id,
                    "status": result.status.value,
                    "worker_pid": result.worker_pid,
                },
            worker_id=str(ctx.get("worker_id") or ""),
            ctx=ctx,
        )
            return {"training_job_id": training_job_id, "status": result.status.value}
        fenced_transition(ctx["job_store"], job.job_id, JobState.FAILED, error=f"unknown action {action}", worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return {}
    except Exception as exc:  # noqa: BLE001
        fenced_transition(ctx["job_store"], job.job_id, JobState.FAILED, error=str(exc)[:500], worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return {"error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    return main_for_pool("training_control", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
