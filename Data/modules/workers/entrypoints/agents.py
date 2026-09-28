"""Agents pool entrypoint — advances one fleet mission outside FastAPI."""

from __future__ import annotations

from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool


def _build_fleet(ctx: dict[str, Any]):
    from Data.modules.agents.fleet import AgentFleetService
    from Data.modules.agents.runtime import AgentRuntime
    from Data.modules.agents.store import AgentFleetStore

    settings = ctx["settings"]
    store = AgentFleetStore(settings.database_path)
    store.initialize()
    features = getattr(settings, "features", None)
    agents_enabled = bool(getattr(features, "agents_enabled", True))
    runtime = AgentRuntime(
        gateway=ctx["gateway"],
        jobs=ctx.get("job_runtime"),
        agents_enabled=agents_enabled,
    )
    fleet = AgentFleetService(
        store,
        runtime,
        job_runtime=ctx.get("job_runtime"),
    )
    return fleet


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    mission_id = str(args.get("mission_id") or "")
    if not mission_id:
        fenced_transition(
            ctx["job_store"],
            job.job_id,
            JobState.FAILED,
            error="missing mission_id",
            worker_id=str(ctx.get("worker_id") or ""),
            ctx=ctx,
        )
        return {}

    try:
        fleet = _build_fleet(ctx)
        mission = fleet.advance_mission(mission_id)
        wait = str((mission.metadata or {}).get("wait_reason") or "")
        # Soft continuation when waiting on durable child work — never busy-wait.
        if wait in {"WAITING_CHILD_JOB", "WAITING_CHILDREN"} and ctx.get("job_runtime") is not None:
            try:
                pending = (mission.metadata or {}).get("pending_child_job_id") or ""
                fleet.enqueue_advance(
                    mission_id,
                    requested_by="agents_worker",
                    parent_job_id=job.job_id,
                    generation=f"{mission.created_at}:wait:{wait}:{pending}:{mission.updated_at}",
                )
            except Exception:  # noqa: BLE001
                pass
        result = {
            "mission_id": mission.mission_id,
            "agent_id": mission.agent_id,
            "status": mission.status.value,
            "progress": mission.progress,
            "error": mission.error,
            "wait_reason": wait or None,
        }
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
        fenced_transition(
            ctx["job_store"],
            job.job_id,
            JobState.FAILED,
            error=str(exc)[:500],
            worker_id=str(ctx.get("worker_id") or ""),
            ctx=ctx,
        )
        return {"error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    return main_for_pool("agents", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
