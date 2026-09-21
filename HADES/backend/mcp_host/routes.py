"""FastAPI routes for MCP management."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from mcp_host.manager import get_mcp_manager
from mcp_host.oauth import sanitize_ui_return_url
from mcp_host.secrets import SecretStorageUnavailable as SecretErr


class ServerCreate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    description: str = Field(default="", max_length=4000)
    transport: str | None = None
    transport_choice: str | None = None
    catalog_id: str | None = Field(default=None, max_length=120)
    enabled: bool = True
    auto_connect: bool = False
    command: dict[str, Any] | None = None
    env: dict[str, Any] | None = None
    endpoint_url: str | None = Field(default=None, max_length=2000)
    auth_method: str = "none"
    headers: dict[str, str] | None = None
    bearer_token: str | None = Field(default=None, max_length=16_000)
    auth_token: str | None = Field(default=None, max_length=16_000)
    timeout_seconds: float = Field(default=60, gt=0, le=600)
    metadata: dict[str, Any] | None = None


class ServerUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    transport: str | None = None
    transport_choice: str | None = None
    enabled: bool | None = None
    auto_connect: bool | None = None
    command: dict[str, Any] | None = None
    env: dict[str, Any] | None = None
    endpoint_url: str | None = Field(default=None, max_length=2000)
    auth_method: str | None = None
    headers: dict[str, str] | None = None
    bearer_token: str | None = Field(default=None, max_length=16_000)
    auth_token: str | None = Field(default=None, max_length=16_000)
    timeout_seconds: float | None = Field(default=None, gt=0, le=600)
    metadata: dict[str, Any] | None = None


class ToolPrefsUpdate(BaseModel):
    allowed: bool | None = None
    chatbot_enabled: bool | None = None
    require_approval: bool | None = None


class ToolInvokeInput(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)
    # Informational/audit only — not authorization authority. Prefer approval_id.
    approved_by_user: bool = False
    approval_id: str | None = Field(default=None, max_length=120)
    idempotency_key: str | None = Field(default=None, max_length=200)
    # Per-kind capability approvals (F-03). Required when global policy is ask.
    approved_network: bool = False
    approved_file_read: bool = False
    approved_file_write: bool = False
    approved_subprocess: bool = False


class OAuthStartInput(BaseModel):
    redirect_uri: str | None = Field(default=None, max_length=2000)
    ui_return_url: str | None = Field(default=None, max_length=2000)
    approval_id: str | None = Field(default=None, max_length=120)


class OAuthCompleteInput(BaseModel):
    state: str = Field(min_length=8, max_length=200)
    code: str = Field(min_length=1, max_length=4000)
    iss: str | None = Field(default=None, max_length=2000)


class ConnectInput(BaseModel):
    approval_id: str | None = Field(default=None, max_length=120)


class ImportInput(BaseModel):
    servers: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    connect: bool = False


def _default_oauth_redirect(request: Any) -> str:
    # Absolute callback on the API origin — never includes a fragment.
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/mcp/oauth/callback"


def _oauth_ui_target(ui: str, *, ok: bool) -> str:
    """Append only a fixed status marker; never provider/backend error text."""
    status_value = "done" if ok else "error"
    if "#" in ui:
        base, frag = ui.split("#", 1)
        path = frag.split("?")[0]
        return f"{base}#{path}?oauth={status_value}"
    sep = "&" if "?" in ui else "?"
    return f"{ui}{sep}oauth={status_value}"


def mount_mcp_routes() -> APIRouter:
    router = APIRouter(tags=["mcp"])

    def manager():
        mgr = get_mcp_manager()
        if mgr is None:
            raise HTTPException(status_code=503, detail="MCP manager not initialized")
        return mgr

    def _policy_http(exc: Exception) -> None:
        from mcp_host.policy import McpPolicyError

        if isinstance(exc, McpPolicyError) and exc.approval_required:
            raise HTTPException(
                status_code=428,
                detail={
                    "message": str(exc),
                    "approval_required": True,
                    "approval": exc.approval,
                    "effect": exc.effect,
                },
            ) from exc
        if isinstance(exc, PermissionError):
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        if isinstance(exc, SecretErr):
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/mcp/host/catalog")
    async def mcp_host_catalog() -> dict[str, Any]:
        return await asyncio.to_thread(manager().catalog)

    @router.get("/mcp/servers")
    async def list_servers() -> dict[str, Any]:
        items = await asyncio.to_thread(manager().list_servers)
        return {"items": items, "count": len(items)}

    @router.post("/mcp/servers")
    async def create_server(values: ServerCreate) -> dict[str, Any]:
        try:
            server = await asyncio.to_thread(manager().create_server, values.model_dump(exclude_none=True))
        except SecretErr as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"server": server}

    @router.get("/mcp/servers/{server_id}")
    async def get_server(server_id: str) -> dict[str, Any]:
        server = await asyncio.to_thread(manager().get_server, server_id)
        if not server:
            raise HTTPException(status_code=404, detail="MCP-server niet gevonden")
        return {"server": server}

    @router.patch("/mcp/servers/{server_id}")
    async def update_server(server_id: str, values: ServerUpdate) -> dict[str, Any]:
        try:
            server = await asyncio.to_thread(
                manager().update_server,
                server_id,
                values.model_dump(exclude_none=True),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MCP-server niet gevonden") from exc
        except SecretErr as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"server": server}

    @router.delete("/mcp/servers/{server_id}")
    async def delete_server(server_id: str) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(manager().delete_server, server_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MCP-server niet gevonden") from exc
        except SecretErr as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @router.post("/mcp/servers/{server_id}/duplicate")
    async def duplicate_server(server_id: str) -> dict[str, Any]:
        try:
            server = await asyncio.to_thread(manager().duplicate_server, server_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MCP-server niet gevonden") from exc
        except SecretErr as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"server": server}

    @router.post("/mcp/servers/{server_id}/enable")
    async def enable_server(server_id: str, enabled: bool = True) -> dict[str, Any]:
        try:
            server = await asyncio.to_thread(manager().set_enabled, server_id, enabled)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MCP-server niet gevonden") from exc
        return {"server": server}

    @router.post("/mcp/servers/{server_id}/connect")
    async def connect_server(server_id: str, values: ConnectInput | None = None) -> dict[str, Any]:
        approval_id = values.approval_id if values else None
        try:
            return await asyncio.to_thread(manager().connect, server_id, approval_id=approval_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MCP-server niet gevonden") from exc
        except Exception as exc:
            _policy_http(exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/mcp/servers/{server_id}/disconnect")
    async def disconnect_server(server_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(manager().disconnect, server_id)

    @router.post("/mcp/servers/{server_id}/reconnect")
    async def reconnect_server(server_id: str, values: ConnectInput | None = None) -> dict[str, Any]:
        approval_id = values.approval_id if values else None
        try:
            # reconnect uses connect under the hood; pass approval through connect path.
            mgr = manager()

            def _reconnect():
                mgr.disconnect(server_id)
                return mgr.connect(server_id, approval_id=approval_id)

            return await asyncio.to_thread(_reconnect)
        except Exception as exc:
            _policy_http(exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/mcp/servers/{server_id}/refresh-tools")
    async def refresh_tools(server_id: str) -> dict[str, Any]:
        try:
            discovery = await asyncio.to_thread(manager().refresh_tools, server_id)
        except SecretErr as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        tools = await asyncio.to_thread(manager().list_tools, server_id=server_id)
        return {"discovery": discovery, "tools": tools}

    @router.get("/mcp/tools")
    async def list_tools(
        server_id: str | None = None,
        q: str = "",
        allowed: bool | None = None,
        chatbot_enabled: bool | None = None,
    ) -> dict[str, Any]:
        filters = {}
        if allowed is not None:
            filters["allowed"] = allowed
        if chatbot_enabled is not None:
            filters["chatbot_enabled"] = chatbot_enabled
        if server_id:
            filters["server_id"] = server_id
        items = await asyncio.to_thread(manager().list_tools, server_id=server_id, q=q, filters=filters)
        return {"items": items, "count": len(items)}

    @router.patch("/mcp/tools/{tool_id:path}")
    async def update_tool(tool_id: str, values: ToolPrefsUpdate) -> dict[str, Any]:
        try:
            tool = await asyncio.to_thread(manager().update_tool_prefs, tool_id, values.model_dump(exclude_none=True))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Tool niet gevonden") from exc
        return {"tool": tool}

    @router.post("/mcp/tools/{tool_id:path}/invoke")
    async def invoke_tool(tool_id: str, values: ToolInvokeInput) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(
                manager().invoke_tool,
                tool_id,
                values.arguments,
                invocation_type="manual",
                # approved_by_user retained for audit/compat; authorization uses approval_id
                # and/or per-kind capability flags (F-03).
                approved_by_user=bool(values.approved_by_user),
                approval_id=values.approval_id,
                idempotency_key=values.idempotency_key,
                approved_network=bool(values.approved_network),
                approved_file_read=bool(values.approved_file_read),
                approved_file_write=bool(values.approved_file_write),
                approved_subprocess=bool(values.approved_subprocess),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Tool niet gevonden") from exc
        except SecretErr as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            _policy_http(exc)
            if isinstance(exc, PermissionError):
                raise HTTPException(status_code=403, detail=str(exc)) from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/mcp/executions/{execution_id}/cancel")
    async def cancel_execution(execution_id: str) -> dict[str, Any]:
        try:
            execution = await asyncio.to_thread(manager().cancel_execution, execution_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Uitvoering niet gevonden") from exc
        return {"execution": execution}

    @router.get("/mcp/executions")
    async def list_executions(server_id: str | None = None, limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
        items = await asyncio.to_thread(manager().store.list_executions, server_id=server_id, limit=limit)
        return {"items": items, "count": len(items)}

    @router.get("/mcp/servers/{server_id}/auth")
    async def auth_status(server_id: str, discover: bool = False) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(manager().auth_status, server_id, discover=discover)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MCP-server niet gevonden") from exc
        except SecretErr as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post("/mcp/servers/{server_id}/auth/discover")
    async def auth_discover(server_id: str, approval_id: str | None = None) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(manager().auth_status, server_id, discover=True, approval_id=approval_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MCP-server niet gevonden") from exc
        except Exception as exc:
            _policy_http(exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/mcp/servers/{server_id}/oauth/start")
    async def oauth_start(server_id: str, request: Request, values: OAuthStartInput) -> dict[str, Any]:
        redirect_uri = (values.redirect_uri or "").strip() or _default_oauth_redirect(request)
        try:
            return await asyncio.to_thread(
                manager().start_oauth,
                server_id,
                redirect_uri=redirect_uri,
                ui_return_url=values.ui_return_url,
                approval_id=values.approval_id,
            )
        except Exception as exc:
            _policy_http(exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/mcp/oauth/callback")
    async def oauth_callback(
        request: Request,
        code: str | None = None,
        state: str | None = None,
        iss: str | None = None,
        error: str | None = None,
        error_description: str | None = None,
    ) -> Any:
        """Standards-compliant Authorization Code callback (no fragment)."""
        _ = request, error_description  # provider diagnostics must never be reflected into redirects
        default_ui = "http://127.0.0.1:3000/#/mcp"
        if error or not code or not state:
            return RedirectResponse(url=_oauth_ui_target(default_ui, ok=False), status_code=303)
        try:
            result = await asyncio.to_thread(manager().complete_oauth, state=state, code=code, iss=iss)
        except Exception:
            # OAuth callback URLs are browser-visible; never serialize backend/provider
            # diagnostics, tokens, codes or secret-store failures into Location/history.
            return RedirectResponse(url=_oauth_ui_target(default_ui, ok=False), status_code=303)
        ui = sanitize_ui_return_url((result or {}).get("ui_return_url"), default=default_ui)
        return RedirectResponse(url=_oauth_ui_target(ui, ok=bool(result.get("ok"))), status_code=303)

    @router.post("/mcp/oauth/complete")
    async def oauth_complete(values: OAuthCompleteInput) -> dict[str, Any]:
        # Retained for non-browser clients; browser flow uses GET /oauth/callback.
        try:
            return await asyncio.to_thread(manager().complete_oauth, state=values.state, code=values.code, iss=values.iss)
        except SecretErr as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post("/mcp/oauth/cancel")
    async def oauth_cancel(state: str) -> dict[str, Any]:
        return await asyncio.to_thread(manager().cancel_oauth, state)

    @router.get("/mcp/export")
    async def export_config() -> dict[str, Any]:
        return await asyncio.to_thread(manager().export_config)

    @router.post("/mcp/import")
    async def import_config(values: ImportInput) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(manager().import_config, values.model_dump(), connect=values.connect)
        except SecretErr as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
