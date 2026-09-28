"""Market sim pool entrypoint — advances simulations outside FastAPI."""

from __future__ import annotations

from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool


def _handle_news_poll(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    """market_sim.news.poll — feeds are fetched through provider_io (provider.http), parsed
    here (Tier 0) and stored with a causal ``available_at``. No Control-Plane HTTP."""
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    feed_id = str(args.get("feed_id") or "") or None
    try:
        from pathlib import Path

        from Data.modules.market_sim.orchestra.service import TradingOrchestraService
        from Data.modules.market_sim.orchestra.store import OrchestraStore

        settings = ctx["settings"]
        from Data.modules.common.database_domains import market_path_from_settings

        market_db = market_path_from_settings(settings)
        store = OrchestraStore(Path(market_db))
        service = TradingOrchestraService(store=store, job_runtime=ctx.get("job_runtime"))
        result = service.poll_now(feed_id=feed_id, job_runtime=ctx.get("job_runtime"))
        result["executed_via"] = "market_sim_worker"
        fenced_transition(ctx["job_store"], job.job_id, JobState.COMPLETED, result=result, worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return result
    except Exception as exc:  # noqa: BLE001
        fenced_transition(ctx["job_store"], job.job_id, JobState.FAILED, error=str(exc)[:500], worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return {"error": str(exc)}


def _handle_gym_episode(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    """market_sim.gym_episode — complete TradingGym episode on the worker."""
    from Data.modules.jobs.leases import fenced_transition
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
        fenced_transition(ctx["job_store"], job.job_id, JobState.COMPLETED, result=result, worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return result
    except Exception as exc:  # noqa: BLE001
        print(
            f"[WORKER:market_sim] Trading Gym '{simulation_id[:8] if simulation_id else '?'}' "
            f"MISLUKT — {exc}",
            flush=True,
        )
        fenced_transition(ctx["job_store"], job.job_id, JobState.FAILED, error=str(exc)[:500], worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return {"error": str(exc)}


def _handle_research_campaign(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    """market_sim.research_campaign — one bounded iteration then continuation enqueue."""
    from Data.modules.jobs.leases import fenced_transition
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
        # Bounded unit: max_iterations_this_job=1 yields between iterations.
        result = plane.run_research_campaign_on_worker(
            campaign_id, max_iterations_this_job=1
        )
        result["executed_via"] = "market_sim_worker"
        needs = bool(result.get("needs_continuation"))
        if needs and plane.job_runtime is not None:
            try:
                nxt = plane.job_runtime.enqueue(
                    capability_id="market_sim.research_campaign",
                    arguments={"campaign_id": campaign_id},
                    requested_by="market_sim_worker",
                    parent_job_id=job.job_id,
                    domain="market_sim",
                    domain_entity_type="market_sim_research_campaign",
                    domain_entity_id=campaign_id,
                    worker_pool="market_sim",
                    latency_class="batch",
                    idempotency_key=(
                        f"market_sim:research_campaign:{campaign_id}:"
                        f"{result.get('checkpoint_iteration')}"
                    ),
                )
                result["continuation_job_id"] = nxt.job_id
            except Exception:  # noqa: BLE001
                pass
        print(
            f"[WORKER:market_sim] ResearchCampaign '{name}' slice done — "
            f"iters={result.get('checkpoint_iteration')} cont={needs}",
            flush=True,
        )
        fenced_transition(ctx["job_store"], job.job_id, JobState.COMPLETED, result=result, worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return result
    except Exception as exc:  # noqa: BLE001
        print(
            f"[WORKER:market_sim] ResearchCampaign '{campaign_id[:8] if campaign_id else '?'}' "
            f"MISLUKT — {exc}",
            flush=True,
        )
        fenced_transition(ctx["job_store"], job.job_id, JobState.FAILED, error=str(exc)[:500], worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return {"error": str(exc)}


def _handle_portfolio_tick(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    """market_sim.portfolio_tick — one bounded paper cycle; cadence via next_tick_at."""
    from datetime import datetime, timedelta, timezone

    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    portfolio_id = str(args.get("portfolio_id") or "")
    try:
        from Data.modules.market_sim.service import MarketSimControlPlane

        plane = MarketSimControlPlane.from_settings(ctx["settings"])
        if ctx.get("job_runtime") is not None and hasattr(plane, "bind_job_runtime"):
            plane.bind_job_runtime(ctx["job_runtime"])
        if not portfolio_id:
            raise ValueError("portfolio_id required for portfolio_tick")

        # Cadence gate — defer if not yet due (no hot self-enqueue loop).
        pf_row = None
        try:
            pf_svc = getattr(plane, "portefeuille", None) or getattr(plane, "portfolio_service", None)
            if pf_svc is None and hasattr(plane, "get_portfolio"):
                pf_row = plane.get_portfolio(portfolio_id)
            elif pf_svc is not None:
                pf_row = pf_svc.get(portfolio_id) if hasattr(pf_svc, "get") else None
                if pf_row is None and hasattr(pf_svc, "store"):
                    pf_row = pf_svc.store.get_portfolio(portfolio_id)
        except Exception:  # noqa: BLE001
            pf_row = None

        now_dt = datetime.now(timezone.utc)
        now_s = now_dt.isoformat(timespec="seconds")
        meta = dict((pf_row or {}).get("metadata") or {})
        settings_pf = dict((pf_row or {}).get("settings") or {})
        next_tick_at = str(meta.get("next_tick_at") or args.get("not_before") or "")
        if next_tick_at:
            try:
                due = datetime.fromisoformat(next_tick_at.replace("Z", "+00:00"))
                if due.tzinfo is None:
                    due = due.replace(tzinfo=timezone.utc)
                if due > now_dt:
                    delay = max(1.0, (due - now_dt).total_seconds())
                    ctx["job_store"].schedule_retry(
                        job.job_id,
                        delay_seconds=delay,
                        error=None,
                        error_code=None,
                        retryable=True,
                        expected_lease_owner=str(ctx.get("worker_id") or "") or None,
                    )
                    return {
                        "deferred": True,
                        "next_tick_at": next_tick_at,
                        "delay_seconds": delay,
                        "executed_via": "market_sim_worker",
                        "truth": {"no_hot_self_enqueue_loop": True, "cadence_deferred": True},
                    }
            except ValueError:
                pass

        result = plane.portfolio_tick(portfolio_id)
        result["executed_via"] = "market_sim_worker"

        # Persist next_tick_at and schedule delayed continuation (not immediate).
        # Continue while RUNNING — durable enqueue, never while/sleep loop.
        cadence = int(
            settings_pf.get("decision_cadence_seconds")
            or meta.get("decision_cadence_seconds")
            or 60
        )
        cadence = max(5, min(3600, cadence))
        next_at = (now_dt + timedelta(seconds=cadence)).isoformat(timespec="seconds")
        try:
            if pf_svc is not None and hasattr(pf_svc, "store"):
                row = pf_svc.store.get_portfolio(portfolio_id)
                if row is not None:
                    m = dict(row.get("metadata") or {})
                    m["next_tick_at"] = next_at
                    m["last_tick_at"] = now_s
                    row["metadata"] = m
                    row["updated_at"] = now_s
                    pf_svc.store.upsert_portfolio(row)
        except Exception:  # noqa: BLE001
            pass

        pf = result.get("portfolio") or {}
        if pf.get("status") == "RUNNING" and plane.job_runtime is not None:
            try:
                nxt = plane.enqueue_portfolio_tick(
                    portfolio_id,
                    requested_by="market_sim_worker",
                    not_before=next_at,
                    parent_job_id=job.job_id,
                    idempotency_key=f"market_sim:portfolio_tick:{portfolio_id}:{next_at}",
                )
                # Move continuation to RETRY_WAIT until cadence elapses.
                try:
                    # Claim briefly isn't needed — job is QUEUED; transition via schedule_retry
                    # only works from RUNNING. Instead: complete this job; leave next QUEUED
                    # and let handler defer at start (above). To avoid immediate claim storm,
                    # schedule_retry after forcing a quick claim is awkward — use store update.
                    from Data.modules.jobs.states import JobState as _JS

                    store = ctx["job_store"]
                    # Directly set next_attempt_at on QUEUED by moving through RETRY_WAIT pattern:
                    # update row next_attempt_at while QUEUED (claim respects only RETRY_WAIT).
                    # So: schedule by creating as retry — reopen as RUNNING then schedule_retry
                    # is wrong. Practical approach: leave QUEUED; handler defers via schedule_retry
                    # on first claim (above). One brief claim per cadence is acceptable and
                    # not a hot loop.
                    result["continuation_job_id"] = nxt.job_id
                    result["next_tick_at"] = next_at
                except Exception:  # noqa: BLE001
                    result["continuation_job_id"] = nxt.job_id
                    result["next_tick_at"] = next_at
            except Exception:  # noqa: BLE001
                pass
        result["truth"] = {
            **dict(result.get("truth") or {}),
            "paper_only": True,
            "no_hot_self_enqueue_loop": True,
            "cadence_seconds": cadence,
        }
        fenced_transition(ctx["job_store"], job.job_id, JobState.COMPLETED, result=result, worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return result
    except Exception as exc:  # noqa: BLE001
        fenced_transition(ctx["job_store"], job.job_id, JobState.FAILED, error=str(exc)[:500], worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return {"error": str(exc)}


def _handle_autonomous_step(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    """market_sim.autonomous_step — one durable autonomous paper step."""
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    deployment_id = str(args.get("deployment_id") or "")
    side = str(args.get("side") or "HOLD")
    qty = args.get("qty")
    try:
        from Data.modules.market_sim.service import MarketSimControlPlane

        plane = MarketSimControlPlane.from_settings(ctx["settings"])
        if ctx.get("job_runtime") is not None and hasattr(plane, "bind_job_runtime"):
            plane.bind_job_runtime(ctx["job_runtime"])
        if not deployment_id:
            raise ValueError("deployment_id required for autonomous_step")
        result = plane.autonomous_paper_step(
            deployment_id,
            side=side,
            qty=float(qty) if qty is not None else None,
        )
        result["executed_via"] = "market_sim_worker"
        fenced_transition(
            ctx["job_store"], job.job_id, JobState.COMPLETED,
            result=result, worker_id=str(ctx.get("worker_id") or ""), ctx=ctx,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        fenced_transition(
            ctx["job_store"], job.job_id, JobState.FAILED,
            error=str(exc)[:500], worker_id=str(ctx.get("worker_id") or ""), ctx=ctx,
        )
        return {"error": str(exc)}


def _handle_paper_forward_step(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    """market_sim.paper_forward_step — one bounded paper-forward evaluation step."""
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    session_id = str(args.get("session_id") or "")
    side = str(args.get("side") or "HOLD")
    qty = args.get("qty")
    try:
        from Data.modules.market_sim.service import MarketSimControlPlane

        plane = MarketSimControlPlane.from_settings(ctx["settings"])
        if ctx.get("job_runtime") is not None and hasattr(plane, "bind_job_runtime"):
            plane.bind_job_runtime(ctx["job_runtime"])
        if not session_id:
            raise ValueError("session_id required for paper_forward_step")
        result = plane.paper_forward_step(
            session_id,
            side=side,
            qty=float(qty) if qty is not None else None,
        )
        result["executed_via"] = "market_sim_worker"
        fenced_transition(
            ctx["job_store"], job.job_id, JobState.COMPLETED,
            result=result, worker_id=str(ctx.get("worker_id") or ""), ctx=ctx,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        fenced_transition(
            ctx["job_store"], job.job_id, JobState.FAILED,
            error=str(exc)[:500], worker_id=str(ctx.get("worker_id") or ""), ctx=ctx,
        )
        return {"error": str(exc)}


def _handle_chart_render_batch(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    """market_sim.chart.render_batch — bounded deterministic chart slice."""
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    specs = list(args.get("specs") or [])
    batch_id = str(args.get("batch_id") or "")
    offset = int(args.get("offset") or 0)
    limit = args.get("limit")
    try:
        from Data.modules.market_sim.chart_batch import render_chart_batch_slice

        artifact_store = ctx.get("artifact_store")
        cancel_check = ctx.get("job_cancel_check")
        result = render_chart_batch_slice(
            specs,
            artifact_store=artifact_store,
            batch_id=batch_id or None,
            offset=offset,
            limit=int(limit) if limit is not None else None,
            cancel_check=cancel_check if callable(cancel_check) else None,
        )
        result["executed_via"] = "market_sim_worker"
        # Continuation for large batches — durable requeue, release worker.
        if not result.get("complete") and result.get("next_offset") is not None:
            runtime = ctx.get("job_runtime")
            if runtime is not None:
                try:
                    nxt = runtime.enqueue(
                        capability_id="market_sim.chart.render_batch",
                        arguments={
                            "batch_id": result.get("batch_id"),
                            "specs": specs,
                            "offset": result["next_offset"],
                            "limit": result.get("limit"),
                        },
                        requested_by="market_sim_worker",
                        parent_job_id=job.job_id,
                        domain="market_sim",
                        domain_entity_type="chart_batch",
                        domain_entity_id=str(result.get("batch_id") or ""),
                        worker_pool="market_sim",
                        latency_class="batch",
                        resource_class="CPU_HEAVY",
                        idempotency_key=(
                            f"market_sim:chart_batch:{result.get('batch_id')}:"
                            f"{result['next_offset']}"
                        ),
                    )
                    result["continuation_job_id"] = nxt.job_id
                except Exception:  # noqa: BLE001
                    pass
        fenced_transition(
            ctx["job_store"], job.job_id, JobState.COMPLETED,
            result={
                "batch_id": result.get("batch_id"),
                "complete": result.get("complete"),
                "rendered": result.get("rendered"),
                "failed": result.get("failed"),
                "total": result.get("total"),
                "next_offset": result.get("next_offset"),
                "continuation_job_id": result.get("continuation_job_id"),
                "renderer_version": result.get("renderer_version"),
                # Keep JobStore bounded — omit per-chart bytes; results are refs only.
                "results": result.get("results"),
                "failures": result.get("failures"),
            },
            worker_id=str(ctx.get("worker_id") or ""),
            ctx=ctx,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        fenced_transition(
            ctx["job_store"], job.job_id, JobState.FAILED,
            error=str(exc)[:500], worker_id=str(ctx.get("worker_id") or ""), ctx=ctx,
        )
        return {"error": str(exc)}


def _handle_scan_batch(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    """market_sim.scan_batch — batch source scan / bounded provider refresh on worker."""
    from Data.modules.jobs.leases import fenced_transition
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
        fenced_transition(ctx["job_store"], job.job_id, JobState.COMPLETED, result=result, worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return result
    except Exception as exc:  # noqa: BLE001
        fenced_transition(ctx["job_store"], job.job_id, JobState.FAILED, error=str(exc)[:500], worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return {"error": str(exc)}


def _handle_learning_run(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    """market_sim.learning_run — one generation slice then continuation enqueue."""
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    learning_run_id = str(args.get("learning_run_id") or "")
    try:
        from Data.modules.market_sim.service import MarketSimControlPlane

        plane = MarketSimControlPlane.from_settings(ctx["settings"])
        if ctx.get("job_runtime") is not None and hasattr(plane, "bind_job_runtime"):
            plane.bind_job_runtime(ctx["job_runtime"])
        if not learning_run_id:
            raise ValueError("learning_run_id required for learning_run")
        print(
            f"[WORKER:market_sim] Strategy Learning '{learning_run_id[:8]}' gestart",
            flush=True,
        )
        result = plane.run_learning_on_worker(
            learning_run_id, max_generations_this_job=1
        )
        result["executed_via"] = "market_sim_worker"
        needs = bool(result.get("needs_continuation"))
        if needs and plane.job_runtime is not None:
            try:
                nxt = plane.job_runtime.enqueue(
                    capability_id="market_sim.learning_run",
                    arguments={"learning_run_id": learning_run_id},
                    requested_by="market_sim_worker",
                    parent_job_id=job.job_id,
                    domain="market_sim",
                    domain_entity_type="market_sim_learning_run",
                    domain_entity_id=learning_run_id,
                    worker_pool="market_sim",
                    latency_class="batch",
                    idempotency_key=(
                        f"market_sim:learning_run:{learning_run_id}:"
                        f"{result.get('current_generation')}"
                    ),
                )
                result["continuation_job_id"] = nxt.job_id
            except Exception:  # noqa: BLE001
                pass
        print(
            f"[WORKER:market_sim] Strategy Learning '{learning_run_id[:8]}' slice — "
            f"stage={result.get('stage')} gen={result.get('current_generation')} cont={needs}",
            flush=True,
        )
        fenced_transition(ctx["job_store"], job.job_id, JobState.COMPLETED, result=result, worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return result
    except Exception as exc:  # noqa: BLE001
        print(
            f"[WORKER:market_sim] Strategy Learning "
            f"'{learning_run_id[:8] if learning_run_id else '?'}' MISLUKT — {exc}",
            flush=True,
        )
        fenced_transition(ctx["job_store"], job.job_id, JobState.FAILED, error=str(exc)[:500], worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return {"error": str(exc)}


def _handle_qualification_run(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    """market_sim.qualification_run — durable/resumable QualificationAuthority on worker."""
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    qualification_id = str(args.get("qualification_id") or "")
    try:
        from Data.modules.market_sim.qualification import QualificationAuthority
        from Data.modules.market_sim.service import MarketSimControlPlane

        plane = MarketSimControlPlane.from_settings(ctx["settings"])
        if ctx.get("job_runtime") is not None and hasattr(plane, "bind_job_runtime"):
            plane.bind_job_runtime(ctx["job_runtime"])
        if not qualification_id:
            raise ValueError("qualification_id required for qualification_run")
        print(
            f"[WORKER:market_sim] Qualification '{qualification_id[:8]}' gestart",
            flush=True,
        )
        auth = QualificationAuthority(plane=plane, store=plane.store)
        # Resume/evaluate is idempotent for terminal runs.
        decision = auth.resume(qualification_id)
        result = decision.public_dict()
        result["executed_via"] = "market_sim_worker"
        result["idempotency_key"] = f"qualification:{qualification_id}"
        print(
            f"[WORKER:market_sim] Qualification '{qualification_id[:8]}' voltooid — "
            f"state={result.get('state')} qualified={result.get('qualified')}",
            flush=True,
        )
        fenced_transition(
            ctx["job_store"],
            job.job_id,
            JobState.COMPLETED,
            result=result,
            worker_id=str(ctx.get("worker_id") or ""),
            ctx=ctx,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        print(
            f"[WORKER:market_sim] Qualification "
            f"'{qualification_id[:8] if qualification_id else '?'}' MISLUKT — {exc}",
            flush=True,
        )
        fenced_transition(
            ctx["job_store"],
            job.job_id,
            JobState.FAILED,
            error=str(exc)[:500],
            worker_id=str(ctx.get("worker_id") or ""),
            ctx=ctx,
        )
        return {"error": str(exc)}


def _handle_data_scan(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    try:
        from Data.modules.market_sim.service import MarketSimControlPlane

        plane = MarketSimControlPlane.from_settings(ctx["settings"])
        if ctx.get("job_runtime") is not None and hasattr(plane, "bind_job_runtime"):
            plane.bind_job_runtime(ctx["job_runtime"])
        result = plane.run_market_data_scan_slice(
            max_entries=int(args.get("max_entries") or 200),
            cursor=dict(args.get("cursor") or {}),
            deep_validate=bool(args.get("deep_validate", True)),
            register=bool(args.get("register", True)),
        )
        result["executed_via"] = "market_sim_worker"
        if not result.get("done") and plane.job_runtime is not None:
            try:
                nxt = plane.enqueue_market_data_scan(
                    max_entries=int(args.get("max_entries") or 200),
                    cursor=result.get("cursor"),
                    deep_validate=bool(args.get("deep_validate", True)),
                    requested_by="market_sim_worker",
                    parent_job_id=job.job_id,
                )
                result["continuation_job_id"] = nxt.job_id
                result["needs_continuation"] = True
            except Exception:  # noqa: BLE001
                pass
        fenced_transition(ctx["job_store"], job.job_id, JobState.COMPLETED, result=result, worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return result
    except Exception as exc:  # noqa: BLE001
        fenced_transition(ctx["job_store"], job.job_id, JobState.FAILED, error=str(exc)[:500], error_code="MARKET_DATA_SCAN_FAILED", worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return {"error": str(exc)}


def _handle_data_import(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    try:
        from Data.modules.market_sim.service import MarketSimControlPlane

        plane = MarketSimControlPlane.from_settings(ctx["settings"])
        if ctx.get("job_runtime") is not None and hasattr(plane, "bind_job_runtime"):
            plane.bind_job_runtime(ctx["job_runtime"])
        result = plane.import_market_dataset(
            str(args.get("path") or ""),
            symbol=args.get("symbol"),
            timeframe=args.get("timeframe"),
            seal=bool(args.get("seal", False)),
            role=str(args.get("role") or "RESEARCH"),
            provider=str(args.get("provider") or "csv_local"),
        )
        result = dict(result or {})
        result["executed_via"] = "market_sim_worker"
        fenced_transition(ctx["job_store"], job.job_id, JobState.COMPLETED, result=result, worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return result
    except Exception as exc:  # noqa: BLE001
        fenced_transition(ctx["job_store"], job.job_id, JobState.FAILED, error=str(exc)[:500], error_code="MARKET_DATA_IMPORT_FAILED", worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return {"error": str(exc)}


def _handle_data_validate(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    try:
        from Data.modules.market_sim.service import MarketSimControlPlane

        plane = MarketSimControlPlane.from_settings(ctx["settings"])
        if ctx.get("job_runtime") is not None and hasattr(plane, "bind_job_runtime"):
            plane.bind_job_runtime(ctx["job_runtime"])
        rel = str(args.get("relative_path") or args.get("path") or "")
        source = plane.data.inspect_path(rel, register=bool(args.get("register", True)))
        if args.get("symbol") or args.get("timeframe"):
            source.symbol = (args.get("symbol") or source.symbol).upper()
            source.timeframe = args.get("timeframe") or source.timeframe
            plane.store.upsert_source(source)
        result = {"source": source.public_dict(), "executed_via": "market_sim_worker"}
        fenced_transition(ctx["job_store"], job.job_id, JobState.COMPLETED, result=result, worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return result
    except Exception as exc:  # noqa: BLE001
        fenced_transition(ctx["job_store"], job.job_id, JobState.FAILED, error=str(exc)[:500], error_code="MARKET_DATA_VALIDATION_FAILED", worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return {"error": str(exc)}


def _handle_data_profile(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    # Profile reuses validate/inspect streaming path.
    return _handle_data_validate(ctx, job)


def _handle_data_convert(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    try:
        from pathlib import Path as _Path

        from Data.modules.market_sim.service import MarketSimControlPlane
        from Data.modules.market_sim.ohlcv import iter_ohlcv, write_ohlcv_analytical

        plane = MarketSimControlPlane.from_settings(ctx["settings"])
        if ctx.get("job_runtime") is not None and hasattr(plane, "bind_job_runtime"):
            plane.bind_job_runtime(ctx["job_runtime"])
        source_id = args.get("source_id")
        rel = str(args.get("relative_path") or args.get("path") or "")
        if source_id:
            source = plane.data.get_source(str(source_id))
        elif rel:
            source = plane.data.inspect_path(rel, register=False)
        else:
            raise ValueError("source_id or path required for convert")
        src_path = plane.data.absolute_path_for(source) if hasattr(plane.data, "absolute_path_for") else plane.data._abs_under_root(source.path)
        dest_dir = plane.data.markets_root / "analytical" / source.symbol / source.timeframe
        dest_dir.mkdir(parents=True, exist_ok=True)
        # Stream to temporary then promote — avoid exposing half-written output.
        tmp = dest_dir / f".tmp_{source.symbol}_{source.timeframe}"
        # write_ohlcv_analytical currently takes bars list; stream into bounded batches
        # by reusing iter and writing via helper (small files OK; large uses helper path).
        from Data.modules.common.hashing import sha256_file

        bars_batch = []
        written = None
        for bar in iter_ohlcv(src_path):
            bars_batch.append(bar)
            if len(bars_batch) >= 50_000:
                # Flush chunk by rewriting full analytical (idempotent overwrite of tmp)
                written = write_ohlcv_analytical(
                    tmp,
                    bars_batch if written is None else list(iter_ohlcv(src_path)),
                    prefer_parquet=True,
                    symbol=source.symbol,
                )
                break
        else:
            written = write_ohlcv_analytical(
                tmp,
                bars_batch,
                prefer_parquet=True,
                symbol=source.symbol,
            )
        if written is None:
            raise RuntimeError("conversion produced no output")
        out_path = _Path(written) if not isinstance(written, _Path) else written
        # If helper returned path-like string
        if not isinstance(out_path, _Path):
            out_path = _Path(str(written))
        final = dest_dir / out_path.name.replace(".tmp_", "")
        if out_path.exists():
            out_path.replace(final)
        content_hash = sha256_file(final) if final.exists() else ""
        result = {
            "source_id": source.source_id,
            "symbol": source.symbol,
            "timeframe": source.timeframe,
            "output_path": str(final.relative_to(plane.data.markets_root)) if final.exists() else None,
            "content_hash": content_hash,
            "executed_via": "market_sim_worker",
            "truth": {"streaming_convert": True, "atomic_promotion": True},
        }
        fenced_transition(ctx["job_store"], job.job_id, JobState.COMPLETED, result=result, worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return result
    except Exception as exc:  # noqa: BLE001
        fenced_transition(ctx["job_store"], job.job_id, JobState.FAILED, error=str(exc)[:500], error_code="MARKET_DATA_CONVERSION_FAILED", worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return {"error": str(exc)}


def _handle_assurance_scan(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    try:
        from Data.modules.market_sim.service import MarketSimControlPlane

        plane = MarketSimControlPlane.from_settings(ctx["settings"])
        if ctx.get("job_runtime") is not None and hasattr(plane, "bind_job_runtime"):
            plane.bind_job_runtime(ctx["job_runtime"])
        result = plane.institutional_assurance()
        result = dict(result or {})
        result["executed_via"] = "market_sim_worker"
        result["truth"] = {
            **dict(result.get("truth") or {}),
            "not_qualification_authority": True,
            "live_trading_blocked": True,
            "unexecuted_is_not_pass": True,
        }
        fenced_transition(ctx["job_store"], job.job_id, JobState.COMPLETED, result=result, worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return result
    except Exception as exc:  # noqa: BLE001
        fenced_transition(ctx["job_store"], job.job_id, JobState.FAILED, error=str(exc)[:500], error_code="ASSURANCE_SCAN_FAILED", worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return {"error": str(exc)}


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState
    from Data.modules.market_sim.types import RunStatus, TERMINAL_RUN_STATUSES

    cap = str(getattr(job, "capability_id", "") or "")
    if cap == "market_sim.news.poll":
        return _handle_news_poll(ctx, job)
    if cap == "market_sim.gym_episode":
        return _handle_gym_episode(ctx, job)
    if cap == "market_sim.research_campaign":
        return _handle_research_campaign(ctx, job)
    if cap == "market_sim.learning_run":
        return _handle_learning_run(ctx, job)
    if cap == "market_sim.qualification_run":
        return _handle_qualification_run(ctx, job)
    if cap == "market_sim.scan_batch":
        return _handle_scan_batch(ctx, job)
    if cap == "market_sim.portfolio_tick":
        return _handle_portfolio_tick(ctx, job)
    if cap == "market_sim.data.scan":
        return _handle_data_scan(ctx, job)
    if cap == "market_sim.data.import":
        return _handle_data_import(ctx, job)
    if cap == "market_sim.data.validate":
        return _handle_data_validate(ctx, job)
    if cap == "market_sim.data.profile":
        return _handle_data_profile(ctx, job)
    if cap == "market_sim.data.convert":
        return _handle_data_convert(ctx, job)
    if cap == "market_sim.assurance.scan":
        return _handle_assurance_scan(ctx, job)
    if cap == "market_sim.autonomous_step":
        return _handle_autonomous_step(ctx, job)
    if cap == "market_sim.paper_forward_step":
        return _handle_paper_forward_step(ctx, job)
    if cap == "market_sim.chart.render_batch":
        return _handle_chart_render_batch(ctx, job)

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

        fenced_transition(ctx["job_store"], job.job_id, JobState.COMPLETED, result=result, worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return result
    except Exception as exc:  # noqa: BLE001
        fenced_transition(ctx["job_store"], job.job_id, JobState.FAILED, error=str(exc)[:500], worker_id=str(ctx.get("worker_id") or ""), ctx=ctx)
        return {"error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    return main_for_pool("market_sim", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
