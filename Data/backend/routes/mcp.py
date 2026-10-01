"""FastAPI routes for the universal MCP bridge (Tools / MCP operator surface)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from Data.modules.execution import CapabilityRequest, CapabilityStatus, ExecutionGateway
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


def _mcp_externalize_enabled() -> bool:
    import os

    raw = (os.environ.get("LEVIATHAN_WORKERS_EXTERNALIZE_API") or "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _queue_mcp_live_op(
    *,
    job_runtime: Any | None,
    capability_id: str,
    server_id: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Enqueue live MCP connect/list onto mcp_execution — never spawn in FastAPI."""
    if job_runtime is None or not hasattr(job_runtime, "enqueue"):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "MCP_EXECUTION_UNAVAILABLE",
                "message": "JobRuntime unavailable for live MCP operations",
                "server_id": server_id,
                "capability_id": capability_id,
            },
        )
    try:
        job = job_runtime.enqueue(
            capability_id=capability_id,
            arguments={"server_id": server_id, **dict(arguments or {})},
            requested_by=f"api.mcp.{capability_id}",
            worker_pool="mcp_execution",
            resource_class="NETWORK_BOUND",
            latency_class="interactive",
            domain="mcp",
            consumer="api.mcp",
            metadata={"worker_kind": "mcp_execution", "execution_class": "EXTERNAL_REQUIRED"},
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={
                "code": "MCP_EXECUTION_UNAVAILABLE",
                "message": str(exc)[:300],
                "server_id": server_id,
                "capability_id": capability_id,
            },
        ) from exc
    return {
        "queued": True,
        "job_id": getattr(job, "job_id", None),
        "capability_id": capability_id,
        "worker_pool": "mcp_execution",
        "server_id": server_id,
        "truth": {
            "fastapi_does_not_spawn_mcp_stdio": True,
            "fastapi_does_not_perform_live_mcp_handshake": True,
            "control_plane_does_not_poll_mcp_jobs": True,
        },
    }


def _accepted(payload: dict[str, Any]) -> JSONResponse:
    """HTTP 202 Accepted — durable job queued; poll /api/jobs/{job_id}."""
    return JSONResponse(status_code=202, content=payload)


