"""Module manager HTTP routes — lifecycle owner surface for modules/plugins."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from Data.modules.module_manager import ModuleManagerError


class ModuleExecuteRequest(BaseModel):
    operation: str = Field(min_length=1, max_length=120)
    arguments: dict = Field(default_factory=dict)


class ModuleInstallRequest(BaseModel):
    force: bool = False
    ref: str | None = None


class ModuleInstallVersionRequest(BaseModel):
    ref: str | None = None
    activate: bool = False


class ModuleActivateVersionRequest(BaseModel):
    version_id: str = Field(min_length=1, max_length=240)


class ModuleRollbackVersionRequest(BaseModel):
    version_id: str | None = None


def build_modules_router(*, module_manager: Any, observability: Any, job_runtime: Any = None) -> APIRouter:
    router = APIRouter(tags=["modules"])

    def _require_enabled() -> None:
        if not module_manager.enabled:
            raise HTTPException(status_code=503, detail="Module manager feature flag OFF")

    @router.get("/api/modules")
    def list_managed_modules() -> dict:
        if not module_manager.enabled:
            return {
                "enabled": False,
                "modules": [],
                "truth": {"module_manager_feature_flag_off": True},
            }
        return module_manager.public_snapshot()

    @router.post("/api/modules/discover")
    def discover_modules() -> dict:
        _require_enabled()
        manifests = module_manager.discover()
        observability.emit("module_manager", "discover", payload={"count": len(manifests)})
        return {
            "discovered": [item.public_dict() for item in manifests],
            "snapshot": module_manager.public_snapshot(),
        }

    @router.get("/api/modules/{module_id}")
    def get_module(module_id: str) -> dict:
        _require_enabled()
        managed = module_manager.get(module_id)
        if managed is None:
            raise HTTPException(status_code=404, detail=f"Unknown module: {module_id}")
        return {"module": managed.public_dict()}

    @router.post("/api/modules/{module_id}/install")
    def install_module(module_id: str, payload: ModuleInstallRequest | None = None) -> dict:
        _require_enabled()
        payload = payload or ModuleInstallRequest()
        # Long install → JobRuntime when available.
        if job_runtime is not None:
            try:
                from Data.modules.execution import CapabilityRequest

                job = job_runtime.enqueue(
                    CapabilityRequest(
                        capability_id="external.module.install",
                        arguments={
                            "module_id": module_id,
                            "force": payload.force,
                            "ref": payload.ref,
                        },
                        requested_by="api.modules.install",
                        idempotency_key=f"ext-install:{module_id}:{payload.ref or 'active'}",
                    )
                )
                observability.emit("module_manager", "install_enqueued", payload={"module_id": module_id, "job_id": job.job_id})
                return {"job_id": job.job_id, "run_id": getattr(job, "run_id", None), "status": "QUEUED"}
            except Exception:  # noqa: BLE001 — fall back to sync install for tests/dev
                pass
        try:
            result = module_manager.ensure_installed(module_id)
        except ModuleManagerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        observability.emit("module_manager", "install", payload={"module_id": module_id})
        return {"result": result, "module": module_manager.get(module_id).public_dict()}

    @router.post("/api/modules/{module_id}/start")
    def start_module(module_id: str) -> dict:
        _require_enabled()
        try:
            result = module_manager.start(module_id)
        except ModuleManagerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        observability.emit("module_manager", "start", payload={"module_id": module_id})
        return {"result": result, "module": module_manager.get(module_id).public_dict()}

    @router.post("/api/modules/{module_id}/stop")
    def stop_module(module_id: str) -> dict:
        _require_enabled()
        try:
            result = module_manager.stop(module_id)
        except ModuleManagerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        observability.emit("module_manager", "stop", payload={"module_id": module_id})
        return {"result": result, "module": module_manager.get(module_id).public_dict()}

    @router.post("/api/modules/{module_id}/restart")
    def restart_module(module_id: str) -> dict:
        _require_enabled()
        try:
            result = module_manager.restart(module_id)
        except ModuleManagerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        observability.emit("module_manager", "restart", payload={"module_id": module_id})
        return {"result": result, "module": module_manager.get(module_id).public_dict()}

    @router.post("/api/modules/{module_id}/ensure-ready")
    def ensure_ready_module(module_id: str) -> dict:
        _require_enabled()
        try:
            result = module_manager.ensure_ready(module_id)
        except ModuleManagerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        observability.emit("module_manager", "ensure_ready", payload={"module_id": module_id})
        managed = module_manager.get(module_id)
        return {
            "result": result,
            "module": managed.public_dict() if managed is not None else None,
        }

    @router.get("/api/modules/{module_id}/health")
    def module_health(module_id: str) -> dict:
        _require_enabled()
        try:
            health = module_manager.health(module_id)
        except ModuleManagerError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"health": health.public_dict()}

    @router.get("/api/modules/{module_id}/logs")
    def module_logs(module_id: str, limit: int = Query(default=200, ge=1, le=500)) -> dict:
        _require_enabled()
        try:
            lines = module_manager.logs(module_id, limit=limit)
        except ModuleManagerError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"module_id": module_id, "lines": lines, "count": len(lines)}

    @router.get("/api/modules/{module_id}/capabilities")
    def module_capabilities(module_id: str) -> dict:
        _require_enabled()
        managed = module_manager.get(module_id)
        if managed is None:
            raise HTTPException(status_code=404, detail=f"Unknown module: {module_id}")
        caps = [c.public_dict() for c in managed.manifest.capabilities]
        return {
            "module_id": module_id,
            "capabilities": caps,
            "count": len(caps),
            "truth": {"discoverable_is_not_authorized": True},
        }

    @router.get("/api/modules/{module_id}/jobs")
    def module_jobs(module_id: str) -> dict:
        _require_enabled()
        try:
            jobs = module_manager.active_jobs(module_id)
        except ModuleManagerError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"module_id": module_id, "jobs": jobs, "count": len(jobs)}

    @router.get("/api/modules/{module_id}/versions")
    def module_versions(module_id: str) -> dict:
        _require_enabled()
        try:
            versions = module_manager.list_versions(module_id)
        except ModuleManagerError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"module_id": module_id, "versions": versions, "count": len(versions)}

    @router.get("/api/modules/{module_id}/check-update")
    def module_check_update(module_id: str) -> dict:
        _require_enabled()
        try:
            result = module_manager.check_update(module_id)
        except ModuleManagerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"result": result}

    @router.post("/api/modules/{module_id}/install-version")
    def module_install_version(module_id: str, payload: ModuleInstallVersionRequest | None = None) -> dict:
        _require_enabled()
        payload = payload or ModuleInstallVersionRequest()
        if job_runtime is not None and not payload.activate:
            try:
                from Data.modules.execution import CapabilityRequest

                job = job_runtime.enqueue(
                    CapabilityRequest(
                        capability_id="external.module.install",
                        arguments={
                            "module_id": module_id,
                            "ref": payload.ref,
                            "activate": False,
                        },
                        requested_by="api.modules.install_version",
                        idempotency_key=f"ext-install-ver:{module_id}:{payload.ref or 'active'}",
                    )
                )
                return {"job_id": job.job_id, "run_id": getattr(job, "run_id", None), "status": "QUEUED"}
            except Exception:  # noqa: BLE001
                pass
        try:
            result = module_manager.install_version(
                module_id,
                ref=payload.ref,
                activate=payload.activate,
            )
        except ModuleManagerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        observability.emit(
            "module_manager",
            "install_version",
            payload={"module_id": module_id, "ref": payload.ref, "activate": payload.activate},
        )
        return {"result": result, "module": module_manager.get(module_id).public_dict()}

    @router.post("/api/modules/{module_id}/activate-version")
    def module_activate_version(module_id: str, payload: ModuleActivateVersionRequest) -> dict:
        _require_enabled()
        try:
            result = module_manager.activate_version(module_id, payload.version_id)
        except ModuleManagerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        observability.emit(
            "module_manager",
            "activate_version",
            payload={"module_id": module_id, "version_id": payload.version_id},
        )
        return {"result": result, "module": module_manager.get(module_id).public_dict()}

    @router.post("/api/modules/{module_id}/rollback-version")
    def module_rollback_version(module_id: str, payload: ModuleRollbackVersionRequest | None = None) -> dict:
        _require_enabled()
        payload = payload or ModuleRollbackVersionRequest()
        try:
            result = module_manager.rollback_version(module_id, version_id=payload.version_id)
        except ModuleManagerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        observability.emit(
            "module_manager",
            "rollback_version",
            payload={"module_id": module_id, "version_id": payload.version_id},
        )
        return {"result": result, "module": module_manager.get(module_id).public_dict()}

    @router.post("/api/modules/sweep-idle")
    def sweep_idle_modules() -> dict:
        _require_enabled()
        stopped = []
        if hasattr(module_manager, "sweep_idle_modules"):
            stopped = module_manager.sweep_idle_modules()
        observability.emit("module_manager", "sweep_idle", payload={"stopped": len(stopped)})
        return {"stopped": stopped, "count": len(stopped)}

    @router.post("/api/modules/{module_id}/execute")
    def execute_managed_module(module_id: str, payload: ModuleExecuteRequest) -> dict:
        _require_enabled()
        try:
            result = module_manager.execute(module_id, payload.operation, payload.arguments)
        except ModuleManagerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        observability.emit(
            "module_manager",
            "execute",
            payload={"module_id": module_id, "operation": payload.operation, "status": result.status},
        )
        return {"result": result.public_dict()}

    return router
