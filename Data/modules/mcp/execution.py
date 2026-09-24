"""MCP tool execution worker — long tools/call ownership off the Control Plane.

Connect / handshake / tools/list / health remain Control Plane control traffic
on the McpBridge. This worker owns tools/call execution with process cleanup.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from Data.modules.jobs.states import JobState
from Data.modules.mcp.errors import McpError
from Data.modules.mcp.limits import DEFAULT_MCP_LIMITS
from Data.modules.mcp.session import McpServerSession
from Data.modules.mcp.store import McpStore
from Data.modules.mcp.types import McpCallStatus, McpServerState


class McpExecutionExecutor:
    """Ephemeral per-job MCP session for tools/call (HTTP or stdio)."""

    def __init__(self, *, db_path: str | Path | None = None) -> None:
        path = Path(
            db_path
            or os.environ.get("LEVIATHAN_DB_PATH")
            or "Data/state/leviathan.db"
        )
        self.db_path = path
        self.store = McpStore(path)
        self.store.initialize()
        allow = (os.environ.get("LEVIATHAN_NETWORK_ALLOW_OUTBOUND") or "").strip().lower()
        self.allow_outbound = allow in {"1", "true", "yes", "on"}

    def close(self) -> None:
        return None

    def execute_job(self, ctx: dict[str, Any], job: Any) -> dict[str, Any]:
        store = ctx["job_store"]
        args = dict(job.arguments or {})
        server_id = str(args.get("server_id") or "").strip()
        tool_name = str(args.get("tool_name") or "").strip()
        arguments = dict(args.get("arguments") or {})
        if not server_id or not tool_name:
            payload = {
                "status": "failed",
                "error": {
                    "code": "MCP_INVALID_REQUEST",
                    "message": "mcp.call requires server_id and tool_name",
                },
                "worker_pid": os.getpid(),
            }
            store.transition(job.job_id, JobState.FAILED, error="MCP_INVALID_REQUEST", result=payload)
            return payload

        config = self.store.get_server(server_id)
        if config is None:
            payload = {
                "status": "failed",
                "error": {"code": "MCP_SERVER_NOT_FOUND", "message": server_id},
                "worker_pid": os.getpid(),
            }
            store.transition(job.job_id, JobState.FAILED, error="MCP_SERVER_NOT_FOUND", result=payload)
            return payload

        worker_id = str(ctx.get("worker_id") or f"mcp_execution-{os.getpid()}")

        def cancel_check() -> bool:
            try:
                current = store.get(job.job_id)
            except Exception:  # noqa: BLE001
                return False
            return current is None or current.state == JobState.CANCEL_REQUESTED

        session = McpServerSession(
            config=config,
            limits=DEFAULT_MCP_LIMITS,
            allow_outbound=self.allow_outbound,
        )
        try:
            if cancel_check():
                payload = {
                    "status": "cancelled",
                    "error": {"code": "MCP_CALL_CANCELLED", "message": "Cancelled"},
                    "worker_pid": os.getpid(),
                }
                store.transition(
                    job.job_id, JobState.CANCELLED, error="MCP_CALL_CANCELLED", result=payload
                )
                return payload

            try:
                if hasattr(store, "heartbeat_lease"):
                    store.heartbeat_lease(
                        job.job_id,
                        worker_id=worker_id,
                        ttl_seconds=float(ctx.get("lease_ttl_seconds") or 30.0),
                    )
            except Exception:  # noqa: BLE001
                pass

            session.connect()
            if cancel_check():
                raise McpError("MCP_CALL_CANCELLED", "Cancelled before tool call")
            result = session.call_tool(tool_name, arguments)
            out = {
                "status": "succeeded"
                if result.status == McpCallStatus.COMPLETED
                else result.status.value.lower(),
                "content": result.content,
                "is_error": result.is_error,
                "truncated": result.truncated,
                "error_code": result.error_code,
                "error_message": result.error_message,
                "duration_ms": result.duration_ms,
                "worker_pid": os.getpid(),
                "server_id": server_id,
                "tool_name": tool_name,
            }
            if result.status == McpCallStatus.COMPLETED and not result.is_error:
                store.transition(job.job_id, JobState.COMPLETED, result=out)
            elif result.status == McpCallStatus.CANCELLED:
                store.transition(job.job_id, JobState.CANCELLED, error=result.error_code, result=out)
            elif result.status == McpCallStatus.TIMEOUT:
                store.transition(job.job_id, JobState.FAILED, error="MCP_CALL_TIMEOUT", result=out)
            else:
                store.transition(
                    job.job_id,
                    JobState.FAILED,
                    error=result.error_code or "MCP_TOOL_CALL_FAILED",
                    result=out,
                )
            return out
        except McpError as exc:
            cancelled = exc.code == "MCP_CALL_CANCELLED"
            payload = {
                "status": "cancelled" if cancelled else "failed",
                "error": {"code": exc.code, "message": exc.message},
                "worker_pid": os.getpid(),
            }
            store.transition(
                job.job_id,
                JobState.CANCELLED if cancelled else JobState.FAILED,
                error=exc.code,
                result=payload,
            )
            return payload
        finally:
            try:
                session.disconnect()
            except Exception:  # noqa: BLE001
                pass
            try:
                self.store.update_runtime_state(
                    server_id, state=McpServerState.DISCONNECTED
                )
            except Exception:  # noqa: BLE001
                pass
