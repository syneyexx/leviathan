"""ExecutionGateway MCP provider adapter."""

from __future__ import annotations

import os
from typing import Any

from Data.modules.execution.types import CapabilityResult, CapabilityStatus

from .bridge import McpBridge
from .errors import McpError
from .types import McpCallStatus


class McpProvider:
    """Dispatches authorized capability invokes to McpBridge or mcp_execution workers.

    Live connect / handshake / tools/list / tools/call that touch network or
    spawn stdio processes execute via ``mcp_execution``. Cached server/tool
    metadata remains Control Plane.

    Contract (externalized): enqueue durable job and return QUEUED immediately.
    Never poll the job on the Control Plane / FastAPI request thread.
    Callers poll ``/api/jobs/{job_id}`` (HTTP 202 accepted pattern).
    """

    def __init__(self, bridge: McpBridge, *, job_runtime: Any | None = None) -> None:
        self.bridge = bridge
        self.job_runtime = job_runtime

    def bind_job_runtime(self, job_runtime: Any | None) -> None:
        self.job_runtime = job_runtime

    def _externalize_execution(self) -> bool:
        ext = (os.environ.get("LEVIATHAN_WORKERS_EXTERNALIZE_API") or "").strip().lower()
        if ext in {"0", "false", "no", "off"}:
            return False
        if ext in {"1", "true", "yes", "on"}:
            return True
        try:
            from Data.modules.workers.settings import load_worker_settings

            return bool(load_worker_settings().externalize_api_runners)
        except Exception:  # noqa: BLE001
            return False

    def _mcp_workers_ready(self) -> bool:
        try:
            from Data.modules.workers.settings import load_worker_settings
            from Data.modules.workers.protocol import WorkerInstanceState
            from Data.modules.workers.registry import WorkerRegistry
            from pathlib import Path

            if load_worker_settings().desired_count("mcp_execution") <= 0:
                return False
            db_path = getattr(getattr(self.job_runtime, "store", None), "path", None)
            if db_path is None:
                return False
            registry = WorkerRegistry(Path(db_path))
            registry.initialize()
            workers = registry.list(pool_id="mcp_execution")
            return any(
                w.state in {WorkerInstanceState.READY, WorkerInstanceState.BUSY}
                for w in workers
            )
        except Exception:  # noqa: BLE001
            return False

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

        use_worker = (
            self._externalize_execution()
            and self.job_runtime is not None
            and self._mcp_workers_ready()
        )
        if use_worker:
            return self._execute_via_worker(
                tool=tool,
                arguments=arguments,
                request_id=request_id,
                approval_id=approval_id,
                requested_by=requested_by,
                capability_id=capability_id,
            )

        # When externalized but workers are down: do NOT silently run long MCP
        # execution in the Control Plane.
        if self._externalize_execution() and self.job_runtime is not None:
            return CapabilityResult(
                request_id=request_id,
                capability_id=capability_id,
                status=CapabilityStatus.FAILED,
                error="PROVIDER_EXECUTION_UNAVAILABLE: mcp_execution workers unavailable",
                telemetry={
                    "provider": "mcp",
                    "error_code": "PROVIDER_EXECUTION_UNAVAILABLE",
                },
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
                "MCP_APPROVAL_REQUIRED": CapabilityStatus.APPROVAL_REQUIRED,
            }.get(exc.code, CapabilityStatus.FAILED)
            return CapabilityResult(
                request_id=request_id,
                capability_id=capability_id,
                status=status,
                error=f"{exc.code}: {exc.message}",
                telemetry={"provider": "mcp", "error_code": exc.code},
            )

        return self._result_from_bridge(result, tool=tool, request_id=request_id, capability_id=capability_id)

    def _execute_via_worker(
        self,
        *,
        tool: Any,
        arguments: dict[str, Any],
        request_id: str,
        approval_id: str | None,
        requested_by: str,
        capability_id: str,
    ) -> CapabilityResult:
        """Enqueue mcp.call and return immediately (HTTP 202 / QUEUED contract).

        Control Plane must not poll worker completion on the request thread.
        """
        job = self.job_runtime.enqueue(
            capability_id="mcp.call",
            arguments={
                "server_id": tool.server_id,
                "tool_name": tool.external_name,
                "arguments": dict(arguments),
                "capability_id": capability_id,
                "approval_id": approval_id,
                "trace_id": request_id,
            },
            requested_by=requested_by,
            worker_pool="mcp_execution",
            resource_class="NETWORK_BOUND",
            latency_class="interactive",
            domain="mcp",
            consumer="mcp_execution",
            timeout_seconds=float(getattr(tool, "timeout_seconds", None) or 60.0),
            metadata={"transport": getattr(getattr(tool, "transport", None), "value", None)},
        )
        job_id = getattr(job, "job_id", None)
        return CapabilityResult(
            request_id=request_id,
            capability_id=capability_id,
            status=CapabilityStatus.QUEUED,
            output={
                "queued": True,
                "job_id": job_id,
                "worker_pool": "mcp_execution",
                "truth": {
                    "mcp_output_is_observation_not_evidence": True,
                    "untrusted_external_content": True,
                    "executed_via": "mcp_execution",
                    "control_plane_does_not_poll_mcp_jobs": True,
                },
            },
            telemetry={
                "provider": "mcp",
                "server_id": tool.server_id,
                "external_name": tool.external_name,
                "job_id": job_id,
                "executed_via": "mcp_execution",
                "queued": True,
            },
        )

    def _result_from_bridge(
        self,
        result: Any,
        *,
        tool: Any,
        request_id: str,
        capability_id: str,
    ) -> CapabilityResult:
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
                    "executed_via": "control_plane_bridge",
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
                "executed_via": "control_plane_bridge",
            },
        )
