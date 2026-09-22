"""Structured MCP error codes — honest failure only."""

from __future__ import annotations

from typing import Any


class McpError(Exception):
    """Typed MCP failure with a stable machine-readable code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}

    def public_dict(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


MCP_SERVER_NOT_FOUND = "MCP_SERVER_NOT_FOUND"
MCP_SERVER_DISABLED = "MCP_SERVER_DISABLED"
MCP_SERVER_UNAVAILABLE = "MCP_SERVER_UNAVAILABLE"
MCP_SERVER_CONFLICT = "MCP_SERVER_CONFLICT"
MCP_CONNECT_FAILED = "MCP_CONNECT_FAILED"
MCP_INITIALIZE_FAILED = "MCP_INITIALIZE_FAILED"
MCP_PROTOCOL_ERROR = "MCP_PROTOCOL_ERROR"
MCP_PROTOCOL_VERSION_MISMATCH = "MCP_PROTOCOL_VERSION_MISMATCH"
MCP_TRANSPORT_UNSUPPORTED = "MCP_TRANSPORT_UNSUPPORTED"
MCP_TRANSPORT_DEPENDENCY_MISSING = "MCP_TRANSPORT_DEPENDENCY_MISSING"
MCP_TOOL_NOT_FOUND = "MCP_TOOL_NOT_FOUND"
MCP_TOOL_SCHEMA_INVALID = "MCP_TOOL_SCHEMA_INVALID"
MCP_TOOL_CALL_FAILED = "MCP_TOOL_CALL_FAILED"
MCP_CALL_TIMEOUT = "MCP_CALL_TIMEOUT"
MCP_CALL_CANCELLED = "MCP_CALL_CANCELLED"
MCP_PROTOCOL_LIMIT_EXCEEDED = "MCP_PROTOCOL_LIMIT_EXCEEDED"
MCP_NETWORK_BLOCKED = "MCP_NETWORK_BLOCKED"
MCP_APPROVAL_REQUIRED = "MCP_APPROVAL_REQUIRED"
MCP_ISOLATION_UNAVAILABLE = "MCP_ISOLATION_UNAVAILABLE"
MCP_CIRCUIT_OPEN = "MCP_CIRCUIT_OPEN"
MCP_FEATURE_DISABLED = "MCP_FEATURE_DISABLED"
MCP_SECRET_UNRESOLVED = "MCP_SECRET_UNRESOLVED"
