"""MCP domain types — servers, tools, calls, health (DTOs only)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class McpTransportKind(str, Enum):
    STDIO = "stdio"
    HTTP = "http"
    SSE = "sse"


class McpSourceKind(str, Enum):
    CONFIG = "config"
    MODULE = "module"
    MANUAL = "manual"


class McpTrust(str, Enum):
    UNTRUSTED = "untrusted"
    MANUAL = "manual"
    TRUSTED = "trusted"


class McpServerState(str, Enum):
    DISABLED = "DISABLED"
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    READY = "READY"
    BUSY = "BUSY"
    DEGRADED = "DEGRADED"
    UNRESPONSIVE = "UNRESPONSIVE"
    ERROR = "ERROR"
    RESTARTING = "RESTARTING"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"


class McpToolAvailability(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


class McpCallStatus(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class McpIsolationKind(str, Enum):
    NONE = "none"
    SUBPROCESS = "subprocess"
    PROCESS = "process"
    CONTAINER = "container"
    SANDBOX = "sandbox"


_SAFE_ID = re.compile(r"[^a-zA-Z0-9._-]+")


def sanitize_capability_segment(value: str) -> str:
    text = (value or "").strip().lower()
    text = _SAFE_ID.sub("_", text)
    text = text.strip("._-") or "unnamed"
    return text[:128]


def mcp_capability_id(server_id: str, tool_name: str) -> str:
    return f"mcp.{sanitize_capability_segment(server_id)}.{sanitize_capability_segment(tool_name)}"


def stable_schema_hash(schema: dict[str, Any] | None) -> str:
    payload = json.dumps(schema or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_server_id(*, source_kind: McpSourceKind, source_key: str) -> str:
    key = sanitize_capability_segment(source_key)
    return f"{source_kind.value}:{key}"


@dataclass(frozen=True)
class McpServerConfig:
    """Registration is data — never a per-server Python wrapper class."""

    server_id: str
    display_name: str
    source_kind: McpSourceKind
    source_key: str
    transport: McpTransportKind
    command: str | None = None
    args: tuple[str, ...] = ()
    url: str | None = None
    cwd: str | None = None
    env_public: dict[str, str] = field(default_factory=dict)
    secret_refs: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    enabled: bool = False
    trust: McpTrust = McpTrust.UNTRUSTED
    requested_isolation: McpIsolationKind = McpIsolationKind.SUBPROCESS
    max_concurrent_calls: int = 4
    owner_module_id: str | None = None
    eager_connect: bool = False
    expand_tools: bool = True
    semantic_effects: dict[str, tuple[str, ...]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "server_id": self.server_id,
            "display_name": self.display_name,
            "source_kind": self.source_kind.value,
            "source_key": self.source_key,
            "owner_module_id": self.owner_module_id,
            "transport": self.transport.value,
            "command": self.command,
            "args": list(self.args),
            "url": self.url,
            "cwd": self.cwd,
            "env": dict(self.env_public),
            "secret_refs": {k: v for k, v in self.secret_refs.items()},
            "timeout_seconds": self.timeout_seconds,
            "enabled": self.enabled,
            "trust": self.trust.value,
            "requested_isolation": self.requested_isolation.value,
            "max_concurrent_calls": self.max_concurrent_calls,
            "eager_connect": self.eager_connect,
            "expand_tools": self.expand_tools,
            "semantic_effects": {k: list(v) for k, v in self.semantic_effects.items()},
            "metadata": self.metadata,
            "truth": {
                "secret_refs_are_not_secret_values": True,
                "discoverable_is_not_authorized": True,
            },
        }


@dataclass
class McpServerRuntime:
    server_id: str
    state: McpServerState = McpServerState.DISCONNECTED
    effective_isolation: McpIsolationKind = McpIsolationKind.SUBPROCESS
    protocol_version: str | None = None
    server_version: str | None = None
    server_name: str | None = None
    last_connected_at: str | None = None
    last_seen_at: str | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    restart_count: int = 0
    pid: int | None = None
    tool_count: int = 0
    circuit_open: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "server_id": self.server_id,
            "state": self.state.value,
            "effective_isolation": self.effective_isolation.value,
            "protocol_version": self.protocol_version,
            "server_version": self.server_version,
            "server_name": self.server_name,
            "last_connected_at": self.last_connected_at,
            "last_seen_at": self.last_seen_at,
            "last_error_code": self.last_error_code,
            "last_error_message": self.last_error_message,
            "restart_count": self.restart_count,
            "pid": self.pid,
            "tool_count": self.tool_count,
            "circuit_open": self.circuit_open,
            "truth": {
                "process_exists_is_not_health": True,
                "requested_isolation_is_not_effective_isolation": True,
            },
        }


@dataclass(frozen=True)
class McpToolRecord:
    server_id: str
    external_name: str
    capability_id: str
    description: str
    input_schema: dict[str, Any]
    schema_hash: str
    semantic_effects: tuple[str, ...]
    availability: McpToolAvailability
    first_seen_at: str
    last_seen_at: str
    server_version: str | None = None
    protocol_version: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "server_id": self.server_id,
            "external_name": self.external_name,
            "capability_id": self.capability_id,
            "description": self.description,
            "input_schema": self.input_schema,
            "schema_hash": self.schema_hash,
            "semantic_effects": list(self.semantic_effects),
            "availability": self.availability.value,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "server_version": self.server_version,
            "protocol_version": self.protocol_version,
            "provider_kind": "MCP",
        }


@dataclass(frozen=True)
class McpToolCallRecord:
    call_id: str
    trace_id: str | None
    server_id: str
    capability_id: str
    external_tool_name: str
    requester: str
    status: McpCallStatus
    duration_ms: float | None
    approval_id: str | None
    arguments_summary: str | None
    result_summary: str | None
    error_code: str | None
    error_message: str | None
    started_at: str
    finished_at: str | None
    schema_hash: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "trace_id": self.trace_id,
            "server_id": self.server_id,
            "capability_id": self.capability_id,
            "external_tool_name": self.external_tool_name,
            "requester": self.requester,
            "status": self.status.value,
            "duration_ms": self.duration_ms,
            "approval_id": self.approval_id,
            "arguments_summary": self.arguments_summary,
            "result_summary": self.result_summary,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "schema_hash": self.schema_hash,
            "truth": {"mcp_output_is_not_evidence": True},
        }


@dataclass(frozen=True)
class McpCallResult:
    status: McpCallStatus
    content: list[dict[str, Any]] | None = None
    is_error: bool = False
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: float = 0.0
    truncated: bool = False
    artifact_ref: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "content": self.content,
            "is_error": self.is_error,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "duration_ms": self.duration_ms,
            "truncated": self.truncated,
            "artifact_ref": self.artifact_ref,
            "truth": {
                "mcp_output_is_observation_not_evidence": True,
                "model_output_is_not_evidence": True,
            },
        }


@dataclass(frozen=True)
class McpHealthSummary:
    registered_servers: int
    enabled_servers: int
    connected_servers: int
    ready_servers: int
    tool_count: int
    unavailable_tools: int
    last_error: str | None
    feature_enabled: bool

    def public_dict(self) -> dict[str, Any]:
        return {
            "registered_servers": self.registered_servers,
            "enabled_servers": self.enabled_servers,
            "connected_servers": self.connected_servers,
            "ready_servers": self.ready_servers,
            "tool_count": self.tool_count,
            "unavailable_tools": self.unavailable_tools,
            "last_error": self.last_error,
            "feature_enabled": self.feature_enabled,
            "truth": {"no_fake_status": True},
        }
