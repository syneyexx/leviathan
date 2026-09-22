"""MCP JSON-RPC protocol helpers (initialize / tools/list / tools/call)."""

from __future__ import annotations

import json
from typing import Any

from .errors import (
    MCP_PROTOCOL_ERROR,
    MCP_PROTOCOL_LIMIT_EXCEEDED,
    MCP_PROTOCOL_VERSION_MISMATCH,
    McpError,
)
from .limits import McpLimits

# MCP protocol versions we negotiate (newest first).
SUPPORTED_PROTOCOL_VERSIONS = (
    "2024-11-05",
    "2025-03-26",
)

CLIENT_INFO = {
    "name": "leviathan-mcp-bridge",
    "version": "1.0.0",
}

CLIENT_CAPABILITIES: dict[str, Any] = {
    "tools": {},
}


def encode_message(payload: dict[str, Any], *, limits: McpLimits) -> bytes:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > limits.max_message_bytes:
        raise McpError(
            MCP_PROTOCOL_LIMIT_EXCEEDED,
            f"Outbound MCP message exceeds {limits.max_message_bytes} bytes",
            details={"size": len(raw)},
        )
    return raw + b"\n"


def decode_message_line(line: bytes, *, limits: McpLimits) -> dict[str, Any]:
    if len(line) > limits.max_message_bytes:
        raise McpError(
            MCP_PROTOCOL_LIMIT_EXCEEDED,
            f"Inbound MCP message exceeds {limits.max_message_bytes} bytes",
            details={"size": len(line)},
        )
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise McpError(MCP_PROTOCOL_ERROR, f"Invalid UTF-8 in MCP message: {exc}") from exc
    text = text.strip()
    if not text:
        raise McpError(MCP_PROTOCOL_ERROR, "Empty MCP message line")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise McpError(MCP_PROTOCOL_ERROR, f"Malformed JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise McpError(MCP_PROTOCOL_ERROR, "MCP message must be a JSON object")
    return payload


def build_request(method: str, params: dict[str, Any] | None, request_id: int | str) -> dict[str, Any]:
    message: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    if params is not None:
        message["params"] = params
    return message


def build_notification(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
    }
    if params is not None:
        message["params"] = params
    return message


def build_initialize_params(*, protocol_version: str | None = None) -> dict[str, Any]:
    return {
        "protocolVersion": protocol_version or SUPPORTED_PROTOCOL_VERSIONS[0],
        "capabilities": CLIENT_CAPABILITIES,
        "clientInfo": CLIENT_INFO,
    }


def negotiate_protocol_version(server_version: str | None) -> str:
    if not server_version:
        raise McpError(
            MCP_PROTOCOL_VERSION_MISMATCH,
            "Server omitted protocolVersion during initialize",
        )
    if server_version in SUPPORTED_PROTOCOL_VERSIONS:
        return server_version
    # Accept unknown future versions that share the year-month-day shape when
    # they are lexicographically >= our oldest supported — otherwise refuse.
    if server_version >= SUPPORTED_PROTOCOL_VERSIONS[-1]:
        return server_version
    raise McpError(
        MCP_PROTOCOL_VERSION_MISMATCH,
        f"Unsupported MCP protocol version: {server_version}",
        details={"supported": list(SUPPORTED_PROTOCOL_VERSIONS)},
    )


def extract_result(payload: dict[str, Any]) -> Any:
    if "error" in payload:
        err = payload["error"]
        if isinstance(err, dict):
            message = str(err.get("message") or "MCP protocol error")
            code = err.get("code")
            raise McpError(
                MCP_PROTOCOL_ERROR,
                message,
                details={"rpc_code": code, "data": err.get("data")},
            )
        raise McpError(MCP_PROTOCOL_ERROR, str(err))
    if "result" not in payload:
        raise McpError(MCP_PROTOCOL_ERROR, "JSON-RPC response missing result/error")
    return payload["result"]


def is_notification(payload: dict[str, Any]) -> bool:
    return "id" not in payload and "method" in payload


def is_response(payload: dict[str, Any]) -> bool:
    return "id" in payload and ("result" in payload or "error" in payload)
