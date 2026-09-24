"""Market sim pool entrypoint — advances simulations outside FastAPI."""

from __future__ import annotations

from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool


def _handle_news_poll(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    """market_sim.news.poll — feeds are fetched through provider_io (provider.http), parsed
    here (Tier 0) and stored with a causal ``available_at``. No Control-Plane HTTP."""
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    feed_id = str(args.get("feed_id") or "") or None
    try:
        from pathlib import Path

        from Data.modules.market_sim.orchestra.service import TradingOrchestraService
        from Data.modules.market_sim.orchestra.store import OrchestraStore

        settings = ctx["settings"]
        store = OrchestraStore(Path(settings.database_path))
        service = TradingOrchestraService(store=store, job_runtime=ctx.get("job_runtime"))
        result = service.poll_now(feed_id=feed_id, job_runtime=ctx.get("job_runtime"))
        result["executed_via"] = "market_sim_worker"
        ctx["job_store"].transition(job.job_id, JobState.COMPLETED, result=result)
        return result
    except Exception as exc:  # noqa: BLE001
        ctx["job_store"].transition(job.job_id, JobState.FAILED, error=str(exc)[:500])
        return {"error": str(exc)}


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    from Data.modules.jobs.states import JobState
    from Data.modules.market_sim.types import RunStatus, TERMINAL_RUN_STATUSES

    if str(getattr(job, "capability_id", "") or "") == "market_sim.news.poll":
        return _handle_news_poll(ctx, job)

    args = dict(getattr(job, "arguments", None) or {})
    simulation_id = str(args.get("simulation_id") or args.get("run_id") or "")
    try:
        from Data.modules.market_sim.service import MarketSimControlPlane

        plane = MarketSimControlPlane.from_settings(ctx["settings"])
        if ctx.get("job_runtime") is not None and hasattr(plane, "bind_job_runtime"):
            plane.bind_job_runtime(ctx["job_runtime"])

        advanced = False
        if simulation_id and hasattr(plane.worker, "process_run"):
            advanced = bool(plane.worker.process_run(simulation_id))
        elif hasattr(plane.worker, "process_next"):
            advanced = bool(plane.worker.process_next())

        result: dict[str, Any] = {
            "advanced": advanced,
            "simulation_id": simulation_id or None,
        }
        # One slice per job; enqueue continuation while still active.
        if simulation_id:
            run = plane.store.get_run(simulation_id)
            if run is not None:
                result["run_status"] = run.status
                if run.status not in TERMINAL_RUN_STATUSES and run.status in {
                    RunStatus.QUEUED.value,
                    RunStatus.RUNNING.value,
                    RunStatus.STEPPING.value,
                }:
                    try:
                        nxt = plane.enqueue_advance(
                            simulation_id,
                            parent_job_id=job.job_id,
                            requested_by="market_sim_worker",
                        )
                        result["continuation_job_id"] = nxt.job_id
                    except Exception:  # noqa: BLE001
                        pass

        ctx["job_store"].transition(job.job_id, JobState.COMPLETED, result=result)
        return result
    except Exception as exc:  # noqa: BLE001
        ctx["job_store"].transition(job.job_id, JobState.FAILED, error=str(exc)[:500])
        return {"error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    return main_for_pool("market_sim", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
