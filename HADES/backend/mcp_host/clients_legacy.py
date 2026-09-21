"""MCP transport clients: long-lived stdio + Streamable HTTP.

Implements an explicit protocol-generation boundary:
- modern (2026-07-28): server/discover, per-request _meta, Mcp-Method/Mcp-Name,
  no initialize/session.
- legacy (2025-11-25 and earlier supported revisions): initialize handshake and
  optional Mcp-Session-Id.

Cancellation is request-scoped. Closing the client may cancel all outstanding
local waiters; cancelling one execution must not poison future requests.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from typing import Any
from urllib.parse import urlparse

import httpx

from mcp_host.errors import (
    McpJsonRpcError,
    McpProtocolError,
    classify_http_probe_failure,
    parse_jsonrpc_error_body,
)
from mcp_host.param_headers import McpParamError, build_mcp_param_headers, filter_tools_for_http_headers
from mcp_host.protocol import (
    CLIENT_INFO,
    DEFAULT_PROTOCOL_VERSION,
    LEGACY_PROTOCOL_VERSIONS,
    MAX_PAYLOAD_BYTES,
    MAX_SSE_BYTES,
    MAX_TOOL_LIST_PAGES,
    MODERN_PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    connection_status_for_generation,
    discovery_cursor_loop,
    finite_timeout,
    is_modern_protocol,
    json_size_ok,
    mcp_http_headers,
    mcp_name_from_params,
    parse_discover_supported_versions,
    protocol_generation,
    select_mutually_supported_version,
    stamp_params,
    validate_modern_discover_result,
)
from url_security import UrlSecurityError, assert_public_http_url, redirect_location, safe_public_url


class McpClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        kind: str = "transport",
        rpc: McpJsonRpcError | None = None,
        http_status: int | None = None,
        legacy_evidence: bool = False,
        auth_challenge: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.rpc = rpc
        self.http_status = http_status if http_status is not None else (rpc.http_status if rpc else None)
        self.legacy_evidence = legacy_evidence
        self.auth_challenge = auth_challenge or {}


def resolve_command(raw: list[str]) -> list[str]:
    if not raw:
        raise McpClientError("MCP command is empty", kind="validation")
    first = raw[0]
    if first in {"npx", "npm", "node", "python", "python3"}:
        resolved = shutil.which(first) or shutil.which(first + ".cmd")
        if not resolved and first.startswith("python"):
            resolved = sys.executable
        if not resolved:
            raise McpClientError(f"command not found on PATH: {first}", kind="dependency")
        return [resolved, *raw[1:]]
    if os.path.sep in first or (os.name == "nt" and "\\" in first):
        return list(raw)
    resolved = shutil.which(first) or shutil.which(first + ".cmd")
    if not resolved:
        raise McpClientError(f"command not found on PATH: {first}", kind="dependency")
    return [resolved, *raw[1:]]


def _terminate_process_tree(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            # Process group created with CREATE_NEW_PROCESS_GROUP.
            proc.terminate()
        else:
            try:
                os.killpg(proc.pid, 15)  # SIGTERM
            except (ProcessLookupError, PermissionError, AttributeError):
                proc.terminate()
    except OSError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            if os.name != "nt":
                try:
                    os.killpg(proc.pid, 9)
                except (ProcessLookupError, PermissionError, AttributeError):
                    proc.kill()
            else:
                proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=3)
        except Exception:
            pass


def _is_explicit_loopback_host(host: str) -> bool:
    """Allow MCP private-mode only for explicit loopback, never arbitrary RFC1918/link-local hosts."""
    normalized = (host or "").lower().strip("[]")
    return normalized in {"localhost", "127.0.0.1", "::1"}


def _url_origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower().strip("[]")
    port = parsed.port
    if port is None:
        port = 80 if scheme == "http" else 443 if scheme == "https" else None
    return scheme, host, port


class StdioMcpClient:
    """Long-lived stdio MCP session (lives in the HADES backend process)."""

    transport = "stdio"

    def __init__(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout: float = 60.0,
        known_secrets: list[str] | None = None,
    ) -> None:
        if not command:
            raise McpClientError("MCP command is empty", kind="validation")
        self.timeout = finite_timeout(timeout)
        self._id = 0
        self.protocol_version = DEFAULT_PROTOCOL_VERSION
        self.protocol_generation = protocol_generation(self.protocol_version)
        self.notifications: deque[dict[str, Any]] = deque(maxlen=200)
        self._pending: dict[Any, dict[str, Any] | None] = {}
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._closed = False
        self._cancel_flags: dict[Any, threading.Event] = {}
        self._execution_requests: dict[str, Any] = {}  # execution_id -> req_id
        self._known_secrets = [s for s in (known_secrets or []) if s]
        self._raw_command = list(command)
        self._env = {str(k): str(v) for k, v in (env or {}).items()}
        self._cwd = cwd
        self._creationflags = 0
        self._preexec_fn = None
        if os.name == "nt":
            self._creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            self._preexec_fn = os.setsid
        self._merged_env = os.environ.copy()
        self._merged_env.update(self._env)
        self.command = resolve_command(self._raw_command)
        self._stderr_chunks: list[str] = []
        self.proc: subprocess.Popen[Any]
        self._stderr_thread: threading.Thread
        self._reader_thread: threading.Thread
        self._spawn_process()

    def _spawn_process(self) -> None:
        self.proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=False,
            env=self._merged_env,
            cwd=self._cwd or None,
            creationflags=self._creationflags,
            preexec_fn=self._preexec_fn,
        )
        self._stderr_chunks = []
        self._stderr_thread = threading.Thread(target=self._pump_stderr, daemon=True)
        self._stderr_thread.start()
        self._reader_thread = threading.Thread(target=self._pump_stdout, daemon=True)
        self._reader_thread.start()

    def _restart_process(self) -> None:
        """Restart the child after a poisoned modern probe (legacy servers may exit)."""
        self._closed = True
        try:
            _terminate_process_tree(self.proc)
        except Exception:
            pass
        with self._lock:
            self._pending.clear()
            self._cancel_flags.clear()
            self._execution_requests.clear()
            self._id = 0
        self._closed = False
        self._spawn_process()

    def _redact_text(self, text: str) -> str:
        out = text
        for secret in self._known_secrets:
            if secret:
                out = out.replace(secret, "***")
        return out

    def stderr_tail(self, limit: int = 2000) -> str:
        return self._redact_text("".join(self._stderr_chunks)[-limit:])

    def _pump_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self._stderr_chunks.append(line)
            if sum(len(chunk) for chunk in self._stderr_chunks) > 200_000:
                self._stderr_chunks = self._stderr_chunks[-50:]

    def _pump_stdout(self) -> None:
        assert self.proc.stdout is not None
        while not self._closed:
            line = self.proc.stdout.readline()
            if line == "":
                if self.proc.poll() is not None:
                    break
                time.sleep(0.01)
                continue
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                with self._lock:
                    self.notifications.append({"method": "hades/invalid_json", "params": {"raw": line[:2000]}})
                continue
            if not isinstance(message, dict):
                continue
            msg_id = message.get("id")
            # Server→client request (method + id): answer with method-not-found for
            # unsupported features; do not silently drop when a response is expected.
            if "method" in message and msg_id is not None and "result" not in message and "error" not in message:
                self._handle_server_request(message)
                continue
            if "method" in message and msg_id is None:
                with self._lock:
                    self.notifications.append(message)
                continue
            if msg_id is not None:
                with self._lock:
                    if msg_id in self._pending:
                        self._pending[msg_id] = message
                    else:
                        self.notifications.append({"method": "hades/orphan_response", "params": message})

    def _handle_server_request(self, message: dict[str, Any]) -> None:
        """Legacy bidirectional requests HADES does not support."""
        if is_modern_protocol(self.protocol_version):
            # 2026: servers must not send JSON-RPC requests; ignore defensively.
            with self._lock:
                self.notifications.append({"method": "hades/unexpected_server_request", "params": message})
            return
        req_id = message.get("id")
        method = str(message.get("method") or "")
        error = {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32601,
                "message": f"Method not supported by HADES MCP host: {method}",
            },
        }
        try:
            self._write_message(error)
        except Exception:
            with self._lock:
                self.notifications.append({"method": "hades/server_request_unanswered", "params": message})

    def _write_message(self, payload: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        if not json_size_ok(payload):
            raise McpClientError("MCP request exceeds MAX_PAYLOAD_BYTES", kind="validation")
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        with self._write_lock:
            self.proc.stdin.write(line)
            self.proc.stdin.flush()

    def _next_id(self) -> int:
        with self._lock:
            self._id += 1
            return self._id

    @property
    def alive(self) -> bool:
        return not self._closed and self.proc.poll() is None

    def bind_execution(self, execution_id: str, req_id: Any) -> None:
        with self._lock:
            self._execution_requests[execution_id] = req_id

    def unbind_execution(self, execution_id: str) -> None:
        with self._lock:
            self._execution_requests.pop(execution_id, None)

    def cancel_execution(self, execution_id: str) -> bool:
        with self._lock:
            req_id = self._execution_requests.get(execution_id)
        if req_id is None:
            return False
        return self.cancel_request(req_id)

    def cancel_request(self, req_id: Any) -> bool:
        with self._lock:
            flag = self._cancel_flags.get(req_id)
            if flag is None:
                return False
            flag.set()
        # Best-effort wire cancel for legacy/stdio revisions that support it.
        try:
            self.notify("notifications/cancelled", {"requestId": req_id, "reason": "user cancelled"})
        except Exception:
            pass
        return True

    def cancel_pending(self, req_id: Any | None = None) -> None:
        """Cancel one request, or all outstanding waiters (used on close)."""
        with self._lock:
            if req_id is not None:
                flag = self._cancel_flags.get(req_id)
                if flag is not None:
                    flag.set()
                return
            for flag in self._cancel_flags.values():
                flag.set()

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        execution_id: str | None = None,
    ) -> dict[str, Any]:
        if self.proc.poll() is not None:
            err = self.stderr_tail(4000)
            raise McpClientError(f"MCP server exited early ({self.proc.returncode}): {err}", kind="transport")
        req_id = self._next_id()
        stamped = stamp_params(params, protocol_version=self.protocol_version)
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if stamped:
            payload["params"] = stamped
        cancel_flag = threading.Event()
        with self._lock:
            self._pending[req_id] = None
            self._cancel_flags[req_id] = cancel_flag
            if execution_id:
                self._execution_requests[execution_id] = req_id
        try:
            self._write_message(payload)
        except Exception as exc:
            with self._lock:
                self._pending.pop(req_id, None)
                self._cancel_flags.pop(req_id, None)
                if execution_id:
                    self._execution_requests.pop(execution_id, None)
            raise McpClientError(f"Kon MCP-request niet schrijven: {exc}", kind="transport") from exc

        deadline = time.monotonic() + self.timeout
        try:
            while time.monotonic() < deadline:
                if cancel_flag.is_set():
                    raise McpClientError(f"MCP request cancelled: {method}", kind="cancelled")
                if self.proc.poll() is not None:
                    err = self.stderr_tail(4000)
                    raise McpClientError(f"MCP server exited during {method}: {err}", kind="transport")
                with self._lock:
                    message = self._pending.get(req_id)
                if message is not None:
                    if "error" in message:
                        rpc = parse_jsonrpc_error_body(message)
                        raise McpClientError(
                            json.dumps(message["error"], ensure_ascii=False),
                            kind="protocol",
                            rpc=rpc,
                        )
                    result = message.get("result", {})
                    return result if isinstance(result, dict) else {"value": result}
                time.sleep(0.02)
            raise McpClientError(f"Timed out waiting for MCP response to {method} (id={req_id})", kind="timeout")
        finally:
            with self._lock:
                self._pending.pop(req_id, None)
                self._cancel_flags.pop(req_id, None)
                if execution_id:
                    self._execution_requests.pop(execution_id, None)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        stamped = stamp_params(params, protocol_version=self.protocol_version)
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if stamped:
            payload["params"] = stamped
        self._write_message(payload)

    def _negotiate_legacy(self) -> dict[str, Any]:
        last_error: Exception | None = None
        for version in [v for v in SUPPORTED_PROTOCOL_VERSIONS if v in LEGACY_PROTOCOL_VERSIONS]:
            try:
                result = self.request(
                    "initialize",
                    {
                        "protocolVersion": version,
                        "capabilities": {},
                        "clientInfo": dict(CLIENT_INFO),
                    },
                )
                negotiated = str(result.get("protocolVersion") or version)
                if negotiated not in SUPPORTED_PROTOCOL_VERSIONS or is_modern_protocol(negotiated):
                    raise McpClientError(
                        f"Unsupported legacy MCP protocol version negotiated: {negotiated}",
                        kind="protocol",
                    )
                self.protocol_version = negotiated
                self.protocol_generation = "legacy"
                self.notify("notifications/initialized", {})
                return result
            except McpClientError as exc:
                last_error = exc
                if exc.kind in {"timeout", "cancelled"}:
                    raise
                continue
            except Exception as exc:
                last_error = exc
                continue
        raise McpClientError(f"MCP initialize mislukt voor ondersteunde legacy-versies: {last_error}", kind="protocol")

    def _apply_modern_discover(self, discovered: dict[str, Any]) -> dict[str, Any]:
        parsed = parse_discover_supported_versions(discovered)
        if parsed["source"] == "malformed":
            raise McpClientError("Malformed server/discover supportedVersions", kind="protocol")
        if parsed["source"] == "missing" or not parsed["supported"]:
            raise McpClientError("server/discover missing supportedVersions", kind="protocol")
        chosen = select_mutually_supported_version(parsed["supported"])
        if chosen is None:
            raise McpClientError(
                f"No mutually supported MCP protocol version in {parsed['supported']}",
                kind="protocol",
            )
        if is_modern_protocol(chosen):
            validation = validate_modern_discover_result(discovered)
            if parsed["source"] == "supportedVersions" and not validation["ok"]:
                raise McpClientError(
                    "Malformed modern DiscoverResult: " + ", ".join(validation["issues"] or ["invalid"]),
                    kind="protocol",
                )
            self.protocol_version = MODERN_PROTOCOL_VERSION
            self.protocol_generation = "modern"
            return discovered
        # Server advertised only legacy revisions — fall back without inventing modern.
        return self._negotiate_legacy_after_probe()

    def _negotiate_legacy_after_probe(self) -> dict[str, Any]:
        if not self.alive:
            self._restart_process()
        return self._negotiate_legacy()

    def _negotiate_modern(self) -> dict[str, Any]:
        # Spec (stdio): probe server/discover; fall back on any error that is not a
        # recognized modern error. Process exit / timeout are legacy evidence.
        self.protocol_version = MODERN_PROTOCOL_VERSION
        self.protocol_generation = "modern"
        probe_timeout = min(self.timeout, 8.0)
        previous_timeout = self.timeout
        self.timeout = probe_timeout
        try:
            discovered = self.request("server/discover", {})
        except McpClientError as exc:
            self.timeout = previous_timeout
            rpc = exc.rpc
            if rpc is not None and rpc.is_recognized_modern_error:
                if rpc.is_unsupported_protocol_version:
                    supported = rpc.supported_versions()
                    chosen = select_mutually_supported_version(supported)
                    if chosen is None:
                        raise McpClientError(
                            f"UnsupportedProtocolVersion with no mutually supported revision: {supported}",
                            kind="protocol",
                            rpc=rpc,
                        ) from exc
                    if is_modern_protocol(chosen):
                        # Retry discover is unnecessary; stay modern with negotiated version.
                        self.protocol_version = chosen
                        self.protocol_generation = "modern"
                        return {"supportedVersions": supported, "negotiated": chosen, "from_error": True}
                    return self._negotiate_legacy_after_probe()
                # HeaderMismatch / MissingRequiredClientCapability are protocol bugs, not legacy.
                raise
            if exc.kind == "cancelled":
                raise
            # Process exit, timeout, method-not-found, or other non-modern errors → legacy.
            if not self.alive or exc.kind in {"timeout", "transport"} or (rpc and rpc.is_method_not_found) or exc.legacy_evidence:
                return self._negotiate_legacy_after_probe()
            if rpc is None or rpc.is_method_not_found:
                return self._negotiate_legacy_after_probe()
            raise
        finally:
            self.timeout = previous_timeout
        return self._apply_modern_discover(discovered if isinstance(discovered, dict) else {})

    def initialize(self) -> dict[str, Any]:
        """Verify protocol. Prefers 2026 discover; falls back to legacy initialize."""
        return self._negotiate_modern()

    def list_tools_all(self) -> dict[str, Any]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        pages = 0
        complete = True
        notes: list[str] = []
        cache_hints: dict[str, Any] = {}
        while pages < MAX_TOOL_LIST_PAGES:
            pages += 1
            params: dict[str, Any] = {}
            if cursor:
                params["cursor"] = cursor
            result = self.request("tools/list", params)
            if "ttlMs" in result or "cacheScope" in result:
                cache_hints = {"ttlMs": result.get("ttlMs"), "cacheScope": result.get("cacheScope")}
            batch = result.get("tools") or []
            if isinstance(batch, list):
                tools.extend([item for item in batch if isinstance(item, dict)])
            next_cursor = result.get("nextCursor") or result.get("next_cursor")
            if not next_cursor:
                break
            cursor = str(next_cursor)
            if discovery_cursor_loop(seen_cursors, cursor):
                complete = False
                notes.append("repeated_cursor")
                break
        else:
            complete = False
            notes.append("page_limit_reached")
        with self._lock:
            notifications = list(self.notifications)
        return {
            "tools": tools,
            "complete": complete,
            "pages": pages,
            "notes": notes,
            "notifications": notifications,
            "protocol_version": self.protocol_version,
            "protocol_generation": self.protocol_generation,
            "cache": cache_hints,
            "stderr_tail": self.stderr_tail(),
            "connection_status": connection_status_for_generation(self.protocol_generation, verified=True),
        }

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        execution_id: str | None = None,
        input_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # input_schema is HTTP-only (Mcp-Param); accepted here for API symmetry.
        _ = input_schema
        try:
            result = self.request(
                "tools/call",
                {"name": tool_name, "arguments": arguments},
                execution_id=execution_id,
            )
        except McpClientError as exc:
            if exc.kind == "timeout":
                return {
                    "tool": tool_name,
                    "isError": True,
                    "error_kind": "unknown_outcome",
                    "error": str(exc),
                    "timeout": True,
                    "may_have_side_effects": True,
                    "transport": self.transport,
                    "stderr_tail": self.stderr_tail(),
                }
            raise
        with self._lock:
            notes = list(self.notifications)
        content = result.get("content")
        structured = result.get("structuredContent")
        result_type = result.get("resultType") or "complete"
        empty_payload = (
            (content is None or content == [] or content == "" or content == {})
            and (structured is None or structured == {} or structured == [])
            and result_type == "complete"
        )
        is_error = bool(result.get("isError")) or empty_payload
        payload = {
            "tool": tool_name,
            "result": result,
            "isError": is_error,
            "error_kind": "tool_error" if is_error else None,
            "structuredContent": structured,
            "content": content,
            "resultType": result_type,
            "notifications": notes,
            "protocol_version": self.protocol_version,
            "protocol_generation": self.protocol_generation,
            "transport": self.transport,
            "stderr_tail": self.stderr_tail(),
        }
        if result_type == "input_required":
            payload["isError"] = True
            payload["error_kind"] = "protocol"
            payload["error"] = "MCP input_required (MRTR) is not supported by HADES yet"
            payload["mrtr_unsupported"] = True
        if empty_payload and not result.get("isError"):
            payload["error"] = "empty MCP tool content"
        return payload

    def close(self) -> None:
        self._closed = True
        self.cancel_pending()
        _terminate_process_tree(self.proc)


class HttpMcpClient:
    """Streamable HTTP MCP client with redirect re-validation and optional bearer auth."""

    transport = "streamable_http"

    def __init__(
        self,
        endpoint_url: str,
        *,
        headers: dict[str, str] | None = None,
        bearer_token: str | None = None,
        timeout: float = 60.0,
        allow_private: bool = False,
    ) -> None:
        self.timeout = finite_timeout(timeout)
        self.allow_private = bool(allow_private)
        self.endpoint_url = self._validate_url(endpoint_url)
        self._endpoint_origin = _url_origin(self.endpoint_url)
        self.headers = {str(k): str(v) for k, v in (headers or {}).items()}
        if bearer_token:
            self.headers["Authorization"] = f"Bearer {bearer_token}"
        self.protocol_version = DEFAULT_PROTOCOL_VERSION
        self.protocol_generation = protocol_generation(self.protocol_version)
        self.session_id: str | None = None
        self._id = 0
        self._closed = False
        self._lock = threading.RLock()
        self._cancel_flags: dict[Any, threading.Event] = {}
        self._execution_requests: dict[str, Any] = {}
        self._active_streams: dict[Any, Any] = {}
        self.notifications: deque[dict[str, Any]] = deque(maxlen=200)
        self._client = httpx.Client(timeout=self.timeout, follow_redirects=False)
        self.last_transport_error: str | None = None

    def _validate_url(self, url: str) -> str:
        raw = (url or "").strip()
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower().strip("[]")
        local = _is_explicit_loopback_host(host)
        if local and not self.allow_private:
            raise McpClientError("Loopback MCP endpoint requires explicit local permission", kind="validation")
        try:
            # `allow_private` is deliberately narrowed to explicit loopback only.
            # It must never become permission for RFC1918, link-local, metadata, or
            # another private redirect target.
            assert_public_http_url(raw, allow_private=bool(local and self.allow_private), purpose="mcp_http")
        except UrlSecurityError as exc:
            raise McpClientError(str(exc), kind="validation") from exc
        return raw

    def _validated_redirect_target(self, current_url: str, location: str) -> str:
        """Return a same-origin redirect target or fail before credentials are re-sent."""
        host = (urlparse(location).hostname or "").lower().strip("[]")
        allow_loopback = bool(self.allow_private and _is_explicit_loopback_host(host))
        safe = safe_public_url(location, base=current_url, allow_private=allow_loopback)
        if not safe:
            raise McpClientError(f"Redirect blocked by network policy: {location}", kind="auth")
        if _url_origin(safe) != self._endpoint_origin:
            raise McpClientError("Cross-origin MCP redirect blocked to protect credentials", kind="auth")
        return safe

    def _next_id(self) -> int:
        with self._lock:
            self._id += 1
            return self._id

    @property
    def alive(self) -> bool:
        """Local client object is open — not proof of remote reachability.

        Callers must use protocol verification / last error for UI 'connected'.
        """
        return not self._closed

    def cancel_execution(self, execution_id: str) -> bool:
        with self._lock:
            req_id = self._execution_requests.get(execution_id)
        if req_id is None:
            return False
        return self.cancel_request(req_id)

    def cancel_request(self, req_id: Any) -> bool:
        with self._lock:
            flag = self._cancel_flags.get(req_id)
            stream = self._active_streams.get(req_id)
            if flag is not None:
                flag.set()
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            return flag is not None

    def cancel_pending(self, req_id: Any | None = None) -> None:
        with self._lock:
            if req_id is not None:
                flag = self._cancel_flags.get(req_id)
                if flag is not None:
                    flag.set()
                stream = self._active_streams.get(req_id)
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
                return
            for flag in list(self._cancel_flags.values()):
                flag.set()
            for stream in list(self._active_streams.values()):
                try:
                    stream.close()
                except Exception:
                    pass

    def _tool_name_from_payload(self, method: str, params: dict[str, Any] | None) -> str | None:
        return mcp_name_from_params(method, params)

    def _parse_www_authenticate(self, header_value: str | None) -> dict[str, Any]:
        if not header_value:
            return {}
        challenge: dict[str, Any] = {"raw": header_value}
        # Support Bearer realm=..., error=..., error_description=..., scope=..., resource_metadata=...
        lower = header_value.strip()
        if lower.lower().startswith("bearer"):
            challenge["scheme"] = "Bearer"
            rest = header_value[6:].strip()
        else:
            challenge["scheme"] = lower.split(" ", 1)[0]
            rest = lower.split(" ", 1)[1] if " " in lower else ""
        for part in rest.split(","):
            item = part.strip()
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            value = value.strip().strip('"')
            challenge[key.strip().lower()] = value
        return challenge

    def _raise_http_error(self, response: httpx.Response, *, body: bytes | str | None = None) -> None:
        raw = body if body is not None else b""
        if isinstance(raw, bytes):
            text = raw.decode("utf-8", errors="replace")
        else:
            text = str(raw)
        rpc = parse_jsonrpc_error_body(text, http_status=response.status_code)
        if response.status_code in {401, 403}:
            challenge = self._parse_www_authenticate(response.headers.get("WWW-Authenticate"))
            kind = "auth" if response.status_code == 401 else "permission"
            raise McpClientError(
                f"MCP authentication required (HTTP {response.status_code})",
                kind=kind,
                rpc=rpc,
                http_status=response.status_code,
                auth_challenge=challenge,
            )
        classification = classify_http_probe_failure(
            http_status=response.status_code,
            body=text,
        )
        raise McpClientError(
            f"HTTP MCP error {response.status_code}: {text[:500]}",
            kind=str(classification.get("kind") or "transport"),
            rpc=rpc or classification.get("rpc"),
            http_status=response.status_code,
            legacy_evidence=bool(classification.get("legacy_evidence")),
        )

    def _post_jsonrpc(
        self,
        payload: dict[str, Any],
        *,
        cancel_flag: threading.Event | None = None,
        param_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if self._closed:
            raise McpClientError("HTTP MCP client closed", kind="transport")
        if cancel_flag is not None and cancel_flag.is_set():
            raise McpClientError("MCP request cancelled", kind="cancelled")
        method = str(payload.get("method") or "")
        params = payload.get("params") if isinstance(payload.get("params"), dict) else None
        try:
            headers = mcp_http_headers(
                method=method or "unknown",
                protocol_version=self.protocol_version,
                name=self._tool_name_from_payload(method, params),
                session_id=self.session_id if not is_modern_protocol(self.protocol_version) else None,
                extra=self.headers,
                param_headers=param_headers,
            )
        except ValueError as exc:
            raise McpClientError(str(exc), kind="validation") from exc
        url = self.endpoint_url
        hops = 0
        req_id = payload.get("id")
        while hops < 5:
            hops += 1
            if cancel_flag is not None and cancel_flag.is_set():
                raise McpClientError("MCP request cancelled", kind="cancelled")
            try:
                # Stream body so cancellation can close the response without
                # buffering unbounded SSE into memory.
                request = self._client.build_request(
                    "POST",
                    url,
                    headers=headers,
                    content=json.dumps(payload, ensure_ascii=False),
                )
                response = self._client.send(request, stream=True)
                with self._lock:
                    if req_id is not None:
                        self._active_streams[req_id] = response
            except httpx.TimeoutException as exc:
                self.last_transport_error = str(exc)
                raise McpClientError(f"HTTP MCP timeout: {exc}", kind="timeout") from exc
            except Exception as exc:
                self.last_transport_error = str(exc)
                raise McpClientError(f"HTTP MCP transport error: {exc}", kind="transport") from exc
            try:
                if response.status_code in {301, 302, 303, 307, 308}:
                    loc = redirect_location(response, url)
                    response.close()
                    if not loc:
                        raise McpClientError("Redirect without Location", kind="transport")
                    url = self._validated_redirect_target(url, loc)
                    continue
                # Legacy session recovery
                if (
                    response.status_code == 404
                    and self.session_id
                    and not is_modern_protocol(self.protocol_version)
                    and method != "initialize"
                ):
                    response.close()
                    self.session_id = None
                    raise McpClientError("Legacy MCP session expired (HTTP 404)", kind="transport")
                session_header = response.headers.get("mcp-session-id") or response.headers.get("Mcp-Session-Id")
                if session_header and not is_modern_protocol(self.protocol_version):
                    self.session_id = session_header
                ctype = (response.headers.get("content-type") or "").lower()
                if response.status_code >= 400:
                    body = response.read()[:MAX_PAYLOAD_BYTES]
                    response.close()
                    self._raise_http_error(response, body=body)
                if "text/event-stream" in ctype:
                    return self._read_sse_jsonrpc(response, expect_id=payload.get("id"), cancel_flag=cancel_flag)
                raw = response.read()
                response.close()
                if len(raw) > MAX_PAYLOAD_BYTES:
                    raise McpClientError("HTTP MCP JSON response exceeds size limit", kind="protocol")
                try:
                    message = json.loads(raw.decode("utf-8"))
                except Exception as exc:
                    raise McpClientError(f"Invalid JSON from MCP HTTP endpoint: {exc}", kind="protocol") from exc
                if not isinstance(message, dict):
                    raise McpClientError("MCP HTTP response was not a JSON object", kind="protocol")
                if "method" in message and message.get("id") is None:
                    self.notifications.append(message)
                    raise McpClientError("Unexpected MCP notification without response", kind="protocol")
                if "error" in message:
                    rpc = parse_jsonrpc_error_body(message, http_status=200)
                    raise McpClientError(
                        json.dumps(message["error"], ensure_ascii=False),
                        kind="protocol",
                        rpc=rpc,
                        legacy_evidence=bool(rpc and rpc.is_method_not_found),
                    )
                if payload.get("id") is not None and message.get("id") != payload.get("id"):
                    raise McpClientError("JSON-RPC response id mismatch", kind="protocol")
                result = message.get("result", {})
                self.last_transport_error = None
                return result if isinstance(result, dict) else {"value": result}
            finally:
                with self._lock:
                    if req_id is not None:
                        self._active_streams.pop(req_id, None)
        raise McpClientError("Too many redirects", kind="transport")

    def _read_sse_jsonrpc(
        self,
        response: httpx.Response,
        *,
        expect_id: Any,
        cancel_flag: threading.Event | None,
    ) -> dict[str, Any]:
        data_lines: list[str] = []
        total = 0
        try:
            for line in response.iter_lines():
                if cancel_flag is not None and cancel_flag.is_set():
                    raise McpClientError("MCP request cancelled", kind="cancelled")
                total += len(line) + 1
                if total > MAX_SSE_BYTES:
                    raise McpClientError("SSE MCP response exceeded size limit", kind="protocol")
                if line.startswith(":"):
                    continue  # keep-alive comment
                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
                    continue
                if line.strip() == "" and data_lines:
                    chunk = "\n".join(data_lines)
                    data_lines = []
                    try:
                        message = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(message, dict):
                        continue
                    if "method" in message and message.get("id") is None:
                        self.notifications.append(message)
                        continue
                    if (
                        "method" in message
                        and message.get("id") is not None
                        and "result" not in message
                        and "error" not in message
                    ):
                        # Legacy server request on SSE — unsupported; record only.
                        self.notifications.append({"method": "hades/unsupported_server_request", "params": message})
                        continue
                    if expect_id is not None and message.get("id") != expect_id:
                        self.notifications.append({"method": "hades/orphan_response", "params": message})
                        continue
                    if cancel_flag is not None and cancel_flag.is_set():
                        raise McpClientError("MCP request cancelled", kind="cancelled")
                    if "error" in message:
                        raise McpClientError(json.dumps(message["error"], ensure_ascii=False), kind="protocol")
                    result = message.get("result", {})
                    self.last_transport_error = None
                    return result if isinstance(result, dict) else {"value": result}
            if cancel_flag is not None and cancel_flag.is_set():
                raise McpClientError("MCP request cancelled", kind="cancelled")
            if data_lines:
                message = json.loads("\n".join(data_lines))
                if isinstance(message, dict):
                    if "error" in message:
                        raise McpClientError(json.dumps(message["error"], ensure_ascii=False), kind="protocol")
                    result = message.get("result", {})
                    return result if isinstance(result, dict) else {"value": result}
            raise McpClientError("SSE stream ended without JSON-RPC response", kind="protocol")
        except McpClientError:
            raise
        except Exception as exc:
            if cancel_flag is not None and cancel_flag.is_set():
                raise McpClientError("MCP request cancelled", kind="cancelled") from exc
            # Closing the response stream during cancel often surfaces as OS/httpx read errors.
            name = type(exc).__name__
            text = str(exc).lower()
            if "bad file descriptor" in text or name in {"ReadError", "RemoteProtocolError", "StreamClosed"}:
                raise McpClientError("SSE stream ended without JSON-RPC response", kind="protocol") from exc
            raise McpClientError(f"SSE read failed: {exc}", kind="transport") from exc
        finally:
            try:
                response.close()
            except Exception:
                pass

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        execution_id: str | None = None,
        param_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        req_id = self._next_id()
        stamped = stamp_params(params, protocol_version=self.protocol_version)
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if stamped:
            payload["params"] = stamped
        if not json_size_ok(payload):
            raise McpClientError("MCP request exceeds MAX_PAYLOAD_BYTES", kind="validation")
        cancel_flag = threading.Event()
        with self._lock:
            self._cancel_flags[req_id] = cancel_flag
            if execution_id:
                self._execution_requests[execution_id] = req_id
        try:
            return self._post_jsonrpc(payload, cancel_flag=cancel_flag, param_headers=param_headers)
        except McpClientError:
            raise
        except Exception as exc:
            if cancel_flag.is_set():
                raise McpClientError("MCP request cancelled", kind="cancelled") from exc
            name = type(exc).__name__
            text = str(exc).lower()
            if "bad file descriptor" in text or name in {"ReadError", "RemoteProtocolError", "StreamClosed"}:
                raise McpClientError("SSE stream ended without JSON-RPC response", kind="protocol") from exc
            raise
        finally:
            with self._lock:
                self._cancel_flags.pop(req_id, None)
                if execution_id:
                    self._execution_requests.pop(execution_id, None)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        stamped = stamp_params(params, protocol_version=self.protocol_version)
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if stamped:
            payload["params"] = stamped
        try:
            headers = mcp_http_headers(
                method=method,
                protocol_version=self.protocol_version,
                session_id=self.session_id if not is_modern_protocol(self.protocol_version) else None,
                extra=self.headers,
            )
        except ValueError:
            return
        try:
            self._client.post(self.endpoint_url, headers=headers, content=json.dumps(payload, ensure_ascii=False))
        except Exception:
            pass

    def _negotiate_legacy(self) -> dict[str, Any]:
        last_error: Exception | None = None
        for version in [v for v in SUPPORTED_PROTOCOL_VERSIONS if v in LEGACY_PROTOCOL_VERSIONS]:
            try:
                self.protocol_version = version
                self.protocol_generation = "legacy"
                result = self.request(
                    "initialize",
                    {
                        "protocolVersion": version,
                        "capabilities": {},
                        "clientInfo": dict(CLIENT_INFO),
                    },
                )
                negotiated = str(result.get("protocolVersion") or version)
                if negotiated not in SUPPORTED_PROTOCOL_VERSIONS or is_modern_protocol(negotiated):
                    raise McpClientError(
                        f"Unsupported legacy MCP protocol version negotiated: {negotiated}",
                        kind="protocol",
                    )
                self.protocol_version = negotiated
                self.protocol_generation = "legacy"
                self.notify("notifications/initialized", {})
                return result
            except McpClientError as exc:
                last_error = exc
                if exc.kind in {"auth", "permission", "timeout", "cancelled"}:
                    raise
                continue
        raise McpClientError(f"MCP initialize mislukt: {last_error}", kind="protocol")

    def _apply_modern_discover(self, discovered: dict[str, Any]) -> dict[str, Any]:
        parsed = parse_discover_supported_versions(discovered)
        if not parsed["ok"]:
            if parsed["source"] == "alias" and parsed.get("raw") is not None:
                # Compatibility: non-normative aliases may be used to negotiate, but
                # a missing/empty normative field must not silently invent support.
                pass
            else:
                raise McpClientError(
                    f"Invalid server/discover supportedVersions ({parsed['source']})",
                    kind="protocol",
                )
        supported = parsed["supported"]
        if not supported:
            raise McpClientError("server/discover returned empty supportedVersions", kind="protocol")
        chosen = select_mutually_supported_version(supported)
        if chosen is None:
            raise McpClientError(
                f"No mutually supported MCP protocol version in {supported}",
                kind="protocol",
            )
        if not is_modern_protocol(chosen):
            return self._negotiate_legacy()
        validation = validate_modern_discover_result(discovered)
        if parsed["source"] == "supportedVersions" and not validation["ok"]:
            raise McpClientError(
                "Malformed modern DiscoverResult: " + ", ".join(validation["issues"]),
                kind="protocol",
            )
        self.protocol_version = MODERN_PROTOCOL_VERSION
        self.protocol_generation = "modern"
        self.session_id = None
        return discovered

    def _negotiate_modern(self) -> dict[str, Any]:
        self.protocol_version = MODERN_PROTOCOL_VERSION
        self.protocol_generation = "modern"
        self.session_id = None
        try:
            discovered = self.request("server/discover", {})
            return self._apply_modern_discover(discovered if isinstance(discovered, dict) else {})
        except McpClientError as exc:
            rpc = exc.rpc
            if exc.kind in {"auth", "permission", "timeout", "cancelled"}:
                raise
            if rpc is not None and rpc.is_unsupported_protocol_version:
                supported = rpc.supported_versions()
                chosen = select_mutually_supported_version(supported)
                if chosen is None:
                    raise McpClientError(
                        f"UnsupportedProtocolVersion with no mutually supported revision: {supported}",
                        kind="protocol",
                        rpc=rpc,
                    ) from exc
                if is_modern_protocol(chosen):
                    self.protocol_version = chosen
                    self.protocol_generation = "modern"
                    # Retry discover under the mutually supported modern revision.
                    discovered = self.request("server/discover", {})
                    return self._apply_modern_discover(discovered if isinstance(discovered, dict) else {})
                return self._negotiate_legacy()
            if rpc is not None and (rpc.is_header_mismatch or rpc.is_missing_capability):
                # Spec: recognized modern errors are NOT legacy evidence.
                raise McpClientError(
                    str(exc),
                    kind="protocol",
                    rpc=rpc,
                    http_status=exc.http_status,
                    legacy_evidence=False,
                ) from exc
            if exc.legacy_evidence or (rpc is not None and rpc.is_method_not_found):
                return self._negotiate_legacy()
            # Transport / 5xx / network must not silently downgrade.
            if exc.kind in {"transport"} and exc.http_status is not None and exc.http_status >= 500:
                raise
            if exc.kind == "transport" and exc.http_status is None:
                raise
            # Dual-era HTTP: 4xx without recognized modern error body → legacy.
            if exc.http_status is not None and 400 <= exc.http_status < 500:
                return self._negotiate_legacy()
            raise

    def initialize(self) -> dict[str, Any]:
        return self._negotiate_modern()

    def delete_session(self) -> None:
        if not self.session_id or is_modern_protocol(self.protocol_version):
            return
        headers = mcp_http_headers(
            method="session/delete",
            protocol_version=self.protocol_version,
            session_id=self.session_id,
            extra=self.headers,
        )
        try:
            self._client.delete(self.endpoint_url, headers=headers)
        except Exception:
            pass
        self.session_id = None

    def list_tools_all(self) -> dict[str, Any]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        pages = 0
        complete = True
        notes: list[str] = []
        cache_hints: dict[str, Any] = {}
        rejected_tools: list[dict[str, str]] = []
        while pages < MAX_TOOL_LIST_PAGES:
            pages += 1
            params: dict[str, Any] = {}
            if cursor:
                params["cursor"] = cursor
            result = self.request("tools/list", params)
            if "ttlMs" in result or "cacheScope" in result:
                cache_hints = {"ttlMs": result.get("ttlMs"), "cacheScope": result.get("cacheScope")}
            batch = result.get("tools") or []
            if isinstance(batch, list):
                raw_tools = [item for item in batch if isinstance(item, dict)]
                if is_modern_protocol(self.protocol_version):
                    kept, rejected = filter_tools_for_http_headers(raw_tools)
                    tools.extend(kept)
                    rejected_tools.extend(rejected)
                else:
                    tools.extend(raw_tools)
            next_cursor = result.get("nextCursor") or result.get("next_cursor")
            if not next_cursor:
                break
            cursor = str(next_cursor)
            if discovery_cursor_loop(seen_cursors, cursor):
                complete = False
                notes.append("repeated_cursor")
                break
        else:
            complete = False
            notes.append("page_limit_reached")
        if rejected_tools:
            notes.append("rejected_invalid_x_mcp_header")
        return {
            "tools": tools,
            "complete": complete,
            "pages": pages,
            "notes": notes,
            "notifications": list(self.notifications),
            "protocol_version": self.protocol_version,
            "protocol_generation": self.protocol_generation,
            "cache": cache_hints,
            "rejected_tools": rejected_tools,
            "connection_status": connection_status_for_generation(self.protocol_generation, verified=True),
        }

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        execution_id: str | None = None,
        input_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        param_headers: dict[str, str] | None = None
        if is_modern_protocol(self.protocol_version) and input_schema is not None:
            try:
                param_headers = build_mcp_param_headers(input_schema, arguments)
            except McpParamError as exc:
                raise McpClientError(str(exc), kind="validation") from exc
        try:
            result = self.request(
                "tools/call",
                {"name": tool_name, "arguments": arguments},
                execution_id=execution_id,
                param_headers=param_headers,
            )
        except McpClientError as exc:
            if exc.kind == "timeout":
                return {
                    "tool": tool_name,
                    "isError": True,
                    "error_kind": "unknown_outcome",
                    "error": str(exc),
                    "timeout": True,
                    "may_have_side_effects": True,
                    "transport": self.transport,
                }
            if exc.kind == "transport" and "session expired" in str(exc).lower():
                self.last_transport_error = str(exc)
            raise
        content = result.get("content")
        structured = result.get("structuredContent")
        result_type = result.get("resultType") or "complete"
        empty_payload = (
            (content is None or content == [] or content == "" or content == {})
            and (structured is None or structured == {} or structured == [])
            and result_type == "complete"
        )
        is_error = bool(result.get("isError")) or empty_payload
        payload = {
            "tool": tool_name,
            "result": result,
            "isError": is_error,
            "error_kind": "tool_error" if is_error else None,
            "structuredContent": structured,
            "content": content,
            "resultType": result_type,
            "notifications": list(self.notifications),
            "protocol_version": self.protocol_version,
            "protocol_generation": self.protocol_generation,
            "transport": self.transport,
        }
        if result_type == "input_required":
            payload["isError"] = True
            payload["error_kind"] = "protocol"
            payload["error"] = "MCP input_required (MRTR) is not supported by HADES yet"
            payload["mrtr_unsupported"] = True
        if empty_payload and not result.get("isError"):
            payload["error"] = "empty MCP tool content"
        return payload

    def close(self) -> None:
        self._closed = True
        self.cancel_pending()
        try:
            self.delete_session()
        except Exception:
            pass
        try:
            self._client.close()
        except Exception:
            pass


def new_request_id() -> str:
    return uuid.uuid4().hex