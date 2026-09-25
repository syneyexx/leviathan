"""Agent Signals pool — delivers / retries / housekeeps Signal Fabric work outside FastAPI."""

from __future__ import annotations

from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool


def _build_fabric(ctx: dict[str, Any]):
    from Data.modules.agents.fleet import AgentFleetService
    from Data.modules.agents.runtime import AgentRuntime
    from Data.modules.agents.signals import SignalFabricService, SignalStore
    from Data.modules.agents.store import AgentFleetStore

    settings = ctx["settings"]
    features = getattr(settings, "features", None)
    agents_enabled = bool(getattr(features, "agents_enabled", True))
    signal_enabled = bool(getattr(features, "signal_fabric_enabled", True))

    store = SignalStore(settings.database_path)
    store.initialize()

    fleet_store = AgentFleetStore(settings.database_path)
    fleet_store.initialize()
    runtime = AgentRuntime(
        gateway=ctx["gateway"],
        jobs=ctx.get("job_runtime"),
        agents_enabled=agents_enabled,
    )
    fleet = AgentFleetService(
        fleet_store,
        runtime,
        job_runtime=ctx.get("job_runtime"),
    )

    fabric = SignalFabricService(
        store,
        fleet=fleet,
        job_runtime=ctx.get("job_runtime"),
        enabled=signal_enabled and agents_enabled,
    )
    try:
        from Data.modules.memory.store import MemoryStore

        mem = MemoryStore(settings.database_path)
        mem.initialize()
        fabric.bind_memory_store(mem)
    except Exception:  # noqa: BLE001
        pass
    return fabric


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    capability = str(getattr(job, "capability_id", "") or "")
    worker_id = str(ctx.get("worker_id") or "agent_signals")

    try:
        fabric = _build_fabric(ctx)
        if capability.endswith("housekeeping") or args.get("action") == "housekeeping":
            result = fabric.housekeeping()
        elif capability.endswith("retry") or args.get("action") == "retry":
            dead_id = str(args.get("dead_letter_id") or "")
            if not dead_id:
                ctx["job_store"].transition(job.job_id, JobState.FAILED, error="missing dead_letter_id")
                return {"error": "missing dead_letter_id"}
            delivery = fabric.retry_dead_letter(dead_id)
            result = {"deliveryId": delivery.delivery_id, "signalId": delivery.signal_id}
        else:
            delivery_id = str(args.get("delivery_id") or "")
            if delivery_id:
                result = fabric.process_delivery(delivery_id, worker_id=worker_id)
            else:
                # Batch claim when job is a wake/poll without specific delivery.
                results = fabric.process_pending(worker_id=worker_id, limit=int(args.get("limit") or 8))
                result = {"processed": results, "count": len(results)}
        ctx["job_store"].transition(job.job_id, JobState.COMPLETED, result=result)
        return result
    except Exception as exc:  # noqa: BLE001
        ctx["job_store"].transition(job.job_id, JobState.FAILED, error=str(exc)[:500])
        return {"error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    return main_for_pool("agent_signals", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