def build_mcp_router(
    bridge: McpBridge,
    gateway: ExecutionGateway,
    *,
    job_runtime: Any | None = None,
) -> APIRouter:
    router = APIRouter(tags=["mcp"])
    # Prefer explicit job_runtime; fall back to gateway-bound MCP provider.
    jobs = job_runtime
    if jobs is None:
        mcp_exec = getattr(gateway, "mcp_executor", None)
        jobs = getattr(mcp_exec, "job_runtime", None)

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
    def delete_server(server_id: str, force: bool = Query(False)) -> dict:
        try:
            bridge.unregister_server(server_id, force=force)
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
    def connect_server(server_id: str):
        try:
            bridge.require_server(server_id)
        except McpError as exc:
            raise_mcp_error(exc)
        if _mcp_externalize_enabled():
            return _accepted(
                _queue_mcp_live_op(
                    job_runtime=jobs,
                    capability_id="mcp.connect",
                    server_id=server_id,
                    arguments={"expand_tools": True},
                )
            )
        # Test / developer mode only — production externalize defaults on.
        try:
            connected = bridge.connect(server_id)
        except McpError as exc:
            raise_mcp_error(exc)
        return {
            "server": bridge.get_server_public(server_id),
            "runtime": connected.public_dict(),
            "truth": {"inprocess_test_only": True},
        }

    @router.post("/api/mcp/servers/{server_id}/disconnect")
    def disconnect_server(server_id: str) -> dict:
        try:
            disconnected = bridge.disconnect(server_id)
        except McpError as exc:
            raise_mcp_error(exc)
        return {"server": bridge.get_server_public(server_id), "runtime": disconnected.public_dict()}

    @router.post("/api/mcp/servers/{server_id}/refresh-tools")
    def refresh_tools(server_id: str):
        try:
            bridge.require_server(server_id)
        except McpError as exc:
            raise_mcp_error(exc)
        if _mcp_externalize_enabled():
            return _accepted(
                _queue_mcp_live_op(
                    job_runtime=jobs,
                    capability_id="mcp.list_tools",
                    server_id=server_id,
                    arguments={"force_refresh": True, "expand_tools": True},
                )
            )
        try:
            tools = bridge.refresh_tools(server_id)
        except McpError as exc:
            raise_mcp_error(exc)
        return {"tools": [item.public_dict() for item in tools], "truth": {"inprocess_test_only": True}}

    @router.get("/api/mcp/servers/{server_id}/tools")
    def server_tools(server_id: str) -> dict:
        try:
            bridge.require_server(server_id)
        except McpError as exc:
            raise_mcp_error(exc)
        tools = bridge.list_tools(server_id=server_id)
        return {
            "tools": [item.public_dict() for item in tools],
            "catalog_generation": bridge.store.get_catalog_generation(server_id),
            "sync_issues": bridge.store.list_sync_issues(server_id),
        }

    @router.get("/api/mcp/servers/{server_id}/sync-issues")
    def server_sync_issues(server_id: str) -> dict:
        try:
            bridge.require_server(server_id)
        except McpError as exc:
            raise_mcp_error(exc)
        return {
            "server_id": server_id,
            "sync_issues": bridge.store.list_sync_issues(server_id),
            "catalog_generation": bridge.store.get_catalog_generation(server_id),
        }

    @router.get("/api/mcp/servers/{server_id}/health")
    def server_health(server_id: str) -> dict:
        try:
            health = bridge.server_health(server_id)
        except McpError as exc:
            raise_mcp_error(exc)
        return {"health": health.public_dict()}

    @router.get("/api/mcp/tools")
    def list_tools(server_id: str | None = None) -> dict:
        tools = bridge.list_tools(server_id=server_id)
        payload: dict[str, Any] = {"tools": [item.public_dict() for item in tools]}
        if server_id:
            payload["catalog_generation"] = bridge.store.get_catalog_generation(server_id)
            payload["sync_issues"] = bridge.store.list_sync_issues(server_id)
        return payload

    @router.post("/api/mcp/reconcile-catalog")
    def reconcile_catalog(server_id: str | None = None) -> dict:
        """Rehydrate CapabilityCatalog from durable McpStore (post-worker sync)."""
        try:
            if server_id:
                bridge.require_server(server_id)
            result = bridge.reconcile_catalog_from_store(server_id)
        except McpError as exc:
            raise_mcp_error(exc)
        return {"reconcile": result}

    @router.get("/api/mcp/calls")
    def list_calls(
        limit: int = Query(100, ge=1, le=500),
        server_id: str | None = None,
    ) -> dict:
        calls = bridge.list_calls(limit=limit, server_id=server_id)
        return {"calls": [item.public_dict() for item in calls]}

    @router.post("/api/mcp/call")
    def call_tool(payload: McpCallRequest):
        """Manual operator invoke — MUST go through ExecutionGateway.

        Externalized path: gateway enqueues mcp.call and returns QUEUED → HTTP 202.
        Never blocks the FastAPI thread polling worker completion.
        """
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
        body = {
            "result": result.public_dict(),
            "truth": {
                "manual_mcp_call_uses_execution_gateway": True,
                "approved_by_user_is_not_authority": True,
                "mcp_output_is_not_evidence": True,
                "control_plane_does_not_poll_mcp_jobs": True,
            },
        }
        if result.status == CapabilityStatus.QUEUED or bool((result.output or {}).get("queued")):
            job_id = (result.output or {}).get("job_id") or (result.telemetry or {}).get("job_id")
            body["queued"] = True
            body["job_id"] = job_id
            return _accepted(body)
        if result.status == CapabilityStatus.APPROVAL_REQUIRED:
            raise HTTPException(status_code=403, detail=body)
        if result.status == CapabilityStatus.REJECTED:
            reason = (result.telemetry or {}).get("reason")
            code = 403 if reason in {"approval_required", "approval_denied"} else 422
            raise HTTPException(status_code=code, detail=body)
        if result.status == CapabilityStatus.TIMEOUT:
            raise HTTPException(status_code=504, detail=body)
        if result.status == CapabilityStatus.CANCELLED:
            raise HTTPException(status_code=409, detail=body)
        if result.status == CapabilityStatus.FAILED:
            raise HTTPException(status_code=500, detail=body)
        return body

    return router
