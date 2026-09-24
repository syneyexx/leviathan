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
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    mission_id = str(args.get("mission_id") or "")
    if not mission_id:
        ctx["job_store"].transition(job.job_id, JobState.FAILED, error="missing mission_id")
        return {}

    try:
        fleet = _build_fleet(ctx)
        mission = fleet.advance_mission(mission_id)
        result = {
            "mission_id": mission.mission_id,
            "agent_id": mission.agent_id,
            "status": mission.status.value,
            "progress": mission.progress,
            "error": mission.error,
        }
        ctx["job_store"].transition(job.job_id, JobState.COMPLETED, result=result)
        return result
    except Exception as exc:  # noqa: BLE001
        ctx["job_store"].transition(job.job_id, JobState.FAILED, error=str(exc)[:500])
        return {"error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    return main_for_pool("agents", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
