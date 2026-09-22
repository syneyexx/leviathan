"""Bounded MCP protocol / transport limits."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class McpLimits:
    max_message_bytes: int = 1_048_576  # 1 MiB
    max_tool_schema_bytes: int = 262_144  # 256 KiB
    max_tool_result_bytes: int = 1_048_576
    max_stderr_capture_bytes: int = 65_536
    max_tools_per_server: int = 512
    max_concurrent_calls_per_server: int = 8
    max_restart_attempts: int = 5
    restart_window_seconds: float = 120.0
    startup_timeout_seconds: float = 30.0
    shutdown_timeout_seconds: float = 10.0
    circuit_open_seconds: float = 60.0
    result_summary_chars: int = 2_000
    arguments_summary_chars: int = 512


DEFAULT_MCP_LIMITS = McpLimits()
