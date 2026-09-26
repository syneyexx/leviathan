"""Module manager HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from Data.modules.module_manager import ModuleManagerError


class ModuleExecuteRequest(BaseModel):
    operation: str = Field(min_length=1, max_length=120)
    arguments: dict = Field(default_factory=dict)


def build_modules_router(*, module_manager: Any, observability: Any) -> APIRouter:
    router = APIRouter(tags=["modules"])

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
        if not module_manager.enabled:
            raise HTTPException(status_code=503, detail="Module manager feature flag OFF")
        manifests = module_manager.discover()
        observability.emit("module_manager", "discover", payload={"count": len(manifests)})
        return {
            "discovered": [item.public_dict() for item in manifests],
            "snapshot": module_manager.public_snapshot(),
        }

    @router.post("/api/modules/{module_id}/execute")
    def execute_managed_module(module_id: str, payload: ModuleExecuteRequest) -> dict:
        if not module_manager.enabled:
            raise HTTPException(status_code=503, detail="Module manager feature flag OFF")
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
