#!/usr/bin/env python3
"""Stdio MCP client bridge for HADES plugin tools.

Negotiates a supported protocol version, matches JSON-RPC responses by id,
separates notifications, supports paginated tools/list, and maps MCP isError
to a non-zero process exit so PluginManager cannot treat tool failures as success.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from typing import Any

SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2024-10-07")


class McpSession:
    def __init__(self, command: list[str], env: dict[str, str] | None = None, timeout: float = 45.0) -> None:
        if not command:
            raise ValueError("MCP command is empty")
        self.timeout = timeout
        self._id = 0
        self.protocol_version = SUPPORTED_PROTOCOL_VERSIONS[0]
        self.notifications: deque[dict[str, Any]] = deque(maxlen=200)
        self._pending: dict[int, dict[str, Any] | None] = {}
        self._lock = threading.Lock()
        self._closed = False
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        self.proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=False,
            env=env or os.environ.copy(),
            creationflags=creationflags,
        )
        self._stderr_chunks: list[str] = []
        self._stderr_thread = threading.Thread(target=self._pump_stderr, daemon=True)
        self._stderr_thread.start()
        self._reader_thread = threading.Thread(target=self._pump_stdout, daemon=True)
        self._reader_thread.start()

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
            if "method" in message and msg_id is None:
                with self._lock:
                    self.notifications.append(message)
                continue
            if msg_id is not None:
                try:
                    key = int(msg_id)
                except Exception:
                    key = msg_id  # type: ignore[assignment]
                with self._lock:
                    if key in self._pending:
                        self._pending[key] = message
                    else:
                        # Orphan / late response — keep observable.
                        self.notifications.append({"method": "hades/orphan_response", "params": message})

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.proc.poll() is not None:
            err = "".join(self._stderr_chunks)[-4000:]
            raise RuntimeError(f"MCP server exited early ({self.proc.returncode}): {err}")
        assert self.proc.stdin is not None
        req_id = self._next_id()
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            payload["params"] = params
        with self._lock:
            self._pending[req_id] = None
        try:
            self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except Exception as exc:
            with self._lock:
                self._pending.pop(req_id, None)
            raise RuntimeError(f"Kon MCP-request niet schrijven: {exc}") from exc

        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                err = "".join(self._stderr_chunks)[-4000:]
                raise RuntimeError(f"MCP server exited during {method}: {err}")
            with self._lock:
                message = self._pending.get(req_id)
            if message is not None:
                with self._lock:
                    self._pending.pop(req_id, None)
                if "error" in message:
                    raise RuntimeError(json.dumps(message["error"], ensure_ascii=False))
                result = message.get("result", {})
                return result if isinstance(result, dict) else {"value": result}
            time.sleep(0.02)
        with self._lock:
            self._pending.pop(req_id, None)
        raise TimeoutError(f"Timed out waiting for MCP response to {method} (id={req_id})")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        assert self.proc.stdin is not None
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def initialize(self) -> dict[str, Any]:
        last_error: Exception | None = None
        for version in SUPPORTED_PROTOCOL_VERSIONS:
            try:
                result = self.request(
                    "initialize",
                    {
                        "protocolVersion": version,
                        "capabilities": {},
                        "clientInfo": {"name": "hades-mcp-bridge", "version": "0.2.0"},
                    },
                )
                negotiated = str(result.get("protocolVersion") or version)
                # Never force a newer version than the server accepted.
                self.protocol_version = negotiated if negotiated in SUPPORTED_PROTOCOL_VERSIONS else version
                self.notify("notifications/initialized", {})
                return result
            except Exception as exc:
                last_error = exc
                continue
        raise RuntimeError(f"MCP initialize mislukt voor ondersteunde versies: {last_error}")

    def list_tools_all(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        pages = 0
        while pages < 50:
            pages += 1
            params: dict[str, Any] = {}
            if cursor:
                params["cursor"] = cursor
            result = self.request("tools/list", params)
            batch = result.get("tools") or []
            if isinstance(batch, list):
                tools.extend([item for item in batch if isinstance(item, dict)])
            cursor = result.get("nextCursor") or result.get("next_cursor")
            if not cursor:
                break
        with self._lock:
            notes = list(self.notifications)
        return tools, notes

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.request("tools/call", {"name": tool_name, "arguments": arguments})
        with self._lock:
            notes = list(self.notifications)
        content = result.get("content")
        structured = result.get("structuredContent")
        empty_payload = (
            (content is None or content == [] or content == "" or content == {})
            and (structured is None or structured == {} or structured == [])
        )
        is_error = bool(result.get("isError")) or empty_payload
        payload = {
            "tool": tool_name,
            "result": result,
            "isError": is_error,
            "structuredContent": structured,
            "content": content,
            "notifications": notes,
            "protocol_version": self.protocol_version,
            "stderr_tail": "".join(self._stderr_chunks)[-2000:],
        }
        if empty_payload and not result.get("isError"):
            payload["error"] = "empty MCP tool content"
        return payload

    def close(self) -> None:
        self._closed = True
        if self.proc.poll() is not None:
            return
        try:
            self.proc.terminate()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                self.proc.kill()
            except OSError:
                pass


# Optional long-lived sessions keyed by an opaque session id (plugin-managed).
_MANAGED_SESSIONS: dict[str, McpSession] = {}
_MANAGED_LOCK = threading.Lock()


def get_managed_session(session_id: str) -> McpSession | None:
    with _MANAGED_LOCK:
        return _MANAGED_SESSIONS.get(session_id)


def start_managed_session(session_id: str, command: list[str], timeout: float = 45.0) -> dict[str, Any]:
    stop_managed_session(session_id)
    session = McpSession(resolve_command(command), timeout=timeout)
    try:
        init = session.initialize()
    except Exception:
        session.close()
        raise
    with _MANAGED_LOCK:
        _MANAGED_SESSIONS[session_id] = session
    return {"session_id": session_id, "initialize": init, "protocol_version": session.protocol_version}


def stop_managed_session(session_id: str) -> bool:
    with _MANAGED_LOCK:
        session = _MANAGED_SESSIONS.pop(session_id, None)
    if not session:
        return False
    session.close()
    return True


def resolve_command(raw: list[str]) -> list[str]:
    if not raw:
        raise SystemExit("empty command")
    first = raw[0]
    if first in {"npx", "npm", "node", "python", "python3"}:
        resolved = shutil.which(first) or shutil.which(first + ".cmd")
        if not resolved and first.startswith("python"):
            resolved = sys.executable
        if not resolved:
            raise SystemExit(f"command not found on PATH: {first}")
        return [resolved, *raw[1:]]
    if os.path.sep in first or (os.name == "nt" and "\\" in first):
        return raw
    resolved = shutil.which(first) or shutil.which(first + ".cmd")
    if not resolved:
        raise SystemExit(f"command not found on PATH: {first}")
    return [resolved, *raw[1:]]


def run_session(
    command: list[str],
    action: str,
    tool_name: str | None,
    arguments_json: str | None,
    timeout: float,
    *,
    session_id: str | None = None,
    keep_alive: bool = False,
) -> dict[str, Any]:
    if session_id and action in {"session_start"}:
        return start_managed_session(session_id, command, timeout=timeout)
    if session_id and action == "session_stop":
        return {"stopped": stop_managed_session(session_id)}

    session: McpSession | None = None
    owned = False
    if session_id:
        session = get_managed_session(session_id)
    if session is None:
        session = McpSession(resolve_command(command), timeout=timeout)
        owned = True
        session.initialize()
    try:
        if action == "list_tools":
            tools, notes = session.list_tools_all()
            return {
                "tools": tools,
                "notifications": notes,
                "protocol_version": session.protocol_version,
                "stderr_tail": "".join(session._stderr_chunks)[-2000:],
            }
        if action == "call_tool":
            if not tool_name:
                raise SystemExit("--tool is required for call_tool")
            arguments: dict[str, Any] = {}
            if arguments_json:
                loaded = json.loads(arguments_json)
                if not isinstance(loaded, dict):
                    raise SystemExit("--arguments must be a JSON object")
                arguments = loaded
            return session.call_tool(tool_name, arguments)
        raise SystemExit(f"unknown action: {action}")
    finally:
        if owned and not keep_alive:
            session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES MCP stdio bridge")
    parser.add_argument("--action", required=True, choices=["list_tools", "call_tool", "session_start", "session_stop"])
    parser.add_argument("--tool", default="")
    parser.add_argument("--arguments", default="")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--session-id", default="")
    parser.add_argument("--keep-alive", action="store_true")
    args, remainder = parser.parse_known_args()
    command = list(remainder or [])
    if command and command[0] == "--":
        command = command[1:]
    if args.action not in {"session_stop"} and not command and not args.session_id:
        raise SystemExit("MCP server command required after --")
    try:
        payload = run_session(
            command,
            args.action,
            args.tool or None,
            args.arguments or None,
            args.timeout,
            session_id=args.session_id or None,
            keep_alive=bool(args.keep_alive),
        )
    except Exception as exc:
        print(json.dumps({"error": str(exc), "isError": True}, ensure_ascii=False, indent=2))
        return 1
    is_error = bool(payload.get("isError")) or bool(payload.get("error"))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if is_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
