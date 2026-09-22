"""MCP transports — stdio (MVP) and streamable HTTP."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse

from .errors import (
    MCP_CONNECT_FAILED,
    MCP_NETWORK_BLOCKED,
    MCP_PROTOCOL_ERROR,
    MCP_PROTOCOL_LIMIT_EXCEEDED,
    MCP_TRANSPORT_DEPENDENCY_MISSING,
    MCP_TRANSPORT_UNSUPPORTED,
    McpError,
)
from .limits import McpLimits
from .protocol import decode_message_line, encode_message
from .types import McpTransportKind


def _httpx():
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover — declared in requirements.txt
        raise McpError(
            MCP_TRANSPORT_DEPENDENCY_MISSING,
            "httpx is required for HTTP MCP transport",
            details={"package": "httpx"},
        ) from exc
    return httpx


MessageHandler = Callable[[dict[str, Any]], None]
StderrHandler = Callable[[str], None]
ExitHandler = Callable[[int | None], None]


@dataclass
class StdioTransport:
    """Newline-delimited JSON-RPC over child process stdio."""

    command: str
    args: tuple[str, ...]
    cwd: str | None
    env: dict[str, str]
    limits: McpLimits
    on_message: MessageHandler
    on_stderr: StderrHandler | None = None
    on_exit: ExitHandler | None = None
    _proc: subprocess.Popen[bytes] | None = field(default=None, init=False, repr=False)
    _reader: threading.Thread | None = field(default=None, init=False, repr=False)
    _stderr_reader: threading.Thread | None = field(default=None, init=False, repr=False)
    _write_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _closed: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _stderr_bytes: int = field(default=0, init=False)
    _pgid: int | None = field(default=None, init=False)

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc is not None else None

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        if self._proc is not None:
            raise McpError(MCP_CONNECT_FAILED, "Stdio transport already started")
        try:
            kwargs: dict[str, Any] = {
                "args": [self.command, *self.args],
                "stdin": subprocess.PIPE,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "cwd": self.cwd or None,
                "env": self.env,
                "shell": False,
                "bufsize": 0,
            }
            if os.name == "posix":
                kwargs["start_new_session"] = True
            elif os.name == "nt":
                # CREATE_NEW_PROCESS_GROUP for controlled tree signaling on Windows.
                creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                kwargs["creationflags"] = creationflags
            self._proc = subprocess.Popen(**kwargs)
            if os.name == "posix" and self._proc.pid:
                try:
                    self._pgid = os.getpgid(self._proc.pid)
                except OSError:
                    self._pgid = self._proc.pid
        except OSError as exc:
            raise McpError(MCP_CONNECT_FAILED, f"Failed to spawn MCP server: {exc}") from exc

        self._reader = threading.Thread(target=self._read_stdout, name="mcp-stdio-out", daemon=True)
        self._stderr_reader = threading.Thread(
            target=self._read_stderr, name="mcp-stdio-err", daemon=True
        )
        self._reader.start()
        self._stderr_reader.start()

    def write(self, payload: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None or not self.alive:
            raise McpError(MCP_CONNECT_FAILED, "Stdio transport not connected")
        data = encode_message(payload, limits=self.limits)
        with self._write_lock:
            try:
                self._proc.stdin.write(data)
                self._proc.stdin.flush()
            except BrokenPipeError as exc:
                raise McpError(MCP_CONNECT_FAILED, "Broken pipe writing to MCP server") from exc

    def close(self, *, timeout: float = 10.0) -> None:
        self._closed.set()
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.stdin and not proc.stdin.closed:
                try:
                    proc.stdin.close()
                except OSError:
                    pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    self._kill_tree()
                    try:
                        proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        pass
        finally:
            for stream in (proc.stdout, proc.stderr, proc.stdin):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
            self._kill_tree()
            self._proc = None

    def _kill_tree(self) -> None:
        proc = self._proc
        if proc is None:
            return
        if os.name == "posix" and self._pgid is not None:
            try:
                os.killpg(self._pgid, signal.SIGKILL)
            except OSError:
                try:
                    proc.kill()
                except OSError:
                    pass
        else:
            try:
                proc.kill()
            except OSError:
                pass

    def _read_stdout(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        buffer = b""
        try:
            while not self._closed.is_set():
                chunk = self._proc.stdout.read(1)
                if not chunk:
                    break
                if chunk == b"\n":
                    line = buffer
                    buffer = b""
                    if not line.strip():
                        continue
                    try:
                        message = decode_message_line(line, limits=self.limits)
                    except McpError as exc:
                        self.on_message({"_transport_error": True, "error": str(exc), "code": exc.code})
                        continue
                    self.on_message(message)
                else:
                    buffer += chunk
                    if len(buffer) > self.limits.max_message_bytes:
                        buffer = b""
                        self.on_message(
                            {
                                "_transport_error": True,
                                "error": "Inbound message exceeded size limit",
                                "code": MCP_PROTOCOL_LIMIT_EXCEEDED,
                            }
                        )
        finally:
            code = self._proc.poll() if self._proc else None
            if self.on_exit is not None:
                self.on_exit(code)

    def _read_stderr(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        try:
            while not self._closed.is_set():
                chunk = self._proc.stderr.read(256)
                if not chunk:
                    break
                remaining = self.limits.max_stderr_capture_bytes - self._stderr_bytes
                if remaining <= 0:
                    continue
                take = chunk[:remaining]
                self._stderr_bytes += len(take)
                if self.on_stderr is not None:
                    try:
                        self.on_stderr(take.decode("utf-8", errors="replace"))
                    except Exception:  # noqa: BLE001 — never crash reader on log handler
                        pass
        except Exception:  # noqa: BLE001
            pass


@dataclass
class HttpTransport:
    """Streamable HTTP / JSON MCP transport (single-request JSON-RPC)."""

    url: str
    limits: McpLimits
    timeout_seconds: float
    allow_outbound: bool
    headers: dict[str, str] = field(default_factory=dict)
    _client: httpx.Client | None = field(default=None, init=False, repr=False)

    def start(self) -> None:
        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"}:
            raise McpError(MCP_CONNECT_FAILED, f"Invalid MCP HTTP URL scheme: {parsed.scheme}")
        host = (parsed.hostname or "").lower()
        loopback = host in {"127.0.0.1", "localhost", "::1"}
        if not loopback and not self.allow_outbound:
            raise McpError(
                MCP_NETWORK_BLOCKED,
                "Outbound HTTP MCP blocked by network policy",
                details={"host": host},
            )
        # Basic SSRF guard for non-loopback when outbound is allowed — still refuse metadata IPs.
        if host in {"169.254.169.254", "metadata.google.internal"}:
            raise McpError(MCP_NETWORK_BLOCKED, "Metadata endpoint blocked for MCP HTTP")
        self._client = _httpx().Client(
            timeout=self.timeout_seconds,
            follow_redirects=False,
            headers={"Content-Type": "application/json", **self.headers},
        )

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._client is None:
            raise McpError(MCP_CONNECT_FAILED, "HTTP transport not started")
        body = encode_message(payload, limits=self.limits).rstrip(b"\n")
        httpx = _httpx()
        try:
            response = self._client.post(self.url, content=body)
        except httpx.HTTPError as exc:
            raise McpError(MCP_CONNECT_FAILED, f"HTTP MCP request failed: {exc}") from exc
        if response.status_code >= 400:
            raise McpError(
                MCP_PROTOCOL_ERROR,
                f"HTTP MCP status {response.status_code}",
                details={"status": response.status_code},
            )
        raw = response.content
        if len(raw) > self.limits.max_message_bytes:
            raise McpError(
                MCP_PROTOCOL_LIMIT_EXCEEDED,
                f"HTTP MCP response exceeds {self.limits.max_message_bytes} bytes",
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise McpError(MCP_PROTOCOL_ERROR, f"Invalid JSON in HTTP MCP response: {exc}") from exc
        if not isinstance(data, dict):
            raise McpError(MCP_PROTOCOL_ERROR, "HTTP MCP response must be a JSON object")
        return data

    def close(self, *, timeout: float = 10.0) -> None:
        _ = timeout
        if self._client is not None:
            self._client.close()
            self._client = None


def unsupported_sse() -> None:
    raise McpError(
        MCP_TRANSPORT_UNSUPPORTED,
        "Legacy SSE MCP transport is not implemented in this phase",
        details={"transport": McpTransportKind.SSE.value},
    )
