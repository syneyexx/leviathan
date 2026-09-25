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


def _handle_gym_episode(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    """market_sim.gym_episode — complete TradingGym episode on the worker."""
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    simulation_id = str(args.get("simulation_id") or args.get("run_id") or "")
    try:
        from Data.modules.market_sim.service import MarketSimControlPlane

        plane = MarketSimControlPlane.from_settings(ctx["settings"])
        if ctx.get("job_runtime") is not None and hasattr(plane, "bind_job_runtime"):
            plane.bind_job_runtime(ctx["job_runtime"])
        if not simulation_id:
            raise ValueError("simulation_id required for gym_episode")
        # Terminal observability — worker gestart
        print(
            f"[WORKER:market_sim] Trading Gym '{simulation_id[:8]}' gestart",
            flush=True,
        )
        result = plane.run_gym_episode_on_worker(simulation_id)
        result["executed_via"] = "market_sim_worker"
        print(
            f"[WORKER:market_sim] Trading Gym '{simulation_id[:8]}' voltooid — "
            f"steps={result.get('steps')}",
            flush=True,
        )
        ctx["job_store"].transition(job.job_id, JobState.COMPLETED, result=result)
        return result
    except Exception as exc:  # noqa: BLE001
        print(
            f"[WORKER:market_sim] Trading Gym '{simulation_id[:8] if simulation_id else '?'}' "
            f"MISLUKT — {exc}",
            flush=True,
        )
        ctx["job_store"].transition(job.job_id, JobState.FAILED, error=str(exc)[:500])
        return {"error": str(exc)}


def _handle_research_campaign(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    """market_sim.research_campaign — durable/resumable ResearchCampaign on worker."""
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    campaign_id = str(args.get("campaign_id") or "")
    try:
        from Data.modules.market_sim.service import MarketSimControlPlane

        plane = MarketSimControlPlane.from_settings(ctx["settings"])
        if ctx.get("job_runtime") is not None and hasattr(plane, "bind_job_runtime"):
            plane.bind_job_runtime(ctx["job_runtime"])
        if not campaign_id:
            raise ValueError("campaign_id required for research_campaign")
        camp = plane.get_research_campaign(campaign_id)
        name = camp.get("name") or campaign_id[:8]
        it = camp.get("checkpoint_iteration") or 0
        mx = camp.get("max_iterations") or 0
        print(
            f"[WORKER:market_sim] ResearchCampaign '{name}' iteratie {it}/{mx} gestart",
            flush=True,
        )
        result = plane.run_research_campaign_on_worker(campaign_id)
        result["executed_via"] = "market_sim_worker"
        print(
            f"[WORKER:market_sim] ResearchCampaign '{name}' voltooid — "
            f"iters={result.get('checkpoint_iteration')}",
            flush=True,
        )
        ctx["job_store"].transition(job.job_id, JobState.COMPLETED, result=result)
        return result
    except Exception as exc:  # noqa: BLE001
        print(
            f"[WORKER:market_sim] ResearchCampaign '{campaign_id[:8] if campaign_id else '?'}' "
            f"MISLUKT — {exc}",
            flush=True,
        )
        ctx["job_store"].transition(job.job_id, JobState.FAILED, error=str(exc)[:500])
        return {"error": str(exc)}


def _handle_scan_batch(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    """market_sim.scan_batch — batch source scan / bounded provider refresh on worker."""
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    payload = dict(args.get("payload") or {})
    symbols = args.get("symbols") or payload.get("symbols")
    provider_id = str(args.get("provider_id") or payload.get("provider_id") or "binance_public")
    timeframe = str(args.get("timeframe") or payload.get("timeframe") or "1m")
    limit = int(args.get("limit") or payload.get("limit") or 100)
    try:
        from Data.modules.market_sim.service import MarketSimControlPlane

        plane = MarketSimControlPlane.from_settings(ctx["settings"])
        if ctx.get("job_runtime") is not None and hasattr(plane, "bind_job_runtime"):
            plane.bind_job_runtime(ctx["job_runtime"])
        result = plane.scan_batch(
            symbols=list(symbols) if symbols else None,
            provider_id=provider_id,
            timeframe=timeframe,
            limit=limit,
        )
        result["executed_via"] = "market_sim_worker"
        ctx["job_store"].transition(job.job_id, JobState.COMPLETED, result=result)
        return result
    except Exception as exc:  # noqa: BLE001
        ctx["job_store"].transition(job.job_id, JobState.FAILED, error=str(exc)[:500])
        return {"error": str(exc)}


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    from Data.modules.jobs.states import JobState
    from Data.modules.market_sim.types import RunStatus, TERMINAL_RUN_STATUSES

    cap = str(getattr(job, "capability_id", "") or "")
    if cap == "market_sim.news.poll":
        return _handle_news_poll(ctx, job)
    if cap == "market_sim.gym_episode":
        return _handle_gym_episode(ctx, job)
    if cap == "market_sim.research_campaign":
        return _handle_research_campaign(ctx, job)
    if cap == "market_sim.scan_batch":
        return _handle_scan_batch(ctx, job)

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
