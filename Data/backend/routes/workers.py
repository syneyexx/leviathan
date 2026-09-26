"""Worker fabric HTTP routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from Data.modules.jobs import JobState


class WorkerPoolScaleBody(BaseModel):
    desiredCount: int = Field(ge=0, le=64)


def build_workers_router(
    *,
    settings: Any,
    job_runtime: Any,
) -> APIRouter:
    router = APIRouter(tags=["workers"])

    @router.get("/api/workers")
    def list_workers(
        pool: Annotated[str | None, Query()] = None,
    ) -> dict:
        from Data.modules.workers.pools import POOL_CATALOG
        from Data.modules.workers.protocol import SupervisorHealth
        from Data.modules.workers.registry import WorkerRegistry
        from Data.modules.workers.settings import load_worker_settings

        registry = WorkerRegistry(settings.database_path)
        registry.initialize()
        workers = registry.list(pool_id=pool)
        wsettings = load_worker_settings()
        overrides = registry.list_pool_desired_overrides()
        lease = registry.get_supervisor_lease() or {}
        health = lease.get("health_state") or SupervisorHealth.UNAVAILABLE.value
        return {
            "workers": [w.public_dict() for w in workers],
            "pools": [
                {
                    **defn.public_dict(),
                    "desired": overrides.get(pid, wsettings.desired_count(pid)),
                }
                for pid, defn in POOL_CATALOG.items()
            ],
            "settings": wsettings.public_dict(),
            "supervisor": {
                "health": health,
                "holder_id": lease.get("holder_id"),
                "holder_pid": lease.get("holder_pid"),
                "expires_at": lease.get("expires_at"),
                "last_heartbeat_at": lease.get("last_heartbeat_at"),
                "last_tick_at": lease.get("last_tick_at"),
                "last_successful_tick_at": lease.get("last_successful_tick_at"),
                "consecutive_tick_failures": lease.get("consecutive_tick_failures") or 0,
                "last_tick_error": lease.get("last_tick_error"),
                "restart_count": lease.get("restart_count") or 0,
                "degraded_reason": lease.get("degraded_reason"),
            },
            "truth": {
                "stale_row_is_not_live_worker": True,
                "model_serving_not_listed_here": True,
                "desired_includes_durable_overrides": True,
            },
        }

    @router.get("/api/workers/dashboard")
    def workers_dashboard() -> dict:
        """Aggregate Worker Fabric read-model for BAT + Agents page."""
        from Data.modules.workers.dashboard import build_worker_fabric_dashboard

        return build_worker_fabric_dashboard(
            db_path=settings.database_path,
            job_getter=job_runtime.get,
            list_jobs=job_runtime.list,
        )

    @router.get("/api/workers/pools")
    def list_worker_pools() -> dict:
        from Data.modules.workers.pools import POOL_CATALOG
        from Data.modules.workers.registry import WorkerRegistry
        from Data.modules.workers.settings import load_worker_settings

        registry = WorkerRegistry(settings.database_path)
        registry.initialize()
        wsettings = load_worker_settings()
        overrides = registry.list_pool_desired_overrides()
        pools = []
        for pid, defn in POOL_CATALOG.items():
            regs = registry.list(pool_id=pid)
            pools.append(
                {
                    **defn.public_dict(),
                    "desired": overrides.get(pid, wsettings.desired_count(pid)),
                    "instances": len(regs),
                    "ready": sum(1 for r in regs if r.state.value == "READY"),
                    "busy": sum(1 for r in regs if r.state.value == "BUSY"),
                    "draining": sum(1 for r in regs if r.state.value == "DRAINING"),
                    "degraded": sum(1 for r in regs if r.state.value == "DEGRADED"),
                    "workers": [r.public_dict() for r in regs],
                }
            )
        # Provider health is separate from worker process health.
        provider_status: dict = {
            "note": "provider_health_is_not_worker_health",
            "providers": {},
        }
        try:
            from Data.modules.provider_io.policy import ProviderPolicyRegistry

            # Control plane does not hold live worker circuits; expose config truth only.
            provider_status["settings"] = ProviderPolicyRegistry().public_status()["settings"]
        except Exception:  # noqa: BLE001
            provider_status["settings"] = {"available": False}
        try:
            queued = [
                j
                for j in job_runtime.list(state=JobState.QUEUED, limit=500)
                if getattr(j, "worker_pool", None) == "provider_io"
            ]
            provider_status["queue_depth"] = len(queued)
        except Exception:  # noqa: BLE001
            provider_status["queue_depth"] = None
        return {"pools": pools, "provider_io": provider_status}

    @router.post("/api/workers/pools/{pool_id}/scale")
    def scale_worker_pool(pool_id: str, payload: WorkerPoolScaleBody) -> dict:
        """Persist desired worker count for a pool. Supervisor hot-applies on next tick.

        Does not spawn subprocesses from the API process. Enforces catalog max_count.
        Protected singleton pools (max_count=1) cannot exceed 1.
        """
        from Data.modules.workers.pools import POOL_CATALOG
        from Data.modules.workers.registry import WorkerRegistry
        from Data.modules.workers.settings import load_worker_settings

        if pool_id not in POOL_CATALOG:
            raise HTTPException(status_code=404, detail=f"Unknown worker pool: {pool_id}")
        defn = POOL_CATALOG[pool_id]
        desired = max(0, min(int(payload.desiredCount), int(defn.max_count)))
        if int(payload.desiredCount) > int(defn.max_count):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "MAX_COUNT_EXCEEDED",
                    "message": f"desiredCount {payload.desiredCount} exceeds max_count {defn.max_count}",
                    "maxCount": defn.max_count,
                },
            )
        registry = WorkerRegistry(settings.database_path)
        registry.initialize()
        result = registry.set_pool_desired_count(pool_id, desired, updated_by="api")
        wsettings = load_worker_settings()
        regs = registry.list(pool_id=pool_id)
        return {
            "pool": {
                **defn.public_dict(),
                "desired": desired,
                "envDesired": wsettings.desired_count(pool_id),
                "instances": len(regs),
                "ready": sum(1 for r in regs if r.state.value == "READY"),
                "busy": sum(1 for r in regs if r.state.value == "BUSY"),
            },
            "override": result,
            "truth": {
                "api_does_not_spawn_subprocesses": True,
                "supervisor_applies_on_tick": True,
                "max_count_enforced": True,
            },
        }

    @router.get("/api/workers/{worker_id}")
    def get_worker(worker_id: str) -> dict:
        from Data.modules.workers.dashboard import build_worker_detail

        detail = build_worker_detail(
            worker_id,
            db_path=settings.database_path,
            job_getter=job_runtime.get,
        )
        if detail is None:
            raise HTTPException(status_code=404, detail=f"Unknown worker: {worker_id}")
        return detail

    return router
