"""McpBridge — ONE universal owner of many independent MCP server sessions."""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any

from Data.modules.execution.catalog import CapabilityCatalog
from Data.modules.plugins.registry import PluginRegistry

from .catalog_sync import McpCatalogSync
from .errors import (
    MCP_FEATURE_DISABLED,
    MCP_SERVER_CONFLICT,
    MCP_SERVER_DISABLED,
    MCP_SERVER_NOT_FOUND,
    MCP_TOOL_NOT_FOUND,
    McpError,
)
from .limits import DEFAULT_MCP_LIMITS, McpLimits
from .policy import sanitize_text_for_log
from .session import McpServerSession
from .store import McpStore, utc_now
from .types import (
    McpCallResult,
    McpCallStatus,
    McpHealthSummary,
    McpIsolationKind,
    McpServerConfig,
    McpServerRuntime,
    McpServerState,
    McpSourceKind,
    McpToolCallRecord,
    McpToolRecord,
    McpTransportKind,
    McpTrust,
    make_server_id,
)


class McpBridge:
    """Control-plane facade: register/enable/connect/list/call/health.

    Does NOT authorize side effects — ExecutionGateway remains authority.
    """

    def __init__(
        self,
        *,
        store: McpStore,
        catalog: CapabilityCatalog,
        plugin_registry: PluginRegistry | None = None,
        enabled: bool = False,
        stdio_enabled: bool = True,
        http_enabled: bool = True,
        auto_expand_modules: bool = True,
        allow_outbound: bool = False,
        limits: McpLimits | None = None,
        secret_overrides: dict[str, str] | None = None,
    ) -> None:
        self.store = store
        self.catalog = catalog
        self.plugin_registry = plugin_registry
        self.enabled = enabled
        self.stdio_enabled = stdio_enabled and enabled
        self.http_enabled = http_enabled and enabled
        self.auto_expand_modules = auto_expand_modules and enabled
        self.allow_outbound = allow_outbound
        self.limits = limits or DEFAULT_MCP_LIMITS
        self.secret_overrides = secret_overrides or {}
        self.sync = McpCatalogSync(
            catalog=catalog,
            store=store,
            plugin_registry=plugin_registry,
            limits=self.limits,
        )
        self._sessions: dict[str, McpServerSession] = {}
        self._lock = threading.RLock()
        self.telemetry: dict[str, Any] = {
            "registers": 0,
            "connects": 0,
            "disconnects": 0,
            "tool_calls": 0,
            "tool_call_failures": 0,
            "schema_changes": 0,
        }

    def initialize(self) -> None:
        self.store.initialize()
        # Startup reconciliation: persisted READY is not runtime truth.
        for config in self.store.list_servers():
            state = McpServerState.DISABLED if not config.enabled else McpServerState.DISCONNECTED
            self.store.update_runtime_state(config.server_id, state=state)
            self.sync.mark_unavailable(config)
            if self.enabled and config.enabled and config.eager_connect:
                try:
                    self.connect(config.server_id)
                except McpError:
                    pass

    def shutdown(self) -> None:
        with self._lock:
            ids = list(self._sessions.keys())
        for server_id in ids:
            try:
                self.disconnect(server_id)
            except McpError:
                pass

    # --- registration ---

    def register_server(
        self,
        *,
        display_name: str,
        transport: str | McpTransportKind,
        source_kind: str | McpSourceKind = McpSourceKind.MANUAL,
        source_key: str | None = None,
        server_id: str | None = None,
        command: str | None = None,
        args: list[str] | tuple[str, ...] | None = None,
        url: str | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        secret_refs: dict[str, str] | None = None,
        timeout_seconds: float = 30.0,
        enabled: bool = False,
        trust: str | McpTrust = McpTrust.UNTRUSTED,
        requested_isolation: str | McpIsolationKind = McpIsolationKind.SUBPROCESS,
        max_concurrent_calls: int = 4,
        owner_module_id: str | None = None,
        eager_connect: bool = False,
        expand_tools: bool = True,
        semantic_effects: dict[str, list[str] | tuple[str, ...]] | None = None,
        metadata: dict[str, Any] | None = None,
        allow_overwrite_same_source: bool = True,
    ) -> McpServerConfig:
        self._require_feature()
        sk = McpSourceKind(source_kind) if isinstance(source_kind, str) else source_kind
        key = source_key or (str(uuid.uuid4()) if sk == McpSourceKind.MANUAL else display_name)
        sid = server_id or make_server_id(source_kind=sk, source_key=key)
        existing = self.store.get_server(sid)
        if existing is not None and not (
            allow_overwrite_same_source
            and existing.source_kind == sk
            and existing.source_key == key
        ):
            if existing.source_kind != sk or existing.source_key != key:
                raise McpError(
                    MCP_SERVER_CONFLICT,
                    f"Server id conflict: {sid}",
                    details={
                        "existing_source": f"{existing.source_kind.value}:{existing.source_key}",
                        "requested_source": f"{sk.value}:{key}",
                    },
                )
        transport_kind = McpTransportKind(transport) if isinstance(transport, str) else transport
        if transport_kind == McpTransportKind.STDIO and not self.stdio_enabled:
            raise McpError("MCP_TRANSPORT_UNSUPPORTED", "stdio MCP transport feature disabled")
        if transport_kind == McpTransportKind.HTTP and not self.http_enabled:
            raise McpError("MCP_TRANSPORT_UNSUPPORTED", "http MCP transport feature disabled")
        if transport_kind == McpTransportKind.SSE:
            raise McpError("MCP_TRANSPORT_UNSUPPORTED", "Legacy SSE MCP transport is not implemented")

        effects: dict[str, tuple[str, ...]] = {}
        for tool_name, values in (semantic_effects or {}).items():
            effects[str(tool_name)] = tuple(str(v) for v in values)

        config = McpServerConfig(
            server_id=sid,
            display_name=display_name,
            source_kind=sk,
            source_key=key,
            transport=transport_kind,
            command=command,
            args=tuple(args or ()),
            url=url,
            cwd=cwd,
            env_public=dict(env or {}),
            secret_refs=dict(secret_refs or {}),
            timeout_seconds=timeout_seconds,
            enabled=enabled,
            trust=McpTrust(trust) if isinstance(trust, str) else trust,
            requested_isolation=(
                McpIsolationKind(requested_isolation)
                if isinstance(requested_isolation, str)
                else requested_isolation
            ),
            max_concurrent_calls=max_concurrent_calls,
            owner_module_id=owner_module_id,
            eager_connect=eager_connect,
            expand_tools=expand_tools,
            semantic_effects=effects,
            metadata=dict(metadata or {}),
        )
        self.store.upsert_server(config)
        self.telemetry["registers"] += 1
        return config

    def unregister_server(self, server_id: str, *, force: bool = False) -> None:
        config = self.store.get_server(server_id)
        if config is None:
            raise McpError(MCP_SERVER_NOT_FOUND, f"Unknown MCP server: {server_id}", http_status=404)
        if not force and config.source_kind == McpSourceKind.CONFIG:
            # Config-owned servers require explicit force.
            pass
        try:
            self.disconnect(server_id)
        except McpError:
            pass
        if self.plugin_registry is not None:
            self.plugin_registry.unregister(f"mcp:{server_id}")
        self.store.delete_tools_for_server(server_id)
        self.store.delete_server(server_id)

    def update_server(self, server_id: str, **patch: Any) -> McpServerConfig:
        config = self.require_server(server_id)
        data = config.public_dict()
        # Never accept plaintext secrets via patch.
        patch.pop("env_secrets", None)
        patch.pop("secrets", None)
        mapping = {
            "display_name": "display_name",
            "command": "command",
            "args": "args",
            "url": "url",
            "cwd": "cwd",
            "env": "env",
            "secret_refs": "secret_refs",
            "timeout_seconds": "timeout_seconds",
            "trust": "trust",
            "requested_isolation": "requested_isolation",
            "max_concurrent_calls": "max_concurrent_calls",
            "eager_connect": "eager_connect",
            "expand_tools": "expand_tools",
            "semantic_effects": "semantic_effects",
            "metadata": "metadata",
            "enabled": "enabled",
            "transport": "transport",
        }
        kwargs: dict[str, Any] = {
            "display_name": data["display_name"],
            "transport": data["transport"],
            "source_kind": config.source_kind,
            "source_key": config.source_key,
            "server_id": config.server_id,
            "command": data["command"],
            "args": data["args"],
            "url": data["url"],
            "cwd": data["cwd"],
            "env": data["env"],
            "secret_refs": data["secret_refs"],
            "timeout_seconds": data["timeout_seconds"],
            "enabled": data["enabled"],
            "trust": data["trust"],
            "requested_isolation": data["requested_isolation"],
            "max_concurrent_calls": data["max_concurrent_calls"],
            "owner_module_id": config.owner_module_id,
            "eager_connect": data["eager_connect"],
            "expand_tools": data["expand_tools"],
            "semantic_effects": data["semantic_effects"],
            "metadata": data["metadata"],
        }
        for src, dest in mapping.items():
            if src in patch and patch[src] is not None:
                kwargs[dest] = patch[src]
        return self.register_server(**kwargs)

    def enable(self, server_id: str) -> McpServerConfig:
        self._require_feature()
        config = self.store.set_enabled(server_id, True)
        if config is None:
            raise McpError(MCP_SERVER_NOT_FOUND, f"Unknown MCP server: {server_id}", http_status=404)
        self.store.update_runtime_state(server_id, state=McpServerState.DISCONNECTED)
        return config

    def disable(self, server_id: str) -> McpServerConfig:
        try:
            self.disconnect(server_id)
        except McpError:
            pass
        config = self.store.set_enabled(server_id, False)
        if config is None:
            raise McpError(MCP_SERVER_NOT_FOUND, f"Unknown MCP server: {server_id}", http_status=404)
        self.store.update_runtime_state(server_id, state=McpServerState.DISABLED)
        self.sync.mark_unavailable(config)
        return config

    # --- lifecycle ---

    def connect(self, server_id: str) -> McpServerRuntime:
        self._require_feature()
        config = self.require_server(server_id)
        if not config.enabled:
            raise McpError(MCP_SERVER_DISABLED, f"MCP server disabled: {server_id}")
        with self._lock:
            session = self._sessions.get(server_id)
            if session is None:
                session = McpServerSession(
                    config=config,
                    limits=self.limits,
                    allow_outbound=self.allow_outbound,
                    secret_overrides=self.secret_overrides,
                )
                self._sessions[server_id] = session
            else:
                session.config = config
        runtime = session.connect()
        self.store.update_runtime_state(
            server_id,
            state=runtime.state,
            effective_isolation=runtime.effective_isolation,
            connected=True,
            seen=True,
        )
        self.telemetry["connects"] += 1
        if config.expand_tools:
            try:
                self.refresh_tools(server_id)
            except McpError as exc:
                runtime.state = McpServerState.DEGRADED
                runtime.last_error_code = exc.code
                runtime.last_error_message = exc.message
                self.store.update_runtime_state(
                    server_id,
                    state=McpServerState.DEGRADED,
                    last_error_code=exc.code,
                    last_error_message=exc.message,
                )
        return runtime

    def disconnect(self, server_id: str) -> McpServerRuntime:
        config = self.store.get_server(server_id)
        with self._lock:
            session = self._sessions.pop(server_id, None)
        if session is not None:
            session.disconnect()
            runtime = session.health()
        else:
            runtime = McpServerRuntime(
                server_id=server_id,
                state=McpServerState.DISABLED if config and not config.enabled else McpServerState.DISCONNECTED,
            )
        if config is not None:
            self.sync.mark_unavailable(config)
        self.store.update_runtime_state(server_id, state=runtime.state)
        self.telemetry["disconnects"] += 1
        return runtime

    def refresh_tools(self, server_id: str) -> list[McpToolRecord]:
        session = self._require_session(server_id)
        config = self.require_server(server_id)
        tools = session.list_tools(force_refresh=True)
        before = len(self.sync.schema_change_events)
        records = self.sync.sync_tools(
            config,
            tools,
            protocol_version=session.runtime.protocol_version,
            server_version=session.runtime.server_version,
            available=True,
        )
        self.telemetry["schema_changes"] += len(self.sync.schema_change_events) - before
        self.store.update_runtime_state(server_id, state=session.runtime.state, seen=True)
        return records

    # --- invoke (bridge only — callers should use gateway) ---

    def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        capability_id: str | None = None,
        requester: str = "bridge",
        approval_id: str | None = None,
        trace_id: str | None = None,
        lazy_connect: bool = True,
    ) -> McpCallResult:
        """Low-level tool call. Prefer ExecutionGateway for authorized invokes."""
        self._require_feature()
        config = self.require_server(server_id)
        if not config.enabled:
            raise McpError(MCP_SERVER_DISABLED, f"MCP server disabled: {server_id}")
        if lazy_connect and server_id not in self._sessions:
            self.connect(server_id)
        session = self._require_session(server_id)
        tool = None
        if capability_id:
            tool = self.store.get_tool(capability_id)
        if tool is None:
            for item in self.store.list_tools(server_id=server_id):
                if item.external_name == tool_name:
                    tool = item
                    break
        if tool is None:
            raise McpError(MCP_TOOL_NOT_FOUND, f"Unknown MCP tool: {tool_name}", http_status=404)

        started_at = utc_now()
        call_id = self.store.new_call_id()
        result = session.call_tool(tool_name, arguments or {})
        finished_at = utc_now()
        summary = self._summarize_result(result)
        args_summary = self._summarize_args(arguments or {})
        self.store.record_call(
            McpToolCallRecord(
                call_id=call_id,
                trace_id=trace_id,
                server_id=server_id,
                capability_id=tool.capability_id,
                external_tool_name=tool_name,
                requester=requester,
                status=result.status,
                duration_ms=result.duration_ms,
                approval_id=approval_id,
                arguments_summary=args_summary,
                result_summary=summary,
                error_code=result.error_code,
                error_message=result.error_message,
                started_at=started_at,
                finished_at=finished_at,
                schema_hash=tool.schema_hash,
            )
        )
        self.telemetry["tool_calls"] += 1
        if result.status != McpCallStatus.COMPLETED:
            self.telemetry["tool_call_failures"] += 1
        return result

    # --- queries ---

    def require_server(self, server_id: str) -> McpServerConfig:
        config = self.store.get_server(server_id)
        if config is None:
            raise McpError(MCP_SERVER_NOT_FOUND, f"Unknown MCP server: {server_id}", http_status=404)
        return config

    def list_servers(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for config in self.store.list_servers():
            runtime = self.server_health(config.server_id)
            out.append({**config.public_dict(), "runtime": runtime.public_dict()})
        return out

    def get_server_public(self, server_id: str) -> dict[str, Any]:
        config = self.require_server(server_id)
        return {**config.public_dict(), "runtime": self.server_health(server_id).public_dict()}

    def list_tools(self, *, server_id: str | None = None) -> list[McpToolRecord]:
        return self.store.list_tools(server_id=server_id)

    def list_calls(self, *, limit: int = 100, server_id: str | None = None) -> list[McpToolCallRecord]:
        return self.store.list_calls(limit=limit, server_id=server_id)

    def server_health(self, server_id: str) -> McpServerRuntime:
        with self._lock:
            session = self._sessions.get(server_id)
        if session is not None:
            return session.health()
        snap = self.store.load_runtime_snapshot(server_id)
        if snap is None:
            raise McpError(MCP_SERVER_NOT_FOUND, f"Unknown MCP server: {server_id}", http_status=404)
        # Never trust persisted READY after process restart.
        if snap.state in {McpServerState.READY, McpServerState.BUSY, McpServerState.DEGRADED}:
            snap.state = McpServerState.DISCONNECTED
        return snap

    def health_summary(self) -> McpHealthSummary:
        servers = self.store.list_servers()
        tools = self.store.list_tools()
        ready = 0
        connected = 0
        enabled = 0
        last_error = None
        for config in servers:
            if config.enabled:
                enabled += 1
            try:
                runtime = self.server_health(config.server_id)
            except McpError:
                continue
            if runtime.state in {McpServerState.READY, McpServerState.BUSY, McpServerState.DEGRADED}:
                ready += 1
                connected += 1
            elif runtime.state == McpServerState.CONNECTING:
                connected += 1
            if runtime.last_error_message:
                last_error = runtime.last_error_message
        unavailable = sum(1 for t in tools if t.availability.value != "available")
        return McpHealthSummary(
            registered_servers=len(servers),
            enabled_servers=enabled,
            connected_servers=connected,
            ready_servers=ready,
            tool_count=len(tools),
            unavailable_tools=unavailable,
            last_error=last_error,
            feature_enabled=self.enabled,
        )

    def register_servers_from_module(
        self,
        module_id: str,
        mcp_meta: dict[str, Any],
        *,
        module_root: Path | None = None,
    ) -> list[McpServerConfig]:
        """Register servers declared in module.json mcp block."""
        if not self.enabled:
            return []
        servers_raw = mcp_meta.get("servers") or []
        if not isinstance(servers_raw, list):
            return []
        default_trust = str(mcp_meta.get("default_trust") or "untrusted")
        expand = bool(mcp_meta.get("expand_tools", True))
        registered: list[McpServerConfig] = []
        for item in servers_raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            transport = str(item.get("transport") or "stdio")
            command = item.get("command")
            args = item.get("args") or []
            if module_root is not None and isinstance(args, list):
                # Resolve relative script paths against module root when present.
                resolved_args = []
                for arg in args:
                    text = str(arg)
                    candidate = module_root / text
                    resolved_args.append(str(candidate) if candidate.exists() else text)
                args = resolved_args
            try:
                config = self.register_server(
                    display_name=name,
                    transport=transport,
                    source_kind=McpSourceKind.MODULE,
                    source_key=f"{module_id}:{name}",
                    command=str(command) if command else None,
                    args=list(args) if isinstance(args, list) else [],
                    url=item.get("url"),
                    cwd=str(item["cwd"]) if item.get("cwd") else (str(module_root) if module_root else None),
                    env=dict(item.get("env") or {}),
                    secret_refs=dict(item.get("secret_refs") or {}),
                    timeout_seconds=float(item.get("timeout_seconds") or 30),
                    enabled=bool(item.get("enabled", True)),
                    trust=str(item.get("trust") or default_trust),
                    requested_isolation=str(item.get("isolation") or item.get("requested_isolation") or "subprocess"),
                    max_concurrent_calls=int(item.get("max_concurrent_calls") or 4),
                    owner_module_id=module_id,
                    eager_connect=bool(item.get("eager_connect", False)),
                    expand_tools=expand and bool(item.get("expand_tools", True)),
                    semantic_effects=dict(item.get("semantic_effects") or {}),
                    metadata={"module_id": module_id, "required": bool(item.get("required", False))},
                )
                registered.append(config)
                if self.auto_expand_modules and config.enabled and config.expand_tools:
                    try:
                        self.connect(config.server_id)
                    except McpError:
                        # Optional MCP failure must not kill the module.
                        if config.metadata.get("required"):
                            raise
            except McpError:
                if bool(item.get("required", False)):
                    raise
                continue
        return registered

    def unregister_module_servers(self, module_id: str) -> int:
        removed = 0
        for config in list(self.store.list_servers()):
            if config.source_kind == McpSourceKind.MODULE and config.owner_module_id == module_id:
                self.unregister_server(config.server_id)
                removed += 1
        return removed

    # --- helpers ---

    def _require_feature(self) -> None:
        if not self.enabled:
            raise McpError(MCP_FEATURE_DISABLED, "MCP feature disabled", http_status=503)

    def _require_session(self, server_id: str) -> McpServerSession:
        with self._lock:
            session = self._sessions.get(server_id)
        if session is None or not session.ready:
            raise McpError(
                "MCP_SERVER_UNAVAILABLE",
                f"MCP server session unavailable: {server_id}",
            )
        return session

    def _summarize_result(self, result: McpCallResult) -> str:
        payload = result.public_dict()
        text = json.dumps(
            {
                "status": payload["status"],
                "is_error": payload["is_error"],
                "truncated": payload["truncated"],
                "content": payload.get("content"),
                "error_code": payload.get("error_code"),
            },
            ensure_ascii=False,
        )
        return sanitize_text_for_log(
            text,
            secret_values=None,
            max_chars=self.limits.result_summary_chars,
        )

    def _summarize_args(self, arguments: dict[str, Any]) -> str:
        text = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        return sanitize_text_for_log(text, max_chars=self.limits.arguments_summary_chars)
