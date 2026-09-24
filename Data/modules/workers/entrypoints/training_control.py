"""Training-control worker — owns trainer subprocess (not the API)."""

from __future__ import annotations

from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    from Data.modules.jobs.states import JobState
    from Data.modules.training.service import TrainingService

    args = dict(getattr(job, "arguments", None) or {})
    training_job_id = str(args.get("training_job_id") or "")
    action = str(args.get("action") or "start")
    if not training_job_id:
        ctx["job_store"].transition(job.job_id, JobState.FAILED, error="missing training_job_id")
        return {}
    try:
        service = TrainingService(ctx["settings"], job_runtime=ctx["job_runtime"])
        if action == "start":
            result = service.execute_control_start(training_job_id)
            ctx["job_store"].transition(
                job.job_id,
                JobState.COMPLETED,
                result={
                    "training_job_id": training_job_id,
                    "status": result.status.value,
                    "worker_pid": result.worker_pid,
                },
            )
            return {"training_job_id": training_job_id, "status": result.status.value}
        ctx["job_store"].transition(job.job_id, JobState.FAILED, error=f"unknown action {action}")
        return {}
    except Exception as exc:  # noqa: BLE001
        ctx["job_store"].transition(job.job_id, JobState.FAILED, error=str(exc)[:500])
        return {"error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    return main_for_pool("training_control", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
