"""MCP host manager: CRUD, sessions, discovery, invoke, plugin mirror."""

from __future__ import annotations

import copy
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from mcp_host.catalog import catalog_items, enrich_catalog_status, get_catalog_item
from mcp_host.clients import HttpMcpClient, McpClientError, StdioMcpClient
from mcp_host.oauth import (
    cancel_oauth_flow,
    complete_oauth_flow,
    discover_auth,
    refresh_oauth_token,
    start_oauth_flow,
)
from mcp_host.policy import (
    McpPolicyError,
    mcp_network_scope,
    mcp_subprocess_scope,
    mcp_tool_scope,
    request_mcp_policy_approval,
    require_network_policy,
    require_subprocess_policy,
    resolve_scoped_approval,
    settings_approved_flag,
)
from mcp_host.protocol import (
    canonical_mcp_resource_uri,
    connection_status_for_generation,
    finite_timeout,
    json_size_ok,
    protocol_generation,
    redact_mapping,
    stable_tool_id,
)
from mcp_host.secrets import SecretStorageUnavailable, secret_store
from mcp_host.store import McpStore
from mcp_host.validation import validate_tool_arguments

_MANAGER: "McpManager | None" = None
_MANAGER_LOCK = threading.Lock()


def get_mcp_manager() -> "McpManager | None":
    return _MANAGER


def set_mcp_manager(manager: "McpManager | None") -> None:
    global _MANAGER
    with _MANAGER_LOCK:
        _MANAGER = manager


def is_mcp_tool_metadata(tool: dict[str, Any] | None, plugin: dict[str, Any] | None = None) -> bool:
    meta = (tool or {}).get("metadata") if isinstance((tool or {}).get("metadata"), dict) else {}
    name = str((tool or {}).get("name") or "")
    if meta.get("mcp") or meta.get("mcp_remote") or meta.get("mcp_managed") or meta.get("mcp_tool"):
        return True
    if name.startswith("mcp.") or name.startswith("mcp__"):
        return True
    if plugin and "mcp" in str(plugin.get("plugin_type") or "").lower():
        return True
    if plugin and "mcp" in str(plugin.get("runtime_type") or plugin.get("runtime") or "").lower():
        return True
    return False


