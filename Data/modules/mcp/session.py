"""One MCP server session — independent lifecycle, request IDs, and health."""

from __future__ import annotations

import itertools
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any

from .errors import (
    MCP_CALL_CANCELLED,
    MCP_CALL_TIMEOUT,
    MCP_CONNECT_FAILED,
    MCP_INITIALIZE_FAILED,
    MCP_PROTOCOL_ERROR,
    MCP_SERVER_UNAVAILABLE,
    MCP_TOOL_CALL_FAILED,
    McpError,
)
from .limits import McpLimits
from .policy import resolve_effective_isolation, sanitize_text_for_log
from .protocol import (
    build_initialize_params,
    build_notification,
    build_request,
    extract_result,
    is_notification,
    is_response,
    negotiate_protocol_version,
)
from .secrets import build_process_env
from .transports import HttpTransport, StdioTransport, unsupported_sse
from .types import (
    McpCallResult,
    McpCallStatus,
    McpIsolationKind,
    McpServerConfig,
    McpServerRuntime,
    McpServerState,
    McpTransportKind,
)


@dataclass
class McpServerSession:
    config: McpServerConfig
    limits: McpLimits
    allow_outbound: bool = False
    secret_overrides: dict[str, str] = field(default_factory=dict)
    runtime: McpServerRuntime = field(init=False)
    _id_counter: itertools.count = field(default_factory=lambda: itertools.count(1), init=False, repr=False)
    _pending: dict[int | str, Future[dict[str, Any]]] = field(default_factory=dict, init=False, repr=False)
    _pending_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _lifecycle_lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _call_sema: threading.Semaphore | None = field(default=None, init=False, repr=False)
    _stdio: StdioTransport | None = field(default=None, init=False, repr=False)
    _http: HttpTransport | None = field(default=None, init=False, repr=False)
    _secret_values: list[str] = field(default_factory=list, init=False, repr=False)
    _stderr_buf: list[str] = field(default_factory=list, init=False, repr=False)
    _protocol_version: str | None = field(default=None, init=False)
    _server_info: dict[str, Any] = field(default_factory=dict, init=False)
    _tools_cache: list[dict[str, Any]] | None = field(default=None, init=False)
    _restart_timestamps: list[float] = field(default_factory=list, init=False, repr=False)
    _circuit_open_until: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        self.runtime = McpServerRuntime(server_id=self.config.server_id)
        if not self.config.enabled:
            self.runtime.state = McpServerState.DISABLED
        max_calls = min(self.config.max_concurrent_calls, self.limits.max_concurrent_calls_per_server)
        self._call_sema = threading.Semaphore(max(1, max_calls))

    @property
    def ready(self) -> bool:
        return self.runtime.state in {McpServerState.READY, McpServerState.BUSY, McpServerState.DEGRADED}

    def connect(self) -> McpServerRuntime:
        with self._lifecycle_lock:
            if self.runtime.circuit_open or time.monotonic() < self._circuit_open_until:
                self.runtime.state = McpServerState.CIRCUIT_OPEN
                self.runtime.circuit_open = True
                raise McpError(
                    "MCP_CIRCUIT_OPEN",
                    f"MCP server circuit open for {self.config.server_id}",
                )
            if not self.config.enabled:
                self.runtime.state = McpServerState.DISABLED
                raise McpError("MCP_SERVER_DISABLED", f"MCP server disabled: {self.config.server_id}")

            effective, matched = resolve_effective_isolation(
                self.config.requested_isolation,
                transport=self.config.transport,
            )
            self.runtime.effective_isolation = effective
            if self.config.requested_isolation in {
                McpIsolationKind.CONTAINER,
                McpIsolationKind.SANDBOX,
            } and not matched:
                self.runtime.state = McpServerState.ERROR
                self.runtime.last_error_code = "MCP_ISOLATION_UNAVAILABLE"
                self.runtime.last_error_message = (
                    f"Requested isolation {self.config.requested_isolation.value} unavailable; "
                    f"effective={effective.value}"
                )
                raise McpError(
                    "MCP_ISOLATION_UNAVAILABLE",
                    self.runtime.last_error_message,
                    details={
                        "requested": self.config.requested_isolation.value,
                        "effective": effective.value,
                    },
                )

            self.runtime.state = McpServerState.CONNECTING
            try:
                if self.config.transport == McpTransportKind.STDIO:
                    self._connect_stdio()
                elif self.config.transport == McpTransportKind.HTTP:
                    self._connect_http()
                elif self.config.transport == McpTransportKind.SSE:
                    unsupported_sse()
                else:
                    raise McpError(
                        "MCP_TRANSPORT_UNSUPPORTED",
                        f"Unknown transport: {self.config.transport.value}",
                    )
                self._handshake()
                self.runtime.state = McpServerState.READY
                self.runtime.last_error_code = None
                self.runtime.last_error_message = None
                self.runtime.last_connected_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                self.runtime.last_seen_at = self.runtime.last_connected_at
                return self.runtime
            except McpError as exc:
                self.runtime.state = McpServerState.ERROR
                self.runtime.last_error_code = exc.code
                self.runtime.last_error_message = sanitize_text_for_log(
                    exc.message, secret_values=self._secret_values
                )
                self._cleanup_transport()
                self._note_failure()
                raise
            except Exception as exc:  # noqa: BLE001
                self.runtime.state = McpServerState.ERROR
                self.runtime.last_error_code = MCP_CONNECT_FAILED
                self.runtime.last_error_message = sanitize_text_for_log(
                    str(exc), secret_values=self._secret_values
                )
                self._cleanup_transport()
                self._note_failure()
                raise McpError(MCP_CONNECT_FAILED, str(exc)) from exc

    def disconnect(self) -> None:
        with self._lifecycle_lock:
            self._cleanup_transport()
            self._fail_pending(McpError(MCP_SERVER_UNAVAILABLE, "Server disconnected"))
            self._tools_cache = None
            if self.config.enabled:
                self.runtime.state = McpServerState.DISCONNECTED
            else:
                self.runtime.state = McpServerState.DISABLED
            self.runtime.pid = None

    def list_tools(self, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        if not self.ready:
            raise McpError(MCP_SERVER_UNAVAILABLE, f"Server not ready: {self.config.server_id}")
        if self._tools_cache is not None and not force_refresh:
            return list(self._tools_cache)
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {}
            if cursor:
                params["cursor"] = cursor
            result = self._request("tools/list", params or None, timeout=self.config.timeout_seconds)
            batch = result.get("tools") if isinstance(result, dict) else None
            if not isinstance(batch, list):
                raise McpError(MCP_PROTOCOL_ERROR, "tools/list missing tools array")
            for item in batch:
                if isinstance(item, dict) and item.get("name"):
                    tools.append(item)
                # One invalid tool must not discard the rest — skip silently but count later.
            if len(tools) > self.limits.max_tools_per_server:
                raise McpError(
                    "MCP_PROTOCOL_LIMIT_EXCEEDED",
                    f"Server returned more than {self.limits.max_tools_per_server} tools",
                )
            cursor = result.get("nextCursor") if isinstance(result, dict) else None
            if not cursor:
                break
        self._tools_cache = tools
        self.runtime.tool_count = len(tools)
        return list(tools)

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        cancel_event: threading.Event | None = None,
    ) -> McpCallResult:
        if not self.ready:
            raise McpError(MCP_SERVER_UNAVAILABLE, f"Server not ready: {self.config.server_id}")
        assert self._call_sema is not None
        acquired = self._call_sema.acquire(timeout=timeout or self.config.timeout_seconds)
        if not acquired:
            raise McpError(MCP_CALL_TIMEOUT, "Timed out waiting for MCP call slot")
        started = time.perf_counter()
        self.runtime.state = McpServerState.BUSY
        try:
            if cancel_event is not None and cancel_event.is_set():
                raise McpError(MCP_CALL_CANCELLED, "MCP call cancelled before dispatch")
            result = self._request(
                "tools/call",
                {"name": name, "arguments": arguments or {}},
                timeout=timeout or self.config.timeout_seconds,
                cancel_event=cancel_event,
            )
            content = result.get("content") if isinstance(result, dict) else None
            is_error = bool(result.get("isError")) if isinstance(result, dict) else False
            truncated = False
            if content is not None:
                import json

                raw = json.dumps(content, ensure_ascii=False).encode("utf-8")
                if len(raw) > self.limits.max_tool_result_bytes:
                    truncated = True
                    content = [{"type": "text", "text": "[truncated MCP tool result]"}]
            status = McpCallStatus.FAILED if is_error else McpCallStatus.COMPLETED
            return McpCallResult(
                status=status,
                content=content if isinstance(content, list) else [{"type": "text", "text": str(result)}],
                is_error=is_error,
                error_code=MCP_TOOL_CALL_FAILED if is_error else None,
                error_message="Tool reported isError=true" if is_error else None,
                duration_ms=(time.perf_counter() - started) * 1000,
                truncated=truncated,
            )
        except McpError as exc:
            status = {
                MCP_CALL_TIMEOUT: McpCallStatus.TIMEOUT,
                MCP_CALL_CANCELLED: McpCallStatus.CANCELLED,
            }.get(exc.code, McpCallStatus.FAILED)
            return McpCallResult(
                status=status,
                is_error=True,
                error_code=exc.code,
                error_message=sanitize_text_for_log(exc.message, secret_values=self._secret_values),
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        finally:
            self._call_sema.release()
            if self.ready or self.runtime.state == McpServerState.BUSY:
                self.runtime.state = McpServerState.READY

    def invalidate_tools_cache(self) -> None:
        self._tools_cache = None

    def health(self) -> McpServerRuntime:
        # PID alone is not health — require READY/BUSY/DEGRADED after successful initialize.
        if self.config.transport == McpTransportKind.STDIO and self._stdio is not None:
            if not self._stdio.alive and self.runtime.state not in {
                McpServerState.DISCONNECTED,
                McpServerState.DISABLED,
                McpServerState.ERROR,
                McpServerState.CIRCUIT_OPEN,
            }:
                self.runtime.state = McpServerState.ERROR
                self.runtime.last_error_code = MCP_SERVER_UNAVAILABLE
                self.runtime.last_error_message = "MCP process exited"
                self.runtime.pid = None
        return self.runtime

    # --- internals ---

    def _connect_stdio(self) -> None:
        if not self.config.command:
            raise McpError(MCP_CONNECT_FAILED, "stdio transport requires command")
        env, secrets = build_process_env(
            env_public=self.config.env_public,
            secret_refs=self.config.secret_refs,
            overrides=self.secret_overrides,
        )
        self._secret_values = secrets
        transport = StdioTransport(
            command=self.config.command,
            args=self.config.args,
            cwd=self.config.cwd,
            env=env,
            limits=self.limits,
            on_message=self._on_stdio_message,
            on_stderr=self._on_stderr,
            on_exit=self._on_process_exit,
        )
        transport.start()
        self._stdio = transport
        self.runtime.pid = transport.pid

    def _connect_http(self) -> None:
        if not self.config.url:
            raise McpError(MCP_CONNECT_FAILED, "http transport requires url")
        # Resolve Authorization from secret refs if present.
        headers: dict[str, str] = {}
        env, secrets = build_process_env(
            env_public=self.config.env_public,
            secret_refs=self.config.secret_refs,
            overrides=self.secret_overrides,
            inherit=False,
        )
        self._secret_values = secrets
        if "AUTHORIZATION" in env:
            headers["Authorization"] = env["AUTHORIZATION"]
        elif "Authorization" in env:
            headers["Authorization"] = env["Authorization"]
        transport = HttpTransport(
            url=self.config.url,
            limits=self.limits,
            timeout_seconds=self.config.timeout_seconds,
            allow_outbound=self.allow_outbound,
            headers=headers,
        )
        transport.start()
        self._http = transport

    def _handshake(self) -> None:
        try:
            result = self._request(
                "initialize",
                build_initialize_params(),
                timeout=min(self.config.timeout_seconds, self.limits.startup_timeout_seconds),
            )
        except McpError as exc:
            raise McpError(MCP_INITIALIZE_FAILED, exc.message, details=exc.details) from exc
        if not isinstance(result, dict):
            raise McpError(MCP_INITIALIZE_FAILED, "initialize result must be an object")
        version = negotiate_protocol_version(str(result.get("protocolVersion") or "") or None)
        self._protocol_version = version
        self.runtime.protocol_version = version
        info = result.get("serverInfo") if isinstance(result.get("serverInfo"), dict) else {}
        self._server_info = info
        self.runtime.server_name = str(info.get("name") or "") or None
        self.runtime.server_version = str(info.get("version") or "") or None
        # initialized notification
        self._notify("notifications/initialized", {})

    def _request(
        self,
        method: str,
        params: dict[str, Any] | None,
        *,
        timeout: float,
        cancel_event: threading.Event | None = None,
    ) -> Any:
        request_id = next(self._id_counter)
        message = build_request(method, params, request_id)
        if self._http is not None:
            response = self._http.request(message)
            if response.get("_transport_error"):
                raise McpError(str(response.get("code") or MCP_PROTOCOL_ERROR), str(response.get("error")))
            return extract_result(response)

        if self._stdio is None:
            raise McpError(MCP_SERVER_UNAVAILABLE, "No active transport")
        future: Future[dict[str, Any]] = Future()
        with self._pending_lock:
            self._pending[request_id] = future
        try:
            self._stdio.write(message)
            deadline = time.monotonic() + timeout
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise McpError(MCP_CALL_CANCELLED, f"Cancelled while awaiting {method}")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise McpError(MCP_CALL_TIMEOUT, f"Timeout awaiting {method}")
                try:
                    payload = future.result(timeout=min(0.1, remaining))
                    break
                except TimeoutError:
                    continue
            if payload.get("_transport_error"):
                raise McpError(str(payload.get("code") or MCP_PROTOCOL_ERROR), str(payload.get("error")))
            return extract_result(payload)
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def _notify(self, method: str, params: dict[str, Any] | None) -> None:
        message = build_notification(method, params)
        if self._http is not None:
            # Best-effort; some HTTP servers ignore notifications.
            try:
                self._http.request(message)
            except McpError:
                pass
            return
        if self._stdio is not None:
            self._stdio.write(message)

    def _on_stdio_message(self, payload: dict[str, Any]) -> None:
        if payload.get("_transport_error"):
            # Deliver to any waiter as a synthetic error if only one pending; else stash on runtime.
            self.runtime.last_error_code = str(payload.get("code") or MCP_PROTOCOL_ERROR)
            self.runtime.last_error_message = sanitize_text_for_log(
                str(payload.get("error") or "transport error"),
                secret_values=self._secret_values,
            )
            return
        if is_notification(payload):
            method = str(payload.get("method") or "")
            if method in {"notifications/tools/list_changed", "tools/list_changed"}:
                self.invalidate_tools_cache()
            return
        if not is_response(payload):
            return
        request_id = payload.get("id")
        with self._pending_lock:
            future = self._pending.get(request_id)  # type: ignore[arg-type]
        if future is None:
            # Late / unknown response — ignore honestly (do not invent success).
            return
        if not future.done():
            future.set_result(payload)

    def _on_stderr(self, text: str) -> None:
        cleaned = sanitize_text_for_log(text, secret_values=self._secret_values, max_chars=512)
        self._stderr_buf.append(cleaned)
        if sum(len(item) for item in self._stderr_buf) > self.limits.max_stderr_capture_bytes:
            self._stderr_buf = self._stderr_buf[-10:]

    def _on_process_exit(self, code: int | None) -> None:
        self.runtime.pid = None
        if self.runtime.state in {McpServerState.DISCONNECTED, McpServerState.DISABLED}:
            return
        self.runtime.state = McpServerState.ERROR
        self.runtime.last_error_code = MCP_SERVER_UNAVAILABLE
        self.runtime.last_error_message = f"MCP process exited (code={code})"
        self._fail_pending(
            McpError(MCP_SERVER_UNAVAILABLE, f"MCP process exited (code={code})")
        )
        self._note_failure()

    def _fail_pending(self, error: McpError) -> None:
        with self._pending_lock:
            pending = list(self._pending.items())
            self._pending.clear()
        for _, future in pending:
            if not future.done():
                future.set_result(
                    {"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": error.message}}
                )

    def _cleanup_transport(self) -> None:
        if self._stdio is not None:
            self._stdio.close(timeout=self.limits.shutdown_timeout_seconds)
            self._stdio = None
        if self._http is not None:
            self._http.close(timeout=self.limits.shutdown_timeout_seconds)
            self._http = None

    def _note_failure(self) -> None:
        now = time.monotonic()
        self._restart_timestamps = [
            ts for ts in self._restart_timestamps if now - ts < self.limits.restart_window_seconds
        ]
        self._restart_timestamps.append(now)
        self.runtime.restart_count = len(self._restart_timestamps)
        if len(self._restart_timestamps) >= self.limits.max_restart_attempts:
            self._circuit_open_until = now + self.limits.circuit_open_seconds
            self.runtime.circuit_open = True
            self.runtime.state = McpServerState.CIRCUIT_OPEN
