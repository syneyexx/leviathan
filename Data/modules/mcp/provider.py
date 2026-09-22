"""ExecutionGateway MCP provider adapter."""

from __future__ import annotations

from typing import Any

from Data.modules.execution.types import CapabilityResult, CapabilityStatus

from .bridge import McpBridge
from .errors import McpError
from .types import McpCallStatus


class McpProvider:
    """Dispatches authorized capability invokes to McpBridge.

    Constructed and attached to ExecutionGateway.mcp_executor.
    """

    def __init__(self, bridge: McpBridge) -> None:
        self.bridge = bridge

    def execute_capability(
        self,
        capability_id: str,
        arguments: dict[str, Any],
        *,
        request_id: str,
        approval_id: str | None = None,
        requested_by: str = "api",
        approved_by_user: bool | None = None,
    ) -> CapabilityResult:
        _ = approved_by_user  # audit metadata only — never authorization authority
        tool = self.bridge.store.get_tool(capability_id)
        if tool is None:
            return CapabilityResult(
                request_id=request_id,
                capability_id=capability_id,
                status=CapabilityStatus.FAILED,
                error=f"MCP tool not found for capability: {capability_id}",
                telemetry={"provider": "mcp"},
            )
        try:
            result = self.bridge.call_tool(
                tool.server_id,
                tool.external_name,
                arguments,
                capability_id=capability_id,
                requester=requested_by,
                approval_id=approval_id,
                trace_id=request_id,
                lazy_connect=True,
            )
        except McpError as exc:
            status = {
                "MCP_CALL_TIMEOUT": CapabilityStatus.TIMEOUT,
                "MCP_CALL_CANCELLED": CapabilityStatus.CANCELLED,
                "MCP_APPROVAL_REQUIRED": CapabilityStatus.REJECTED,
            }.get(exc.code, CapabilityStatus.FAILED)
            return CapabilityResult(
                request_id=request_id,
                capability_id=capability_id,
                status=status,
                error=f"{exc.code}: {exc.message}",
                telemetry={"provider": "mcp", "error_code": exc.code},
            )

        status_map = {
            McpCallStatus.COMPLETED: CapabilityStatus.COMPLETED,
            McpCallStatus.FAILED: CapabilityStatus.FAILED,
            McpCallStatus.TIMEOUT: CapabilityStatus.TIMEOUT,
            McpCallStatus.CANCELLED: CapabilityStatus.CANCELLED,
            McpCallStatus.REJECTED: CapabilityStatus.REJECTED,
        }
        return CapabilityResult(
            request_id=request_id,
            capability_id=capability_id,
            status=status_map.get(result.status, CapabilityStatus.FAILED),
            output={
                "content": result.content,
                "is_error": result.is_error,
                "truncated": result.truncated,
                "artifact_ref": result.artifact_ref,
                "truth": {
                    "mcp_output_is_observation_not_evidence": True,
                    "untrusted_external_content": True,
                },
            },
            error=result.error_message,
            telemetry={
                "provider": "mcp",
                "duration_ms": result.duration_ms,
                "error_code": result.error_code,
                "server_id": tool.server_id,
                "external_name": tool.external_name,
                "schema_hash": tool.schema_hash,
            },
        )