class McpManager:
    def __init__(
        self,
        platform_db: Any,
        *,
        plugin_manager: Any | None = None,
        settings_provider: Callable[[], dict[str, Any]] | None = None,
        permission_checker: Callable[..., None] | None = None,
        approval_service: Any | None = None,
    ) -> None:
        self.platform_db = platform_db
        self.plugin_manager = plugin_manager
        self.settings_provider = settings_provider or (lambda: {})
        self.permission_checker = permission_checker
        self.approval_service = approval_service
        self.store = McpStore(platform_db)
        self._sessions: dict[str, Any] = {}
        self._session_lock = threading.RLock()
        self._connect_locks: dict[str, threading.Lock] = {}
        self._active_executions: dict[str, str] = {}  # exec_id -> server_id
        self._reconnect_backoff: dict[str, float] = {}
        self._oauth_refresh_lock = threading.Lock()
        self._tool_call_counts: dict[str, int] = {}
        self._tool_call_lock = threading.Lock()
        self.init_error: str | None = None
        self.subsystem_status: str = "ok"

    def _settings(self) -> dict[str, Any]:
        try:
            return dict(self.settings_provider() or {})
        except Exception:
            return {}

    def _connect_lock(self, server_id: str) -> threading.Lock:
        with self._session_lock:
            lock = self._connect_locks.get(server_id)
            if lock is None:
                lock = threading.Lock()
                self._connect_locks[server_id] = lock
            return lock

    def _max_connections(self) -> int:
        settings = self._settings()
        raw = settings.get("mcp.max_connections", settings.get("mcp_max_connections", 8))
        try:
            return max(1, int(raw))
        except Exception:
            return 8

    def _mcp_enabled(self) -> bool:
        settings = self._settings()
        if "mcp.enabled" in settings:
            return bool(settings.get("mcp.enabled"))
        if "mcp_enabled" in settings:
            return bool(settings.get("mcp_enabled"))
        return True

    # --- Catalog / CRUD -------------------------------------------------

    def catalog(self) -> dict[str, Any]:
        servers = self.store.list_servers()
        self.reconcile_plugin_servers()
        servers = self.store.list_servers()
        items = enrich_catalog_status(catalog_items(), servers)
        return {"items": items, "count": len(items), "secret_storage": secret_store.available()}

    def list_servers(self) -> list[dict[str, Any]]:
        self.reconcile_plugin_servers()
        servers = self.store.list_servers()
        for server in servers:
            self._annotate_server(server)
        return servers

    def get_server(self, server_id: str) -> dict[str, Any] | None:
        server = self.store.get_server(server_id)
        if server:
            self._annotate_server(server)
        return server

    def assert_tool_authorization(
        self,
        tool: dict[str, Any],
        *,
        invocation_type: str,
        approved_by_user: bool = False,
        approval_id: str | None = None,
    ) -> None:
        """Central MCP tool authorization invariant.

        Distinctions:
        - allowed: global enablement for the tool (default deny on discovery)
        - chatbot_enabled: shortlist/visibility only; never grants execution
        - manual: UI/API one-shot; blocked tools require a persisted ApprovalService
          decision with exact tool scope (``approval_id``)
        - autonomous: model/workflow; requires allowed and approval when require_approval
        - require_approval: autonomous path needs a validated ``approval_id``

        ``approved_by_user`` is informational/audit only — never authorization authority.
        """
        itype = str(invocation_type or "manual").strip().lower() or "manual"
        allowed = bool(tool.get("allowed"))
        require_approval = bool(tool.get("require_approval"))
        # Client boolean is not evidence of approval (kept for audit callers only).
        _ = bool(approved_by_user)

        has_scoped_approval = False
        if approval_id:
            scope = mcp_tool_scope(
                server_id=str(tool.get("server_id") or ""),
                tool_id=str(tool.get("id") or ""),
                tool_name=str(tool.get("remote_name") or tool.get("name") or ""),
                effect="mcp_tool_invoke",
            )
            has_scoped_approval = resolve_scoped_approval(
                self.approval_service,
                approval_id=approval_id,
                expected_scope=scope,
            )
            if not has_scoped_approval:
                raise PermissionError(
                    "approval_invalid: persisted ApprovalService decision missing, "
                    "expired, rejected, or scope mismatch"
                )

        if not allowed:
            if itype == "manual" and has_scoped_approval:
                return
            raise PermissionError(
                "Tool is geblokkeerd — zet Allowed aan of lever een geldige approval_id "
                "van een goedgekeurde ApprovalService-aanvraag"
            )
        if require_approval and itype != "manual" and not has_scoped_approval:
            raise PermissionError("Goedkeuring vereist voor deze MCP-tool (approval_id)")
        if self.permission_checker is not None:
            # approved_by_user retained for checker signature compatibility (audit only).
            self.permission_checker(
                tool,
                invocation_type=itype,
                approved_by_user=bool(approved_by_user),
            )

    def request_tool_approval(
        self,
        tool: dict[str, Any],
        *,
        arguments: dict[str, Any] | None = None,
        invocation_type: str = "manual",
    ) -> dict[str, Any]:
        """Create a durable ApprovalService request for an MCP tool invoke."""
        if self.approval_service is None:
            raise RuntimeError("approval_required_but_unavailable")
        scope = mcp_tool_scope(
            server_id=str(tool.get("server_id") or ""),
            tool_id=str(tool.get("id") or ""),
            tool_name=str(tool.get("remote_name") or tool.get("name") or ""),
            effect="mcp_tool_invoke",
        )
        return self.approval_service.create_tool_approval(
            plugin_id=f"mcp:{tool.get('server_id')}",
            tool_name=str(tool.get("remote_name") or tool.get("name") or "mcp.tool"),
            arguments=dict(arguments or {}),
            expected_effect=f"mcp tool invoke ({invocation_type})",
            schema_version="mcp-tool-1",
            scope=scope,
        )

    def _annotate_server(self, server: dict[str, Any]) -> None:
        tools = self.store.list_tools(server["id"])
        server["tool_count"] = len(tools)
        server["allowed_tool_count"] = sum(1 for t in tools if t.get("allowed"))
        server["chatbot_tool_count"] = sum(1 for t in tools if t.get("chatbot_enabled"))
        live = False
        generation = protocol_generation(server.get("protocol_version"))
        transport_error = None
        with self._session_lock:
            client = self._sessions.get(server["id"])
            live = bool(client and getattr(client, "alive", False))
            if client is not None:
                transport_error = getattr(client, "last_transport_error", None)
                generation = getattr(client, "protocol_generation", generation) or generation
        server["session_live"] = live
        server["protocol_generation"] = generation
        status = server.get("connection_status")
        # Truthful effective status: local object ≠ verified remote session.
        if not server.get("enabled"):
            server["connection_status_effective"] = "disabled"
        elif status in {"auth_required", "policy_blocked", "error", "disabled"}:
            server["connection_status_effective"] = status
        elif status in {"connected", "ready"} and server.get("owner_kind") != "plugin":
            if transport_error:
                server["connection_status_effective"] = "error"
            elif generation == "modern":
                # 2026 is stateless — "ready" means last verification succeeded and
                # client object is open; not a persistent session claim.
                server["connection_status_effective"] = "ready" if live else "disconnected"
            else:
                server["connection_status_effective"] = "connected" if live else "disconnected"
        else:
            server["connection_status_effective"] = status
        server["ui_connected"] = server["connection_status_effective"] in {"connected", "ready"}

    def create_server(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = self._normalize_server_payload(payload, existing=None)
        if not self._mcp_enabled() and body.get("enabled", True):
            raise PermissionError("MCP is uitgeschakeld in instellingen (mcp.enabled)")
        server = self.store.upsert_server(body)
        if server.get("auto_connect") and server.get("enabled"):
            try:
                self.connect(server["id"])
            except Exception as exc:
                self.store.update_server_status(
                    server["id"],
                    connection_status="error",
                    last_error=str(exc),
                    last_error_kind=getattr(exc, "kind", "transport"),
                )
        return self.get_server(server["id"])  # type: ignore[return-value]

    def update_server(self, server_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        existing = self.store.get_server(server_id)
        if not existing:
            raise KeyError(server_id)
        if existing.get("owner_kind") == "plugin":
            # Plugin-owned: only prefs (enabled/auto_connect/description) — not transport takeover.
            allowed = {"enabled", "auto_connect", "description", "timeout_seconds", "name"}
            filtered = {k: v for k, v in payload.items() if k in allowed}
            merged = {**existing, **filtered}
            env = existing.get("env") or {}
            merged["env"] = {"plain": env.get("plain") or {}, "secret_refs": env.get("secret_refs") or {}}
            server = self.store.upsert_server(merged)
            self._mirror_plugin_state(server)
            return self.get_server(server_id)  # type: ignore[return-value]
        body = self._normalize_server_payload(payload, existing=existing)
        body["id"] = server_id
        # Reconnect if transport-critical fields changed while connected.
        was_live = False
        with self._session_lock:
            was_live = server_id in self._sessions
        server = self.store.upsert_server(body)
        if was_live:
            self.disconnect(server_id)
            if server.get("enabled"):
                self.connect(server_id)
        return self.get_server(server_id)  # type: ignore[return-value]

    def _normalize_server_payload(self, payload: dict[str, Any], *, existing: dict[str, Any] | None) -> dict[str, Any]:
        catalog_id = payload.get("catalog_id", (existing or {}).get("catalog_id"))
        catalog = get_catalog_item(str(catalog_id)) if catalog_id else None
        transport = str(payload.get("transport") or (existing or {}).get("transport") or (catalog or {}).get("transport") or "stdio")
        if transport == "custom":
            transport = str(payload.get("transport_choice") or payload.get("chosen_transport") or "stdio")
        if transport not in {"stdio", "streamable_http"}:
            raise ValueError(f"Onbekend transport: {transport}")
        name = str(payload.get("name") or (existing or {}).get("name") or (catalog or {}).get("name") or "").strip()
        body: dict[str, Any] = {
            "id": payload.get("id") or (existing or {}).get("id") or uuid.uuid4().hex,
            "name": name,
            "description": payload.get("description", (existing or {}).get("description") or (catalog or {}).get("description") or ""),
            "transport": transport,
            "enabled": payload.get("enabled", (existing or {}).get("enabled", True)),
            "auto_connect": payload.get("auto_connect", (existing or {}).get("auto_connect", False)),
            "owner_kind": payload.get("owner_kind", (existing or {}).get("owner_kind") or "managed"),
            "owner_plugin_id": payload.get("owner_plugin_id", (existing or {}).get("owner_plugin_id")),
            "catalog_id": catalog_id,
            "timeout_seconds": float(payload.get("timeout_seconds") or (existing or {}).get("timeout_seconds") or 60),
            "auth_method": str(payload.get("auth_method") or (existing or {}).get("auth_method") or "none"),
            "metadata": payload.get("metadata") or (existing or {}).get("metadata") or {},
        }
        if transport == "stdio":
            command = payload.get("command") or (existing or {}).get("command")
            if isinstance(command, dict):
                executable = str(command.get("executable") or "").strip()
                args = command.get("args") or []
                if not isinstance(args, list):
                    raise ValueError("command.args must be a list of separate values")
                cwd = command.get("cwd")
                body["command"] = {"executable": executable, "args": [str(a) for a in args], "cwd": cwd}
            elif catalog and catalog.get("command_template") and not command:
                tmpl = catalog["command_template"]
                body["command"] = {"executable": tmpl["executable"], "args": list(tmpl.get("args") or []), "cwd": None}
            else:
                raise ValueError("stdio-server vereist command.executable (+ optionele args)")
            if not body["command"]["executable"]:
                raise ValueError("executable is verplicht")
            env_in = payload.get("env") if isinstance(payload.get("env"), dict) else None
            plain: dict[str, str] = {}
            secret_refs: dict[str, str] = {}
            if existing and isinstance(existing.get("env"), dict):
                plain = dict((existing["env"].get("plain") or {}))
                secret_refs = dict((existing["env"].get("secret_refs") or {}))
            if env_in:
                plain = {str(k): str(v) for k, v in (env_in.get("plain") or {}).items()}
                secrets_in = env_in.get("secrets") if isinstance(env_in.get("secrets"), dict) else {}
                for key, value in secrets_in.items():
                    if value in (None, "", "***"):
                        continue
                    ref = secret_refs.get(str(key)) or secret_store.new_ref(body["id"], f"env_{key}")
                    secret_store.store(ref, str(value))
                    secret_refs[str(key)] = ref
                # Allow deleting secret keys explicitly
                for key in list(secret_refs):
                    if env_in.get("secrets") is not None and str(key) not in (env_in.get("secrets") or {}) and str(key) not in (env_in.get("keep_secrets") or []):
                        # Only drop when secrets map provided and key omitted with drop_missing
                        if env_in.get("drop_missing_secrets"):
                            secret_store.delete(secret_refs.pop(key, None))
            body["env"] = {"plain": plain, "secret_refs": secret_refs}
            body["endpoint_url"] = None
            body["headers"] = {}
        else:
            endpoint = str(payload.get("endpoint_url") or (existing or {}).get("endpoint_url") or (catalog or {}).get("endpoint_url") or "").strip()
            if not endpoint:
                raise ValueError("endpoint_url is verplicht voor streamable_http")
            body["endpoint_url"] = endpoint
            body["command"] = None
            headers = payload.get("headers")
            if headers is None:
                headers = (existing or {}).get("headers") or {}
            if not isinstance(headers, dict):
                raise ValueError("headers must be an object")
            # Strip authorization from plain headers — must go through secret store.
            clean_headers = {str(k): str(v) for k, v in headers.items() if "authorization" not in str(k).lower()}
            body["headers"] = clean_headers
            env = {"plain": {}, "secret_refs": {}}
            if existing and isinstance(existing.get("env"), dict):
                env = {"plain": {}, "secret_refs": dict(existing["env"].get("secret_refs") or {})}
            body["env"] = env
            auth_method = body["auth_method"]
            if auth_method not in {"none", "bearer", "oauth"}:
                raise ValueError(f"Onbekende auth_method: {auth_method}")
            token = payload.get("bearer_token") or payload.get("auth_token")
            if token and token != "***":
                ref = (existing or {}).get("auth_secret_ref") or secret_store.new_ref(body["id"], "bearer")
                secret_store.store(ref, str(token))
                body["auth_secret_ref"] = ref
                body["auth_status"] = "configured"
            elif existing:
                body["auth_secret_ref"] = existing.get("auth_secret_ref")
            if auth_method == "none":
                body["auth_status"] = "none"
            elif auth_method in {"bearer", "oauth"} and not body.get("auth_secret_ref") and not (existing or {}).get("auth_secret_ref"):
                body["auth_status"] = "required"
            elif auth_method == "oauth" and not body.get("auth_secret_ref"):
                body["auth_status"] = "required"
        return body

    def delete_server(self, server_id: str) -> dict[str, Any]:
        server = self.store.get_server(server_id)
        if not server:
            raise KeyError(server_id)
        if server.get("owner_kind") == "plugin":
            raise PermissionError(
                "Deze MCP-server wordt beheerd door een plugin. Verwijder of deactiveer de plugin via Plugin Manager."
            )
        self.disconnect(server_id)
        refs = self._collect_secret_refs(server)
        failures: list[dict[str, Any]] = []
        deleted_refs: list[str] = []
        for ref in refs:
            result = secret_store.delete(ref, missing_ok=True)
            if not result.get("ok"):
                failures.append({"ref": ref, "error": result.get("error") or result.get("error_type") or "delete_failed"})
            else:
                deleted_refs.append(ref)
        if failures:
            # Keep the server row so remaining secret refs stay recoverable.
            meta = dict(server.get("metadata") or {})
            meta["secret_cleanup_failures"] = failures
            meta["secret_cleanup_pending"] = [item["ref"] for item in failures]
            server["metadata"] = meta
            self.store.upsert_server(server)
            self.store.update_server_status(
                server_id,
                connection_status="error",
                last_error="Secret cleanup failed — server row retained for retry",
                last_error_kind="dependency",
            )
            return {
                "ok": False,
                "deleted": False,
                "server_id": server_id,
                "secret_cleanup_failures": failures,
                "deleted_refs_count": len(deleted_refs),
                "error": "Secure secret cleanup failed; server was not removed",
            }
        self._remove_mirror_plugin(server_id)
        self.store.delete_server(server_id)
        return {"ok": True, "deleted": server_id, "deleted_refs_count": len(deleted_refs)}

    def _collect_secret_refs(self, server: dict[str, Any]) -> list[str]:
        refs: list[str] = []
        env = server.get("env") or {}
        for ref in (env.get("secret_refs") or {}).values():
            if ref:
                refs.append(str(ref))
        if server.get("auth_secret_ref"):
            refs.append(str(server["auth_secret_ref"]))
        meta = server.get("metadata") if isinstance(server.get("metadata"), dict) else {}
        for key in ("oauth_refresh_ref", "oauth_access_ref"):
            if meta.get(key):
                refs.append(str(meta[key]))
        # Deduplicate while preserving order.
        seen: set[str] = set()
        out: list[str] = []
        for ref in refs:
            if ref not in seen:
                seen.add(ref)
                out.append(ref)
        return out

    def duplicate_server(self, server_id: str) -> dict[str, Any]:
        server = self.store.get_server(server_id)
        if not server:
            raise KeyError(server_id)
        clone = copy.deepcopy(server)
        clone.pop("id", None)
        clone["name"] = f"{server['name']} (kopie)"
        clone["auto_connect"] = False
        clone["connection_status"] = "configured"
        clone["last_error"] = None
        clone["last_error_kind"] = None
        clone["protocol_version"] = None
        clone["discovery_complete"] = False
        clone["auth_secret_ref"] = None
        clone["auth_status"] = "required" if server.get("auth_method") in {"bearer", "oauth"} else "none"
        clone["owner_kind"] = "managed"
        clone["owner_plugin_id"] = None
        env = clone.get("env") or {}
        clone["env"] = {"plain": dict(env.get("plain") or {}), "secret_refs": {}, "secrets": {}}
        # Ensure unique name
        base = clone["name"]
        n = 2
        while self.store.get_server_by_name(clone["name"]):
            clone["name"] = f"{base} {n}"
            n += 1
        return self.create_server(clone)

    def set_enabled(self, server_id: str, enabled: bool) -> dict[str, Any]:
        server = self.store.get_server(server_id)
        if not server:
            raise KeyError(server_id)
        if not enabled:
            self.disconnect(server_id)
        env = server.get("env") or {}
        server["enabled"] = bool(enabled)
        server["env"] = {"plain": env.get("plain") or {}, "secret_refs": env.get("secret_refs") or {}}
        server["connection_status"] = "disabled" if not enabled else ("disconnected" if not server.get("connection_status") == "connected" else "disconnected")
        if not enabled:
            server["connection_status"] = "disabled"
        else:
            server["connection_status"] = "configured"
        saved = self.store.upsert_server(server)
        self._mirror_plugin_state(saved)
        return self.get_server(server_id)  # type: ignore[return-value]

    # --- Sessions -------------------------------------------------------

    def connect(self, server_id: str, *, approval_id: str | None = None) -> dict[str, Any]:
        if not self._mcp_enabled():
            raise PermissionError("MCP is uitgeschakeld in instellingen")
        lock = self._connect_lock(server_id)
        if not lock.acquire(blocking=False):
            raise RuntimeError("Verbinden is al bezig voor deze server (geen dubbel proces)")
        try:
            server = self.store.get_server(server_id)
            if not server:
                raise KeyError(server_id)
            if not server.get("enabled"):
                raise RuntimeError("Server is uitgeschakeld")
            if server.get("owner_kind") == "plugin":
                return self._connect_plugin_owned(server)
            # Connection budget
            with self._session_lock:
                live = sum(1 for c in self._sessions.values() if getattr(c, "alive", False))
            if live >= self._max_connections() and server_id not in self._sessions:
                raise RuntimeError(f"Maximum aantal MCP-verbindingen bereikt ({self._max_connections()})")
            self._close_session(server_id)
            self.store.update_server_status(server_id, connection_status="connecting", clear_error=True)
            try:
                client = self._build_client(server, approval_id=approval_id)
                init = client.initialize()
                listed = client.list_tools_all()
                stats = self.store.replace_discovered_tools(server_id, listed.get("tools") or [])
                generation = listed.get("protocol_generation") or protocol_generation(listed.get("protocol_version"))
                status = connection_status_for_generation(generation, verified=True)
                self.store.update_server_status(
                    server_id,
                    connection_status=status,
                    protocol_version=listed.get("protocol_version"),
                    discovery_complete=bool(listed.get("complete")),
                    touch_check=True,
                    clear_error=True,
                    auth_status="ok" if server.get("auth_method") != "none" else server.get("auth_status"),
                )
                with self._session_lock:
                    self._sessions[server_id] = client
                self._mirror_to_plugin(server_id)
                return {
                    "ok": True,
                    "server": self.get_server(server_id),
                    "initialize": init,
                    "discovery": {**stats, "complete": listed.get("complete"), "notes": listed.get("notes")},
                    "protocol_generation": generation,
                }
            except McpPolicyError as exc:
                if exc.approval_required:
                    approval = self._ensure_policy_approval(server, effect=exc.effect or "mcp_connect")
                    self.store.update_server_status(
                        server_id,
                        connection_status="policy_blocked",
                        last_error=str(exc),
                        last_error_kind="permission",
                    )
                    raise McpPolicyError(
                        str(exc),
                        kind=exc.kind,
                        approval_required=True,
                        approval=approval,
                        effect=exc.effect,
                    ) from exc
                self.store.update_server_status(
                    server_id,
                    connection_status="policy_blocked",
                    last_error=str(exc),
                    last_error_kind="permission",
                )
                raise
            except Exception as exc:
                self.store.update_server_status(
                    server_id,
                    connection_status="error" if "auth" not in str(getattr(exc, "kind", "")).lower() else "auth_required",
                    last_error=str(exc),
                    last_error_kind=getattr(exc, "kind", "unknown_outcome"),
                )
                try:
                    client.close()  # type: ignore[name-defined]
                except Exception:
                    pass
                raise
        finally:
            lock.release()

    def _connect_plugin_owned(self, server: dict[str, Any]) -> dict[str, Any]:
        """Plugin-owned MCP: expand via PluginManager — do not start a second process."""
        plugin_id = server.get("owner_plugin_id")
        if not plugin_id or self.plugin_manager is None:
            raise RuntimeError("Plugin-eigenaar ontbreekt voor deze MCP-server")
        self.store.update_server_status(server["id"], connection_status="connecting", clear_error=True)
        try:
            expansion = self.plugin_manager.expand_mcp_tools(plugin_id)
        except Exception as exc:
            self.store.update_server_status(
                server["id"],
                connection_status="error",
                last_error=str(exc),
                last_error_kind="transport",
                touch_check=True,
            )
            raise
        # Reflect plugin tools into mcp_tools table for the MCP page.
        plugin_tools = self.platform_db.plugin_tools(plugin_id)
        remote = []
        for tool in plugin_tools:
            meta = tool.get("metadata") or {}
            if meta.get("mcp_remote") or meta.get("mcp_tool"):
                remote.append(
                    {
                        "name": meta.get("mcp_tool") or tool.get("name"),
                        "description": tool.get("description"),
                        "inputSchema": tool.get("input_schema") or {},
                    }
                )
        stats = self.store.replace_discovered_tools(server["id"], remote)
        # Mark connected only if expansion reported tools or plugin is ready — green only after expand success.
        ok = bool(expansion.get("ok")) or int(expansion.get("expanded") or 0) > 0 or int(stats.get("total") or 0) > 0
        if expansion.get("skipped") and expansion.get("reason"):
            self.store.update_server_status(
                server["id"],
                connection_status="error",
                last_error=str(expansion.get("reason")),
                last_error_kind="dependency",
                touch_check=True,
                discovery_complete=False,
            )
        else:
            self.store.update_server_status(
                server["id"],
                connection_status="connected" if ok else "error",
                last_error=None if ok else (expansion.get("error") or "expand mislukt"),
                last_error_kind=None if ok else "transport",
                touch_check=True,
                discovery_complete=True,
                clear_error=ok,
            )
        return {"ok": ok, "server": self.get_server(server["id"]), "expansion": expansion, "discovery": stats}

    def disconnect(self, server_id: str) -> dict[str, Any]:
        server = self.store.get_server(server_id)
        self._close_session(server_id)
        if server and server.get("owner_kind") != "plugin":
            self.store.update_server_status(server_id, connection_status="disconnected" if server.get("enabled") else "disabled")
            self._mirror_plugin_state(self.store.get_server(server_id) or server)
        elif server:
            self.store.update_server_status(server_id, connection_status="disconnected" if server.get("enabled") else "disabled")
        return {"ok": True, "server": self.get_server(server_id)}

    def reconnect(self, server_id: str) -> dict[str, Any]:
        attempts = int(self._settings().get("mcp.reconnect_attempts", self._settings().get("mcp_reconnect_attempts", 3)) or 3)
        last_exc: Exception | None = None
        delay = self._reconnect_backoff.get(server_id, 0.5)
        for _ in range(max(1, attempts)):
            try:
                self.disconnect(server_id)
                result = self.connect(server_id)
                self._reconnect_backoff[server_id] = 0.5
                return result
            except Exception as exc:
                last_exc = exc
                time.sleep(min(delay, 8.0))
                delay = min(delay * 2, 8.0)
                self._reconnect_backoff[server_id] = delay
        assert last_exc is not None
        raise last_exc

    def _close_session(self, server_id: str) -> None:
        with self._session_lock:
            client = self._sessions.pop(server_id, None)
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    def _ensure_policy_approval(self, server: dict[str, Any], *, effect: str) -> dict[str, Any] | None:
        if self.approval_service is None:
            return None
        if server.get("transport") == "stdio":
            scope = mcp_subprocess_scope(server_id=str(server["id"]), command=server.get("command"), effect=effect)
            label = f"MCP stdio start ({server.get('name') or server['id']})"
        else:
            scope = mcp_network_scope(
                server_id=str(server["id"]),
                endpoint_url=str(server.get("endpoint_url") or ""),
                effect=effect,
            )
            label = f"MCP network ({server.get('name') or server['id']}) — {effect}"
        return request_mcp_policy_approval(
            self.approval_service,
            server_id=str(server["id"]),
            effect=effect,
            scope=scope,
            expected_effect=label,
        )

    def _policy_approved(self, server: dict[str, Any], *, effect: str, approval_id: str | None) -> bool:
        settings = self._settings()
        if server.get("transport") == "stdio":
            if settings_approved_flag(settings, "mcp.subprocess_approved", "approved_subprocess", "subprocess_approved"):
                return True
            scope = mcp_subprocess_scope(server_id=str(server["id"]), command=server.get("command"), effect=effect)
        else:
            if settings_approved_flag(settings, "mcp.network_approved", "approved_network", "network_approved"):
                return True
            scope = mcp_network_scope(
                server_id=str(server["id"]),
                endpoint_url=str(server.get("endpoint_url") or ""),
                effect=effect,
            )
        return resolve_scoped_approval(self.approval_service, approval_id=approval_id, expected_scope=scope)

    def _build_client(
        self,
        server: dict[str, Any],
        *,
        approval_id: str | None = None,
        internal_rebuild: bool = False,
    ) -> Any:
        timeout = finite_timeout(server.get("timeout_seconds") or 60)
        settings = self._settings()
        if server.get("transport") == "stdio":
            approved = internal_rebuild or self._policy_approved(
                server, effect="mcp_stdio_connect", approval_id=approval_id
            )
            require_subprocess_policy(
                settings,
                approved=approved,
                purpose="mcp_stdio_connect",
            )
            command = server.get("command") or {}
            executable = command.get("executable")
            args = command.get("args") or []
            cwd = command.get("cwd")
            env_plain = dict(((server.get("env") or {}).get("plain")) or {})
            known_secrets: list[str] = []
            for key, ref in (((server.get("env") or {}).get("secret_refs")) or {}).items():
                value = secret_store.get(ref)
                if value:
                    env_plain[str(key)] = value
                    known_secrets.append(value)
            return StdioMcpClient(
                [str(executable), *[str(a) for a in args]],
                env=env_plain,
                cwd=cwd,
                timeout=timeout,
                known_secrets=known_secrets,
            )
        # HTTP — refresh OAuth access token proactively when expired.
        self._maybe_refresh_oauth(server)
        server = self.store.get_server(server["id"]) or server
        headers = dict(server.get("headers") or {})
        token = None
        if server.get("auth_method") in {"bearer", "oauth"}:
            token = secret_store.get(server.get("auth_secret_ref"))
            if not token:
                raise McpClientError("Authenticatie vereist — geen token in veilige opslag", kind="auth")
        endpoint = str(server.get("endpoint_url") or "")
        approved = internal_rebuild or self._policy_approved(
            server, effect="mcp_http_connect", approval_id=approval_id
        )
        require_network_policy(
            settings,
            endpoint_url=endpoint,
            approved=approved,
            purpose="mcp_http_connect",
        )
        host_local = False
        try:
            from urllib.parse import urlparse

            host = (urlparse(endpoint).hostname or "").lower()
            host_local = host in {"127.0.0.1", "localhost", "::1"} or host.endswith(".localhost")
        except Exception:
            host_local = False
        return HttpMcpClient(
            endpoint,
            headers=headers,
            bearer_token=token,
            timeout=timeout,
            allow_private=host_local,
        )

    def _maybe_refresh_oauth(self, server: dict[str, Any]) -> None:
        if server.get("auth_method") != "oauth":
            return
        meta = server.get("metadata") if isinstance(server.get("metadata"), dict) else {}
        refresh_ref = meta.get("oauth_refresh_ref")
        token_endpoint = meta.get("oauth_token_endpoint")
        client_id = meta.get("oauth_client_id")
        expires_at = meta.get("oauth_expires_at")
        if not refresh_ref or not token_endpoint or not client_id:
            return
        try:
            expires = float(expires_at) if expires_at is not None else None
        except Exception:
            expires = None
        # Refresh a minute early when expiry is known.
        if expires is not None and expires > time.time() + 60:
            return
        with self._oauth_refresh_lock:
            refreshed = refresh_oauth_token(
                server_id=str(server["id"]),
                refresh_ref=str(refresh_ref),
                token_endpoint=str(token_endpoint),
                client_id=str(client_id),
                issuer=meta.get("oauth_issuer"),
                resource=meta.get("oauth_resource") or canonical_mcp_resource_uri(str(server.get("endpoint_url") or "")),
            )
            if not refreshed.get("ok"):
                if refreshed.get("reauth_required"):
                    self.store.update_server_status(server["id"], auth_status="required", connection_status="auth_required")
                return
            old_access = server.get("auth_secret_ref")
            server["auth_secret_ref"] = refreshed["auth_secret_ref"]
            server["auth_status"] = "ok"
            meta = dict(meta)
            meta["oauth_refresh_ref"] = refreshed.get("refresh_secret_ref") or refresh_ref
            if refreshed.get("expires_at") is not None:
                meta["oauth_expires_at"] = refreshed["expires_at"]
            server["metadata"] = meta
            env = server.get("env") or {}
            server["env"] = {"plain": env.get("plain") or {}, "secret_refs": env.get("secret_refs") or {}}
            self.store.upsert_server(server)
            if old_access and old_access != refreshed["auth_secret_ref"]:
                secret_store.delete(old_access, missing_ok=True)

    def _consume_mcp_tool_budget(self, *, scope_key: str) -> None:
        settings = self._settings()
        raw = settings.get("mcp.max_tool_calls", settings.get("mcp_max_tool_calls"))
        if raw is None or raw == "":
            return
        try:
            limit = int(raw)
        except Exception:
            return
        if limit < 0:
            return
        with self._tool_call_lock:
            used = int(self._tool_call_counts.get(scope_key) or 0)
            if used >= limit:
                raise PermissionError(f"mcp.max_tool_calls ({limit}) bereikt voor scope {scope_key}")
            self._tool_call_counts[scope_key] = used + 1

    def refresh_tools(self, server_id: str) -> dict[str, Any]:
        server = self.store.get_server(server_id)
        if not server:
            raise KeyError(server_id)
        if server.get("owner_kind") == "plugin":
            return self._connect_plugin_owned(server).get("discovery") or {}
        with self._session_lock:
            client = self._sessions.get(server_id)
        if client is None or not getattr(client, "alive", False):
            raise RuntimeError("Niet verbonden — verbind eerst opnieuw")
        listed = client.list_tools_all()
        stats = self.store.replace_discovered_tools(server_id, listed.get("tools") or [])
        complete = bool(listed.get("complete"))
        self.store.update_server_status(
            server_id,
            discovery_complete=complete,
            protocol_version=listed.get("protocol_version"),
            touch_check=True,
            clear_error=True,
            connection_status="connected",
        )
        self._mirror_to_plugin(server_id)
        return {**stats, "complete": complete, "notes": listed.get("notes") or [], "pages": listed.get("pages")}

    # --- Tools / invoke -------------------------------------------------

    def list_tools(self, *, server_id: str | None = None, q: str = "", filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        tools = self.store.list_tools(server_id)
        filters = filters or {}
        q_lower = (q or "").lower().strip()
        servers = {s["id"]: s for s in self.store.list_servers()}
        out: list[dict[str, Any]] = []
        for tool in tools:
            server = servers.get(tool["server_id"]) or {}
            if filters.get("allowed") is not None and bool(tool.get("allowed")) != bool(filters.get("allowed")):
                continue
            if filters.get("chatbot_enabled") is not None and bool(tool.get("chatbot_enabled")) != bool(filters.get("chatbot_enabled")):
                continue
            if filters.get("server_id") and tool["server_id"] != filters.get("server_id"):
                continue
            if q_lower and q_lower not in f"{tool.get('remote_name')} {tool.get('description')} {server.get('name')}".lower():
                continue
            out.append({**tool, "server_name": server.get("name"), "server_enabled": server.get("enabled"), "connection_status": server.get("connection_status")})
        return out

    def update_tool_prefs(self, tool_id: str, prefs: dict[str, Any]) -> dict[str, Any]:
        tool = self.store.update_tool_prefs(tool_id, prefs)
        if not tool:
            raise KeyError(tool_id)
        self._mirror_to_plugin(tool["server_id"])
        return tool

    def invoke_tool(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        *,
        invocation_type: str = "manual",
        approved_by_user: bool = False,
        approval_id: str | None = None,
        idempotency_key: str | None = None,
        approved_network: bool = False,
        approved_file_read: bool = False,
        approved_file_write: bool = False,
        approved_subprocess: bool = False,
        approvals: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        tool = self.store.get_tool(tool_id)
        if not tool:
            raise KeyError(tool_id)
        server = self.store.get_server(tool["server_id"])
        if not server:
            raise KeyError(tool["server_id"])
        if not server.get("enabled"):
            raise PermissionError("Server is uitgeschakeld")
        # Re-read tool prefs at execution time (shortlist is not lasting permission).
        tool = self.store.get_tool(tool_id) or tool
        try:
            self.assert_tool_authorization(
                tool,
                invocation_type=invocation_type,
                approved_by_user=approved_by_user,
                approval_id=approval_id,
            )
        except PermissionError as exc:
            # Manual blocked/approval-required tools get a durable ApprovalService request.
            message = str(exc)
            needs_request = (
                invocation_type == "manual"
                and not approval_id
                and self.approval_service is not None
                and (
                    "geblokkeerd" in message.lower()
                    or "goedkeuring vereist" in message.lower()
                    or "approval" in message.lower()
                )
            )
            if needs_request:
                req = self.request_tool_approval(
                    tool, arguments=arguments, invocation_type=invocation_type
                )
                raise McpPolicyError(
                    message,
                    kind="permission",
                    approval_required=True,
                    approval=req,
                    effect="mcp_tool_invoke",
                ) from exc
            raise
        if not json_size_ok(arguments):
            raise ValueError("Tool arguments exceed MAX_PAYLOAD_BYTES")
        from plugin_runtime_v2 import normalize_capability_approvals

        kind_approvals = normalize_capability_approvals(
            approvals,
            approved_network=approved_network,
            approved_file_read=approved_file_read,
            approved_file_write=approved_file_write,
            approved_subprocess=approved_subprocess,
        )
        # Validated durable approval_id grants kinds required by the mirrored plugin tool.
        if approval_id and self.plugin_manager is not None and self.platform_db is not None:
            plugin = self.platform_db.get_plugin(f"mcp:{server['id']}")
            if plugin:
                from plugin_runtime_v2 import build_capability_contract, required_policy_kinds

                mirror_tool = next(
                    (
                        t
                        for t in (self.platform_db.plugin_tools(plugin["id"]) or [])
                        if t.get("name") == tool.get("model_name")
                        or (t.get("metadata") or {}).get("mcp_tool") == tool.get("remote_name")
                    ),
                    None,
                )
                if mirror_tool:
                    kind_approvals = normalize_capability_approvals(
                        kind_approvals,
                        grant_kinds=required_policy_kinds(build_capability_contract(plugin, mirror_tool)),
                    )
        try:
            arguments = validate_tool_arguments(tool.get("input_schema"), arguments)
        except ValueError:
            raise

        # Re-check connection + policies at execution time.
        if server.get("owner_kind") == "plugin":
            return self._invoke_via_plugin(
                server,
                tool,
                arguments,
                invocation_type=invocation_type,
                approved_by_user=approved_by_user,
                idempotency_key=idempotency_key,
                approvals=kind_approvals,
            )

        with self._session_lock:
            client = self._sessions.get(server["id"])
            live = bool(client and getattr(client, "alive", False))
        effective = (self.get_server(server["id"]) or server).get("connection_status_effective") or server.get("connection_status")
        if not live or effective not in {"connected", "ready"}:
            raise RuntimeError("Server is niet verbonden — verbind opnieuw vóór uitvoering")

        # Central policy via plugin mirror path when available.
        if self.plugin_manager is not None:
            plugin = self.platform_db.get_plugin(f"mcp:{server['id']}")
            if plugin:
                return self._invoke_via_mirror(
                    plugin,
                    tool,
                    arguments,
                    invocation_type=invocation_type,
                    approved_by_user=approved_by_user,
                    idempotency_key=idempotency_key,
                    approvals=kind_approvals,
                )

        return self._invoke_direct(
            server,
            tool,
            arguments,
            invocation_type=invocation_type,
            approved_by_user=approved_by_user,
            idempotency_key=idempotency_key,
        )

    def _invoke_via_plugin(
        self,
        server: dict[str, Any],
        tool: dict[str, Any],
        arguments: dict[str, Any],
        *,
        invocation_type: str,
        approved_by_user: bool,
        idempotency_key: str | None,
        approvals: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        plugin_id = server.get("owner_plugin_id")
        if not plugin_id or self.plugin_manager is None:
            raise RuntimeError("Plugin invoke pad niet beschikbaar")
        # Map to plugin tool name (mcp__remote)
        from plugin_runtime_v2 import mcp_wrapper_tool

        wrapper_name = mcp_wrapper_tool(tool["remote_name"], tool.get("description") or "")["name"]
        plugin_tools = {t["name"]: t for t in self.platform_db.plugin_tools(plugin_id)}
        tool_name = wrapper_name if wrapper_name in plugin_tools else None
        if tool_name is None:
            # Fallback: match metadata.mcp_tool
            for name, pt in plugin_tools.items():
                if (pt.get("metadata") or {}).get("mcp_tool") == tool["remote_name"]:
                    tool_name = name
                    break
        if not tool_name:
            raise KeyError(f"Plugin-tool voor {tool['remote_name']} niet gevonden — expand MCP eerst")
        self._consume_mcp_tool_budget(scope_key=f"{invocation_type}:{server['id']}")
        # Input for wrapper expects arguments JSON string often — pass object if schema allows.
        input_data = arguments
        schema = (plugin_tools[tool_name].get("input_schema") or {})
        props = schema.get("properties") if isinstance(schema, dict) else {}
        if isinstance(props, dict) and "arguments" in props and "arguments" not in arguments:
            import json as _json

            input_data = {"arguments": _json.dumps(arguments)}
        result = self.plugin_manager.invoke(
            plugin_id,
            tool_name,
            input_data,
            invocation_type=invocation_type,
            approved_by_user=approved_by_user,
            approvals=approvals,
        )
        status = result.get("status") or "failed"
        self.store.mark_tool_execution(tool["id"], status)
        execution = self.store.create_execution(
            {
                "server_id": server["id"],
                "tool_id": tool["id"],
                "tool_call_id": result.get("id") or result.get("call_id"),
                "status": status,
                "input": arguments,
                "result": redact_mapping(result),
                "idempotency_key": idempotency_key,
                "error_kind": "tool_error" if status not in {"completed", "running"} else None,
            }
        )
        finished = self.store.finish_execution(
            execution["id"],
            status=status,
            result=redact_mapping(result),
            error_kind=execution.get("error_kind"),
        )
        return {"execution": finished or execution, "result": result, "via": "plugin"}

    def _invoke_via_mirror(
        self,
        plugin: dict[str, Any],
        tool: dict[str, Any],
        arguments: dict[str, Any],
        *,
        invocation_type: str,
        approved_by_user: bool,
        idempotency_key: str | None,
        approvals: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        # Ensure mirror tool exists then invoke through PluginManager (hooks into managed call).
        self._mirror_to_plugin(tool["server_id"])
        result = self.plugin_manager.invoke(
            plugin["id"],
            tool["model_name"],
            arguments,
            invocation_type=invocation_type,
            approved_by_user=approved_by_user,
            approvals=approvals,
        )
        status = result.get("status") or "failed"
        self.store.mark_tool_execution(tool["id"], status)
        execution = self.store.create_execution(
            {
                "server_id": tool["server_id"],
                "tool_id": tool["id"],
                "tool_call_id": result.get("id") or result.get("call_id"),
                "status": status if status != "running" else "completed",
                "input": arguments,
                "result": redact_mapping(result),
                "idempotency_key": idempotency_key,
                "error_kind": None if status == "completed" else (result.get("error_kind") or "tool_error"),
            }
        )
        finished = self.store.finish_execution(
            execution["id"],
            status=status,
            result=redact_mapping(result),
            error_kind=None if status == "completed" else "tool_error",
        )
        return {"execution": finished or execution, "result": result, "via": "mirror"}

    def _invoke_direct(
        self,
        server: dict[str, Any],
        tool: dict[str, Any],
        arguments: dict[str, Any],
        *,
        invocation_type: str,
        approved_by_user: bool,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        from runtime.execution_gateway import PolicyModuleUnavailable, enforce_policies_fail_closed

        settings = self._settings()
        try:
            policy = enforce_policies_fail_closed(
                tool_name=tool["model_name"],
                arguments=arguments,
                settings=settings,
                source=f"mcp_manager:{invocation_type}",
                is_mcp_tool=True,
            )
        except PolicyModuleUnavailable as exc:
            raise PermissionError(f"Policy module unavailable: {exc}") from exc
        if not policy.get("allowed"):
            raise PermissionError(f"Policy blocked: {policy.get('reason')}")
        if isinstance(policy.get("args"), dict):
            arguments = policy["args"]

        self._consume_mcp_tool_budget(scope_key=f"{invocation_type}:{server['id']}")

        execution = self.store.create_execution(
            {
                "server_id": server["id"],
                "tool_id": tool["id"],
                "status": "running",
                "input": arguments,
                "idempotency_key": idempotency_key,
            }
        )
        self._active_executions[execution["id"]] = server["id"]
        started = time.perf_counter()
        try:
            with self._session_lock:
                client = self._sessions.get(server["id"])
            if client is None:
                raise McpClientError("Sessie verloren", kind="transport")
            # Check cancel
            if execution.get("cancel_requested"):
                raise McpClientError("Geannuleerd", kind="cancelled")
            try:
                try:
                    payload = client.call_tool(
                        tool["remote_name"],
                        arguments,
                        execution_id=execution["id"],
                        input_schema=tool.get("input_schema"),
                    )
                except TypeError:
                    payload = client.call_tool(tool["remote_name"], arguments)
            except McpClientError as exc:
                if exc.kind != "auth" or server.get("auth_method") != "oauth":
                    raise
                payload = self._retry_oauth_tool_call(
                    server=server,
                    remote_name=tool["remote_name"],
                    arguments=arguments,
                    input_schema=tool.get("input_schema"),
                    execution_id=execution["id"],
                )
            # Invalidate persisted connection status on fatal transport/auth errors.
            if payload.get("error_kind") in {"auth", "transport"} and "session" in str(payload.get("error") or "").lower():
                self.store.update_server_status(
                    server["id"],
                    connection_status="error",
                    last_error=str(payload.get("error") or "transport error"),
                    last_error_kind=payload.get("error_kind"),
                )
            # Re-check cancel after return
            latest = None
            for item in self.store.list_executions(server_id=server["id"], limit=20):
                if item["id"] == execution["id"]:
                    latest = item
                    break
            if latest and latest.get("cancel_requested"):
                finished = self.store.finish_execution(
                    execution["id"],
                    status="cancelled",
                    result=redact_mapping(payload),
                    error_kind="cancelled",
                )
                self.store.mark_tool_execution(tool["id"], "cancelled")
                return {"execution": finished, "result": payload, "via": "direct", "error_kind": "cancelled"}
            is_error = bool(payload.get("isError"))
            error_kind = payload.get("error_kind") or ("tool_error" if is_error else None)
            if payload.get("timeout"):
                error_kind = "unknown_outcome"
            status = "failed" if is_error else "completed"
            finished = self.store.finish_execution(
                execution["id"],
                status=status,
                result=redact_mapping(payload),
                error_kind=error_kind,
            )
            self.store.mark_tool_execution(tool["id"], status)
            # Also persist a platform tool_call for unified history when possible.
            call_id = None
            try:
                call_id = self.platform_db.create_tool_call(
                    f"mcp:{server['id']}",
                    tool["model_name"],
                    arguments,
                    invocation_type=invocation_type,
                    approved_by_user=approved_by_user,
                    metadata={"mcp_managed": True, "mcp_tool": tool["remote_name"], "error_kind": error_kind},
                )
                duration = (time.perf_counter() - started) * 1000.0
                known_secrets = self._known_secrets_for_server(server)
                safe_payload = redact_mapping(payload, known_secrets=known_secrets)
                self.platform_db.finish_tool_call(
                    call_id,
                    status,
                    stdout=str(safe_payload.get("stderr_tail") or "") if server.get("transport") == "stdio" else "",
                    stderr="",
                    exit_code=None if server.get("transport") == "streamable_http" else (1 if is_error else 0),
                    error=str(payload.get("error") or "") if is_error else None,
                    duration_ms=int(duration),
                    output=json.dumps(safe_payload, ensure_ascii=False)[:100_000],
                    metadata={"error_kind": error_kind, "transport": server.get("transport")},
                )
            except Exception:
                call_id = None
            return {"execution": finished, "result": payload, "via": "direct", "tool_call_id": call_id, "error_kind": error_kind}
        except McpClientError as exc:
            finished = self.store.finish_execution(
                execution["id"],
                status="cancelled" if exc.kind == "cancelled" else "failed",
                result={"error": str(exc), "error_kind": exc.kind},
                error_kind=exc.kind,
            )
            self.store.mark_tool_execution(tool["id"], finished["status"] if finished else "failed")
            return {"execution": finished, "result": {"error": str(exc), "isError": True}, "via": "direct", "error_kind": exc.kind}
        finally:
            self._active_executions.pop(execution["id"], None)

    def _known_secrets_for_server(self, server: dict[str, Any]) -> list[str]:
        secrets: list[str] = []
        try:
            token = secret_store.get(server.get("auth_secret_ref"))
            if token:
                secrets.append(token)
        except SecretStorageUnavailable:
            pass
        for ref in (((server.get("env") or {}).get("secret_refs")) or {}).values():
            try:
                value = secret_store.get(ref)
                if value:
                    secrets.append(value)
            except SecretStorageUnavailable:
                continue
        meta = server.get("metadata") if isinstance(server.get("metadata"), dict) else {}
        for key in ("oauth_refresh_ref", "oauth_access_ref"):
            try:
                value = secret_store.get(meta.get(key))
                if value:
                    secrets.append(value)
            except SecretStorageUnavailable:
                continue
        return secrets

    def cancel_execution(self, execution_id: str) -> dict[str, Any]:
        execution = self.store.request_cancel(execution_id)
        if not execution:
            raise KeyError(execution_id)
        server_id = execution["server_id"]
        with self._session_lock:
            client = self._sessions.get(server_id)
        if client is not None:
            try:
                # Request/execution-scoped cancel — never destroy unrelated waiters.
                if hasattr(client, "cancel_execution"):
                    client.cancel_execution(execution_id)
                elif hasattr(client, "cancel_request"):
                    pass
            except Exception:
                pass
        return execution

    def call_managed_tool(
        self,
        server_id: str,
        remote_name: str,
        arguments: dict[str, Any],
        *,
        invocation_type: str = "autonomous",
        approved_by_user: bool = False,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        """Called from PluginManager hook for mirrored tools."""
        tool_id = stable_tool_id(server_id, remote_name)
        tool = self.store.get_tool(tool_id)
        if not tool:
            raise KeyError(tool_id)
        # Re-check permissions immediately before execution (revocation race).
        self.assert_tool_authorization(
            tool,
            invocation_type=invocation_type,
            approved_by_user=approved_by_user,
            approval_id=approval_id,
        )
        server = self.store.get_server(server_id)
        if not server:
            raise KeyError(server_id)
        if not server.get("enabled"):
            raise PermissionError("Server is uitgeschakeld")
        try:
            arguments = validate_tool_arguments(tool.get("input_schema"), arguments)
        except ValueError as exc:
            raise McpClientError(str(exc), kind="validation") from exc
        self._consume_mcp_tool_budget(scope_key=f"{invocation_type}:{server_id}")
        with self._session_lock:
            client = self._sessions.get(server_id)
        if client is None or not getattr(client, "alive", False):
            raise McpClientError("MCP-sessie niet verbonden", kind="transport")
        try:
            return client.call_tool(
                remote_name,
                arguments,
                input_schema=tool.get("input_schema"),
            )
        except McpClientError as exc:
            if exc.kind != "auth" or server.get("auth_method") != "oauth":
                raise
            return self._retry_oauth_tool_call(
                server=server,
                remote_name=remote_name,
                arguments=arguments,
                input_schema=tool.get("input_schema"),
            )

    def _retry_oauth_tool_call(
        self,
        *,
        server: dict[str, Any],
        remote_name: str,
        arguments: dict[str, Any],
        input_schema: dict[str, Any] | None,
        execution_id: str | None = None,
    ) -> dict[str, Any]:
        """Retry a tool call once after a proven HTTP 401 auth rejection."""
        server_id = str(server["id"])
        self._maybe_refresh_oauth(server)
        server = self.store.get_server(server_id) or server
        token = secret_store.get(server.get("auth_secret_ref"))
        if not token:
            self.store.update_server_status(server_id, auth_status="required", connection_status="auth_required")
            raise McpClientError("OAuth refresh failed — reauthorization required", kind="auth")
        with self._session_lock:
            old = self._sessions.get(server_id)
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        # Internal rebuild: do not re-prompt network ask for an already-approved live session.
        client = self._build_client(server, approval_id=None, internal_rebuild=True)
        if old is not None:
            client.protocol_version = getattr(old, "protocol_version", client.protocol_version)
            client.protocol_generation = getattr(old, "protocol_generation", client.protocol_generation)
            if hasattr(client, "session_id"):
                client.session_id = getattr(old, "session_id", None)
        with self._session_lock:
            self._sessions[server_id] = client
        return client.call_tool(
            remote_name,
            arguments if isinstance(arguments, dict) else {},
            execution_id=execution_id,
            input_schema=input_schema,
        )

    def auth_status(self, server_id: str, *, discover: bool = False, approval_id: str | None = None) -> dict[str, Any]:
        server = self.store.get_server(server_id)
        if not server:
            raise KeyError(server_id)
        has_secret = False
        try:
            has_secret = bool(secret_store.get(server.get("auth_secret_ref")))
        except SecretStorageUnavailable:
            has_secret = False
        discovery = None
        if discover and server.get("transport") == "streamable_http" and server.get("endpoint_url"):
            settings = self._settings()
            try:
                approved = self._policy_approved(server, effect="mcp_oauth_discovery", approval_id=approval_id)
                require_network_policy(
                    settings,
                    endpoint_url=str(server["endpoint_url"]),
                    approved=approved,
                    purpose="mcp_oauth_discovery",
                )
                discovery = discover_auth(str(server["endpoint_url"]))
            except McpPolicyError as exc:
                approval = None
                if exc.approval_required:
                    approval = self._ensure_policy_approval(server, effect=exc.effect or "mcp_oauth_discovery")
                discovery = {
                    "ok": False,
                    "error": str(exc),
                    "policy_blocked": True,
                    "approval_required": bool(exc.approval_required),
                    "approval": approval,
                }
        return {
            "server_id": server_id,
            "auth_method": server.get("auth_method"),
            "auth_status": server.get("auth_status"),
            "has_secret": has_secret,
            "secret_storage": secret_store.available(),
            "oauth_discovery": discovery,
            "discovery_performed": bool(discover),
        }

    def start_oauth(
        self,
        server_id: str,
        *,
        redirect_uri: str,
        ui_return_url: str | None = None,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        server = self.store.get_server(server_id)
        if not server:
            raise KeyError(server_id)
        if server.get("transport") != "streamable_http":
            raise ValueError("OAuth is alleen voor Streamable HTTP-servers")
        meta = server.get("metadata") if isinstance(server.get("metadata"), dict) else {}
        client_id = str(meta.get("oauth_client_id") or "").strip() or None
        client_metadata_url = str(meta.get("oauth_client_metadata_url") or "").strip() or None
        # Scoped network approval for OAuth start.
        if not self._policy_approved(server, effect="mcp_oauth_start", approval_id=approval_id):
            settings = self._settings()
            try:
                require_network_policy(
                    settings,
                    endpoint_url=str(server.get("endpoint_url") or ""),
                    approved=False,
                    purpose="mcp_oauth_start",
                )
            except McpPolicyError as exc:
                if exc.approval_required:
                    approval = self._ensure_policy_approval(server, effect="mcp_oauth_start")
                    raise McpPolicyError(
                        str(exc),
                        kind=exc.kind,
                        approval_required=True,
                        approval=approval,
                        effect="mcp_oauth_start",
                    ) from exc
                raise
        result = start_oauth_flow(
            server_id=server_id,
            endpoint_url=str(server.get("endpoint_url")),
            redirect_uri=redirect_uri,
            client_id=client_id,
            client_metadata_url=client_metadata_url,
            settings=self._settings(),
            ui_return_url=ui_return_url,
        )
        if result.get("ok"):
            self.store.update_server_status(server_id, auth_status="required", connection_status="auth_required")
        return result

    def _discard_oauth_result_secrets(self, result: dict[str, Any]) -> None:
        """Delete newly stored token refs when completion cannot bind them to a server."""
        for key in ("auth_secret_ref", "refresh_secret_ref"):
            ref = result.get(key)
            if ref:
                try:
                    secret_store.delete(ref, missing_ok=True)
                except Exception:
                    pass

    def complete_oauth(self, *, state: str, code: str, iss: str | None = None) -> dict[str, Any]:
        result = complete_oauth_flow(state=state, code=code, iss=iss)
        if not result.get("ok"):
            return result
        server_id = result["server_id"]
        server = self.store.get_server(server_id)
        if not server:
            self._discard_oauth_result_secrets(result)
            return {"ok": False, "error": "OAuth server verdwenen vóór token-binding", "ui_return_url": result.get("ui_return_url")}
        # Bind completion to the pending resource/server — reject cross-server reuse.
        pending_endpoint = str(result.get("endpoint_url") or "").strip()
        if pending_endpoint and str(server.get("endpoint_url") or "").strip() != pending_endpoint:
            self._discard_oauth_result_secrets(result)
            return {
                "ok": False,
                "error": "OAuth state is bound to a different MCP endpoint",
                "ui_return_url": result.get("ui_return_url"),
            }
        env = server.get("env") or {}
        old_access = server.get("auth_secret_ref")
        old_refresh = (server.get("metadata") or {}).get("oauth_refresh_ref")
        server["auth_secret_ref"] = result["auth_secret_ref"]
        server["auth_method"] = "oauth"
        server["auth_status"] = "ok"
        server["env"] = {"plain": env.get("plain") or {}, "secret_refs": env.get("secret_refs") or {}}
        meta = dict(server.get("metadata") or {})
        if result.get("refresh_secret_ref"):
            meta["oauth_refresh_ref"] = result["refresh_secret_ref"]
        if result.get("issuer"):
            meta["oauth_issuer"] = result["issuer"]
        if result.get("client_id"):
            meta["oauth_client_id"] = result["client_id"]
        if result.get("expires_at") is not None:
            meta["oauth_expires_at"] = result["expires_at"]
        if result.get("resource"):
            meta["oauth_resource"] = result["resource"]
        if result.get("token_endpoint"):
            meta["oauth_token_endpoint"] = result["token_endpoint"]
        server["metadata"] = meta
        self.store.upsert_server(server)
        if old_access and old_access != result["auth_secret_ref"]:
            secret_store.delete(old_access, missing_ok=True)
        if old_refresh and old_refresh != result.get("refresh_secret_ref"):
            secret_store.delete(old_refresh, missing_ok=True)
        self.store.update_server_status(server_id, auth_status="ok", connection_status="configured", clear_error=True)
        return {"ok": True, "server": self.get_server(server_id), "ui_return_url": result.get("ui_return_url")}

    def cancel_oauth(self, state: str) -> dict[str, Any]:
        return {"ok": cancel_oauth_flow(state)}

    # --- Plugin reconciliation / mirror --------------------------------

    def reconcile_plugin_servers(self) -> None:
        """Mark existing MCP plugins as plugin-owned servers (no second process)."""
        try:
            plugins = self.platform_db.list_plugins()
        except Exception:
            return
        for plugin in plugins:
            pid = str(plugin.get("id") or "")
            labels = plugin.get("labels") or []
            runtime = str(plugin.get("runtime_type") or plugin.get("runtime") or "")
            meta = plugin.get("metadata") if isinstance(plugin.get("metadata"), dict) else {}
            is_mcp = (
                "mcp" in runtime.lower()
                or any("mcp" in str(x).lower() for x in labels)
                or "mcp" in str(meta).lower()
                or pid.endswith("-mcp")
                or "mcp" in pid
            )
            tools = plugin.get("tools") or self.platform_db.plugin_tools(pid)
            has_wrappers = any(isinstance(t, dict) and t.get("name") in {"list_tools", "call_tool"} for t in tools)
            if not is_mcp and not has_wrappers:
                continue
            existing = self.store.get_server_by_plugin(pid)
            catalog_id = None
            for item in catalog_items():
                if item.get("plugin_id") == pid:
                    catalog_id = item["id"]
                    break
            status = "connected" if str(plugin.get("status") or "").lower() == "ready" and plugin.get("enabled") else "configured"
            if not plugin.get("enabled"):
                status = "disabled"
            payload = {
                "id": (existing or {}).get("id") or f"plugin-{pid}",
                "name": str(plugin.get("name") or pid),
                "description": str(plugin.get("description") or "Plugin-beheerde MCP-server"),
                "transport": "stdio",
                "enabled": bool(plugin.get("enabled")),
                "auto_connect": False,
                "owner_kind": "plugin",
                "owner_plugin_id": pid,
                "catalog_id": catalog_id,
                "command": {"executable": "plugin-managed", "args": [], "cwd": None},
                "env": {"plain": {}, "secret_refs": {}},
                "auth_method": "none",
                "timeout_seconds": 90,
                "connection_status": (existing or {}).get("connection_status") or status,
                "metadata": {"plugin_managed": True, "do_not_start_second_process": True},
            }
            # Never invent connected without expand — on first see use configured unless already tracked connected with tools.
            if not existing:
                payload["connection_status"] = "configured" if plugin.get("enabled") else "disabled"
            self.store.upsert_server(payload)

    def _mirror_to_plugin(self, server_id: str) -> dict[str, Any]:
        server = self.store.get_server(server_id)
        if not server or server.get("owner_kind") == "plugin":
            return {"skipped": True}
        plugin_id = f"mcp:{server_id}"
        tools = self.store.list_tools(server_id)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        # Treat modern "ready" the same as legacy connected for mirror enablement.
        connected = server.get("connection_status") in {"connected", "ready"}
        with self._session_lock:
            live = bool(self._sessions.get(server_id) and getattr(self._sessions[server_id], "alive", False))
        ready = bool(server.get("enabled") and connected and live)
        chatbot_tools = [t for t in tools if t.get("chatbot_enabled") and t.get("allowed")]
        manifest = {
            "id": plugin_id,
            "name": server.get("name"),
            "description": server.get("description"),
            "plugin_type": "mcp-managed",
            "runtime_type": "mcp",
            "category": "MCP",
            "labels": ["mcp", "managed"],
            "autonomous": bool(chatbot_tools),
            "mcp": {"expand_tools": False, "transport": server.get("transport"), "managed": True},
            "permissions": ["subprocess", "network"] if server.get("transport") == "stdio" else ["network"],
        }
        data_root = getattr(self.platform_db, "path", None)
        local_path = str(Path(data_root).parent / "mcp_managed" / server_id) if data_root else f"mcp_managed/{server_id}"
        try:
            Path(local_path).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        plugin_row = {
            "id": plugin_id,
            "name": server.get("name"),
            "version": "1.0.0",
            "description": server.get("description") or "",
            "plugin_type": "mcp-managed",
            "runtime_type": "mcp",
            "enabled": bool(server.get("enabled") and ready),
            "status": "ready" if ready else "preparing",
            "trust": "verified" if chatbot_tools else "manual",
            "health": "healthy" if ready else "unknown",
            "manifest": manifest,
            "permissions": manifest.get("permissions") or [],
            "source": "mcp_host",
            "local_path": local_path,
            "entrypoint": "",
            "failure_state": None,
            "metadata": {"mcp_managed": True, "mcp_server_id": server_id},
            "updated_at": now,
        }
        try:
            existing = self.platform_db.get_plugin(plugin_id)
            if existing:
                merged = {**existing, **plugin_row, "manifest": manifest, "local_path": existing.get("local_path") or local_path}
                self.platform_db.save_plugin(merged)
            else:
                self.platform_db.save_plugin({**plugin_row, "created_at": now})
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        tool_rows = []
        for tool in tools:
            chatbot = bool(tool.get("chatbot_enabled") and tool.get("allowed"))
            enabled = bool(tool.get("allowed"))  # blocked tools stay disabled in registry
            tool_rows.append(
                {
                    "name": tool["model_name"],
                    "description": tool.get("description") or tool["remote_name"],
                    "input_schema": tool.get("input_schema") or {"type": "object", "properties": {}},
                    "output_schema": tool.get("output_schema") or {},
                    "command": [],  # executed via manager hook
                    "action": "mcp_call",
                    "mode": "mcp_managed",
                    "enabled": enabled,
                    "autonomous": chatbot,
                    "mcp": True,
                    "mcp_managed": True,
                    "mcp_remote": True,
                    "mcp_server_id": server_id,
                    "mcp_tool": tool["remote_name"],
                    "mcp_tool_id": tool["id"],
                    "require_approval": bool(tool.get("require_approval")),
                    "capabilities": {
                        "effects": ["mcp", "network"] + (["subprocess"] if server.get("transport") == "stdio" else []),
                        "side_effect_class": "process",
                        "cost_class": "moderate",
                        "latency_class": "normal",
                        "failure_modes": ["timeout", "network", "schema"],
                    },
                }
            )
        try:
            self.platform_db.replace_plugin_tools(plugin_id, tool_rows)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "plugin_id": plugin_id, "tools": len(tool_rows)}

    def _mirror_plugin_state(self, server: dict[str, Any]) -> None:
        if server.get("owner_kind") == "plugin":
            return
        self._mirror_to_plugin(server["id"])

    def _remove_mirror_plugin(self, server_id: str) -> None:
        plugin_id = f"mcp:{server_id}"
        try:
            if hasattr(self.platform_db, "delete_plugin"):
                self.platform_db.delete_plugin(plugin_id)
            elif hasattr(self.platform_db, "uninstall_plugin"):
                self.platform_db.uninstall_plugin(plugin_id)
        except Exception:
            pass

    # --- Lifecycle ------------------------------------------------------

    def on_startup(self) -> dict[str, Any]:
        """Restore config; do not blindly restore connected; auto-connect when allowed."""
        self.reconcile_plugin_servers()
        notes: list[str] = []
        for server in self.store.list_servers():
            if server.get("owner_kind") == "plugin":
                # Reset ephemeral connected claim until expand proves it.
                if server.get("connection_status") == "connected":
                    self.store.update_server_status(server["id"], connection_status="configured")
                    notes.append(f"reset_plugin_status:{server['id']}")
                continue
            # Clear stale connected flags — require handshake again.
            if server.get("connection_status") in {"connected", "connecting"}:
                self.store.update_server_status(server["id"], connection_status="disconnected" if server.get("enabled") else "disabled")
                notes.append(f"reset_status:{server['id']}")
            if server.get("auto_connect") and server.get("enabled") and self._mcp_enabled():
                try:
                    self.connect(server["id"])
                    notes.append(f"auto_connected:{server['id']}")
                except Exception as exc:
                    notes.append(f"auto_connect_failed:{server['id']}:{exc}")
        return {"ok": True, "notes": notes}

    def on_shutdown(self) -> None:
        with self._session_lock:
            ids = list(self._sessions.keys())
        for server_id in ids:
            self._close_session(server_id)

    def export_config(self) -> dict[str, Any]:
        return {"servers": self.store.export_servers(), "secret_storage": secret_store.available()}

    def import_config(self, payload: dict[str, Any], *, connect: bool = False) -> dict[str, Any]:
        servers = payload.get("servers") if isinstance(payload, dict) else None
        if not isinstance(servers, list):
            raise ValueError("import vereist servers[]")
        created = []
        for item in servers:
            if not isinstance(item, dict):
                continue
            body = dict(item)
            body.pop("auth_secret_ref", None)
            body["auto_connect"] = False if not connect else body.get("auto_connect", False)
            body["connection_status"] = "configured"
            # Import never starts processes unless connect=True explicitly and auto_connect set.
            server = self.create_server(body)
            created.append(server["id"])
        return {"ok": True, "imported": created}
