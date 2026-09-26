"""Plugin registry HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from Data.modules.execution import CapabilityRequest, CapabilityStatus
from Data.modules.plugins import PluginStatus


class PluginInvokeRequest(BaseModel):
    external_name: str = Field(min_length=1, max_length=120)
    arguments: dict = Field(default_factory=dict)
    approval_id: str | None = None


def build_plugins_router(
    *,
    plugin_registry: Any,
    execution_gateway: Any,
    observability: Any,
) -> APIRouter:
    router = APIRouter(tags=["plugins"])

    @router.get("/api/plugins")
    def list_plugins() -> dict:
        return {"plugins": [item.public_dict() for item in plugin_registry.list()]}

    @router.get("/api/plugins/{plugin_id}")
    def get_plugin(plugin_id: str) -> dict:
        item = plugin_registry.get(plugin_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Plugin not found")
        return {"plugin": item.public_dict()}

    @router.post("/api/plugins/{plugin_id}/disable")
    def disable_plugin(plugin_id: str) -> dict:
        try:
            item = plugin_registry.set_status(plugin_id, PluginStatus.DISABLED)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Plugin not found") from exc
        return {"plugin": item.public_dict()}

    @router.post("/api/plugins/{plugin_id}/enable")
    def enable_plugin(plugin_id: str) -> dict:
        try:
            item = plugin_registry.set_status(plugin_id, PluginStatus.ENABLED)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Plugin not found") from exc
        return {"plugin": item.public_dict()}

    @router.post("/api/plugins/{plugin_id}/invoke")
    def invoke_plugin(plugin_id: str, payload: PluginInvokeRequest) -> dict:
        capability_id = plugin_registry.resolve_capability(plugin_id, payload.external_name)
        if capability_id is None:
            raise HTTPException(
                status_code=404,
                detail="Plugin binding not found or plugin not ENABLED",
            )
        result = execution_gateway.execute(
            CapabilityRequest(
                capability_id=capability_id,
                arguments=payload.arguments,
                approval_id=payload.approval_id,
                requested_by=f"plugin:{plugin_id}",
            )
        )
        observability.emit(
            "plugin",
            "invoke",
            payload={"plugin_id": plugin_id, "capability_id": capability_id, "status": result.status.value},
        )
        status_code = 200
        if result.status == CapabilityStatus.REJECTED:
            reason = (result.telemetry or {}).get("reason")
            status_code = 403 if reason in {"approval_required", "approval_denied"} else 422
        elif result.status == CapabilityStatus.FAILED:
            status_code = 500
        if status_code != 200:
            raise HTTPException(status_code=status_code, detail=result.public_dict())
        return {
            "capability_id": capability_id,
            "result": result.public_dict(),
            "truth": {"discoverable_capability_is_not_authorized_capability": True},
        }

    return router
