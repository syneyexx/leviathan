"""Cognition pool entrypoint — durable cognition.advance jobs."""

from __future__ import annotations

from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    run_id = str(args.get("run_id") or "")
    if not run_id:
        ctx["job_store"].transition(job.job_id, JobState.FAILED, error="missing run_id")
        return {}

    max_iterations = int(args.get("max_iterations") or 1)
    try:
        from Data.modules.cognition.runtime import CognitiveRuntime
        from Data.modules.cognition.store import CognitionStore

        store = CognitionStore(db_path=ctx["settings"].database_path)
        # Worker constructs a store-backed runtime — still the same CognitiveRuntime class.
        runtime = CognitiveRuntime(
            enabled=True,
            shadow=False,
            iterative=True,
            store=store,
            job_runtime=ctx["job_runtime"],
            externalize_deep=True,
            execution_gateway=ctx.get("gateway"),
        )
        result = runtime.advance_external(
            run_id,
            max_iterations=max_iterations,
            requeue=True,
            parent_job_id=getattr(job, "job_id", None),
        )
        ctx["job_store"].transition(
            job.job_id,
            JobState.COMPLETED,
            result=result if isinstance(result, dict) else {"ok": True},
        )
        return result if isinstance(result, dict) else {"run_id": run_id}
    except Exception as exc:  # noqa: BLE001
        refreshed = ctx["job_store"].get(job.job_id)
        if refreshed and refreshed.state.value == "RUNNING":
            ctx["job_store"].transition(job.job_id, JobState.FAILED, error=str(exc))
        return {"error": str(exc), "run_id": run_id}


def main(argv: list[str] | None = None) -> int:
    return main_for_pool("cognition", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
