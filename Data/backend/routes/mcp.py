"""FastAPI routes for the universal MCP bridge (Tools / MCP operator surface)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from Data.modules.execution import CapabilityRequest, ExecutionGateway
from Data.modules.mcp import McpBridge, McpError


def raise_mcp_error(exc: McpError) -> None:
    raise HTTPException(status_code=exc.http_status, detail=exc.public_dict()) from exc


class ServerCreate(BaseModel):
    display_name: str
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    secret_refs: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = 30.0
    enabled: bool = False
    trust: str = "untrusted"
    requested_isolation: str = "subprocess"
    max_concurrent_calls: int = 4
    eager_connect: bool = False
    expand_tools: bool = True
    semantic_effects: dict[str, list[str]] = Field(default_factory=dict)
    source_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ServerUpdate(BaseModel):
    display_name: str | None = None
    transport: str | None = None
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    cwd: str | None = None
    env: dict[str, str] | None = None
    secret_refs: dict[str, str] | None = None
    timeout_seconds: float | None = None
    trust: str | None = None
    requested_isolation: str | None = None
    max_concurrent_calls: int | None = None
    eager_connect: bool | None = None
    expand_tools: bool | None = None
    semantic_effects: dict[str, list[str]] | None = None
    metadata: dict[str, Any] | None = None
    enabled: bool | None = None


class McpCallRequest(BaseModel):
    capability_id: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    approval_id: str | None = None
    requested_by: str = "api"
    # Audit metadata only — never authorization authority.
    approved_by_user: bool | None = None
    run_id: str | None = None


def build_mcp_router(bridge: McpBridge, gateway: ExecutionGateway) -> APIRouter:
    router = APIRouter(tags=["mcp"])

    @router.get("/api/mcp/health")
    def mcp_health() -> dict:
        return {"mcp": bridge.health_summary().public_dict(), "telemetry": dict(bridge.telemetry)}

    @router.get("/api/mcp/servers")
    def list_servers() -> dict:
        if not bridge.enabled:
            return {"servers": [], "feature_enabled": False}
        return {"servers": bridge.list_servers(), "feature_enabled": True}

    @router.post("/api/mcp/servers")
    def create_server(payload: ServerCreate) -> dict:
        try:
            config = bridge.register_server(
                display_name=payload.display_name,
                transport=payload.transport,
                command=payload.command,
                args=payload.args,
                url=payload.url,
                cwd=payload.cwd,
                env=payload.env,
                secret_refs=payload.secret_refs,
                timeout_seconds=payload.timeout_seconds,
                enabled=payload.enabled,
                trust=payload.trust,
                requested_isolation=payload.requested_isolation,
                max_concurrent_calls=payload.max_concurrent_calls,
                eager_connect=payload.eager_connect,
                expand_tools=payload.expand_tools,
                semantic_effects=payload.semantic_effects,
                source_key=payload.source_key,
                metadata=payload.metadata,
            )
        except McpError as exc:
            raise_mcp_error(exc)
        return {"server": bridge.get_server_public(config.server_id)}

    @router.get("/api/mcp/servers/{server_id}")
    def get_server(server_id: str) -> dict:
        try:
            return {"server": bridge.get_server_public(server_id)}
        except McpError as exc:
            raise_mcp_error(exc)

    @router.put("/api/mcp/servers/{server_id}")
    def update_server(server_id: str, payload: ServerUpdate) -> dict:
        try:
            bridge.update_server(server_id, **payload.model_dump(exclude_unset=True))
            return {"server": bridge.get_server_public(server_id)}
        except McpError as exc:
            raise_mcp_error(exc)

    @router.delete("/api/mcp/servers/{server_id}")
    def delete_server(server_id: str) -> dict:
        try:
            bridge.unregister_server(server_id)
        except McpError as exc:
            raise_mcp_error(exc)
        return {"ok": True, "server_id": server_id}

    @router.post("/api/mcp/servers/{server_id}/enable")
    def enable_server(server_id: str) -> dict:
        try:
            bridge.enable(server_id)
            return {"server": bridge.get_server_public(server_id)}
        except McpError as exc:
            raise_mcp_error(exc)

    @router.post("/api/mcp/servers/{server_id}/disable")
    def disable_server(server_id: str) -> dict:
        try:
            bridge.disable(server_id)
            return {"server": bridge.get_server_public(server_id)}
        except McpError as exc:
            raise_mcp_error(exc)

    @router.post("/api/mcp/servers/{server_id}/connect")
    def connect_server(server_id: str) -> dict:
        try:
            runtime = bridge.connect(server_id)
        except McpError as exc:
            raise_mcp_error(exc)
        return {"server": bridge.get_server_public(server_id), "runtime": runtime.public_dict()}

    @router.post("/api/mcp/servers/{server_id}/disconnect")
    def disconnect_server(server_id: str) -> dict:
        try:
            runtime = bridge.disconnect(server_id)
        except McpError as exc:
            raise_mcp_error(exc)
        return {"server": bridge.get_server_public(server_id), "runtime": runtime.public_dict()}

    @router.post("/api/mcp/servers/{server_id}/refresh-tools")
    def refresh_tools(server_id: str) -> dict:
        try:
            tools = bridge.refresh_tools(server_id)
        except McpError as exc:
            raise_mcp_error(exc)
        return {"tools": [item.public_dict() for item in tools]}

    @router.get("/api/mcp/servers/{server_id}/tools")
    def server_tools(server_id: str) -> dict:
        try:
            bridge.require_server(server_id)
        except McpError as exc:
            raise_mcp_error(exc)
        tools = bridge.list_tools(server_id=server_id)
        return {"tools": [item.public_dict() for item in tools]}

    @router.get("/api/mcp/servers/{server_id}/health")
    def server_health(server_id: str) -> dict:
        try:
            runtime = bridge.server_health(server_id)
        except McpError as exc:
            raise_mcp_error(exc)
        return {"health": runtime.public_dict()}

    @router.get("/api/mcp/tools")
    def list_tools(server_id: str | None = None) -> dict:
        tools = bridge.list_tools(server_id=server_id)
        return {"tools": [item.public_dict() for item in tools]}

    @router.get("/api/mcp/calls")
    def list_calls(
        limit: int = Query(100, ge=1, le=500),
        server_id: str | None = None,
    ) -> dict:
        calls = bridge.list_calls(limit=limit, server_id=server_id)
        return {"calls": [item.public_dict() for item in calls]}

    @router.post("/api/mcp/call")
    def call_tool(payload: McpCallRequest) -> dict:
        """Manual operator invoke — MUST go through ExecutionGateway."""
        # approved_by_user is intentionally ignored for authorization.
        result = gateway.execute(
            CapabilityRequest(
                capability_id=payload.capability_id,
                arguments=dict(payload.arguments),
                approval_id=payload.approval_id,
                requested_by=payload.requested_by,
                run_id=payload.run_id,
            )
        )
        return {
            "result": result.public_dict(),
            "truth": {
                "manual_mcp_call_uses_execution_gateway": True,
                "approved_by_user_is_not_authority": True,
                "mcp_output_is_not_evidence": True,
            },
        }

    return router
