"""Coding pool entrypoint — executes already-claimed JobRuntime jobs."""

from __future__ import annotations

from Data.modules.workers.entrypoints._cli import main_for_pool


def _handler(ctx, job):
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    args = dict(job.arguments or {})
    capability = str(getattr(job, "capability_id", "") or "")
    worker_id = str(ctx.get("worker_id") or "")
    session_id = str(args.get("session_id") or "")

    try:
        from Data.modules.coding.worker import process_coding_job
    except ImportError as exc:
        fenced_transition(
            ctx["job_store"],
            job.job_id,
            JobState.FAILED,
            worker_id=worker_id,
            ctx=ctx,
            error=f"Coding handler import failed: {exc}",
            result={
                "capability_id": capability,
                "session_id": session_id,
                "import_error": True,
            },
        )
        return {"error": f"ImportError: {exc}"}

    try:
        result = process_coding_job(ctx, job)
        return result or {}
    except Exception as exc:  # noqa: BLE001
        refreshed = ctx["job_store"].get(job.job_id)
        if refreshed is not None and refreshed.state == JobState.RUNNING:
            fenced_transition(
                ctx["job_store"],
                job.job_id,
                JobState.FAILED,
                worker_id=worker_id,
                ctx=ctx,
                error=f"{type(exc).__name__}: {exc}",
                result={"capability_id": capability, "session_id": session_id},
            )
        return {"error": f"{type(exc).__name__}: {exc}"}


def main(argv=None):
    return main_for_pool("coding", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
