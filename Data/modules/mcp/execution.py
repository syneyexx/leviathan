"""MCP tool execution worker — long tools/call ownership off the Control Plane.

Connect / handshake / tools/list / health remain Control Plane control traffic
on the McpBridge. This worker owns tools/call execution with process cleanup.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from Data.modules.jobs.leases import (
    LeaseFenceError,
    fenced_transition,
    make_lease_bound_checks,
    record_stale_lease_fence,
)
from Data.modules.jobs.states import JobState
from Data.modules.mcp.errors import McpError
from Data.modules.mcp.limits import DEFAULT_MCP_LIMITS
from Data.modules.mcp.session import McpServerSession
from Data.modules.mcp.store import McpStore
from Data.modules.mcp.types import McpCallStatus, McpServerState


class McpExecutionExecutor:
    """Ephemeral per-job MCP session for tools/call (HTTP or stdio)."""

    def __init__(self, *, db_path: str | Path | None = None) -> None:
        from Data.modules.common.database_domains import resolve_control_database_path

        path = resolve_control_database_path(explicit=db_path)
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
        capability = str(getattr(job, "capability_id", "") or "mcp.call")
        server_id = str(args.get("server_id") or "").strip()
        tool_name = str(args.get("tool_name") or "").strip()
        arguments = dict(args.get("arguments") or {})
        worker_id = str(ctx.get("worker_id") or f"mcp_execution-{os.getpid()}")

        if capability in {"mcp.connect", "mcp.list_tools"}:
            return self._execute_control_job(
                ctx,
                job,
                capability=capability,
                server_id=server_id,
                args=args,
                worker_id=worker_id,
            )

        if not server_id or not tool_name:
            payload = {
                "status": "failed",
                "error": {
                    "code": "MCP_INVALID_REQUEST",
                    "message": "mcp.call requires server_id and tool_name",
                },
                "worker_pid": os.getpid(),
            }
            fenced_transition(
                store,
                job.job_id,
                JobState.FAILED,
                worker_id=worker_id,
                ctx=ctx,
                error="MCP_INVALID_REQUEST",
                result=payload,
            )
            return payload

        config = self.store.get_server(server_id)
        if config is None:
            payload = {
                "status": "failed",
                "error": {"code": "MCP_SERVER_NOT_FOUND", "message": server_id},
                "worker_pid": os.getpid(),
            }
            fenced_transition(
                store,
                job.job_id,
                JobState.FAILED,
                worker_id=worker_id,
                ctx=ctx,
                error="MCP_SERVER_NOT_FOUND",
                result=payload,
            )
            return payload

        cancel_check, heartbeat = make_lease_bound_checks(
            ctx,
            store,
            job.job_id,
            worker_id=worker_id,
            ttl_seconds=float(ctx.get("lease_ttl_seconds") or 30.0),
        )

        # Prove lease / cancel before opening an MCP session (no side effects while unfenced).
        if cancel_check():
            current = None
            try:
                current = store.get(job.job_id)
            except Exception:  # noqa: BLE001
                current = None
            is_cancel = current is not None and current.state in {
                JobState.CANCEL_REQUESTED,
                JobState.CANCELLED,
            }
            if is_cancel:
                payload = {
                    "status": "cancelled",
                    "error": {"code": "MCP_CALL_CANCELLED", "message": "Cancelled"},
                    "worker_pid": os.getpid(),
                }
                if current.state != JobState.CANCELLED:
                    if current.state == JobState.RUNNING:
                        store.request_cancel(job.job_id, reason="Cancelled")
                    fenced_transition(
                        store,
                        job.job_id,
                        JobState.CANCELLED,
                        worker_id=worker_id,
                        ctx=ctx,
                        error="MCP_CALL_CANCELLED",
                        result=payload,
                    )
                return payload
            payload = {
                "status": "failed",
                "error": {"code": "LEASE_FENCE", "message": "lease_fence_or_cancel_unreadable"},
                "worker_pid": os.getpid(),
            }
            record_stale_lease_fence(ctx)
            fenced_transition(
                store,
                job.job_id,
                JobState.FAILED,
                worker_id=worker_id,
                ctx=ctx,
                error="LEASE_FENCE",
                result=payload,
            )
            return payload

        try:
            heartbeat()
        except LeaseFenceError as exc:
            payload = {
                "status": "failed",
                "error": {"code": "LEASE_FENCE", "message": str(exc)},
                "worker_pid": os.getpid(),
            }
            record_stale_lease_fence(ctx)
            fenced_transition(
                store,
                job.job_id,
                JobState.FAILED,
                worker_id=worker_id,
                ctx=ctx,
                error="LEASE_FENCE",
                result=payload,
            )
            return payload

        session = McpServerSession(
            config=config,
            limits=DEFAULT_MCP_LIMITS,
            allow_outbound=self.allow_outbound,
        )
        try:
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
                fenced_transition(
                    store,
                    job.job_id,
                    JobState.COMPLETED,
                    worker_id=worker_id,
                    ctx=ctx,
                    result=out,
                )
            elif result.status == McpCallStatus.CANCELLED:
                fenced_transition(
                    store,
                    job.job_id,
                    JobState.CANCELLED,
                    worker_id=worker_id,
                    ctx=ctx,
                    error=result.error_code,
                    result=out,
                )
            elif result.status == McpCallStatus.TIMEOUT:
                fenced_transition(
                    store,
                    job.job_id,
                    JobState.FAILED,
                    worker_id=worker_id,
                    ctx=ctx,
                    error="MCP_CALL_TIMEOUT",
                    result=out,
                )
            else:
                fenced_transition(
                    store,
                    job.job_id,
                    JobState.FAILED,
                    worker_id=worker_id,
                    ctx=ctx,
                    error=result.error_code or "MCP_TOOL_CALL_FAILED",
                    result=out,
                )
            return out
        except LeaseFenceError as exc:
            record_stale_lease_fence(ctx)
            return {
                "status": "failed",
                "error": {"code": "LEASE_FENCE", "message": str(exc)},
                "worker_pid": os.getpid(),
            }
        except McpError as exc:
            cancelled = exc.code == "MCP_CALL_CANCELLED"
            payload = {
                "status": "cancelled" if cancelled else "failed",
                "error": {"code": exc.code, "message": exc.message},
                "worker_pid": os.getpid(),
            }
            fenced_transition(
                store,
                job.job_id,
                JobState.CANCELLED if cancelled else JobState.FAILED,
                worker_id=worker_id,
                ctx=ctx,
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

    def _execute_control_job(
        self,
        ctx: dict[str, Any],
        job: Any,
        *,
        capability: str,
        server_id: str,
        args: dict[str, Any],
        worker_id: str,
    ) -> dict[str, Any]:
        """Live connect / tools/list — spawn/network owned by mcp_execution."""
        store = ctx["job_store"]
        if not server_id:
            payload = {
                "status": "failed",
                "error": {"code": "MCP_INVALID_REQUEST", "message": "server_id required"},
                "worker_pid": os.getpid(),
            }
            fenced_transition(
                store, job.job_id, JobState.FAILED, worker_id=worker_id, ctx=ctx,
                error="MCP_INVALID_REQUEST", result=payload,
            )
            return payload
        config = self.store.get_server(server_id)
        if config is None:
            payload = {
                "status": "failed",
                "error": {"code": "MCP_SERVER_NOT_FOUND", "message": server_id},
                "worker_pid": os.getpid(),
            }
            fenced_transition(
                store, job.job_id, JobState.FAILED, worker_id=worker_id, ctx=ctx,
                error="MCP_SERVER_NOT_FOUND", result=payload,
            )
            return payload

        cancel_check, heartbeat = make_lease_bound_checks(
            ctx, store, job.job_id, worker_id=worker_id,
            ttl_seconds=float(ctx.get("lease_ttl_seconds") or 30.0),
        )
        if cancel_check():
            payload = {
                "status": "cancelled",
                "error": {"code": "MCP_CALL_CANCELLED", "message": "Cancelled"},
                "worker_pid": os.getpid(),
            }
            fenced_transition(
                store, job.job_id, JobState.CANCELLED, worker_id=worker_id, ctx=ctx,
                error="MCP_CALL_CANCELLED", result=payload,
            )
            return payload
        try:
            heartbeat()
        except LeaseFenceError as exc:
            record_stale_lease_fence(ctx)
            payload = {
                "status": "failed",
                "error": {"code": "LEASE_FENCE", "message": str(exc)},
                "worker_pid": os.getpid(),
            }
            fenced_transition(
                store, job.job_id, JobState.FAILED, worker_id=worker_id, ctx=ctx,
                error="LEASE_FENCE", result=payload,
            )
            return payload

        session = McpServerSession(
            config=config,
            limits=DEFAULT_MCP_LIMITS,
            allow_outbound=self.allow_outbound,
        )
        try:
            runtime = session.connect()
            tools: list[dict[str, Any]] = []
            if capability == "mcp.list_tools" or bool(args.get("expand_tools", True)):
                listed = session.list_tools(force_refresh=bool(args.get("force_refresh", True)))
                for tool in listed or []:
                    if hasattr(tool, "public_dict"):
                        tools.append(tool.public_dict())
                    elif isinstance(tool, dict):
                        tools.append(tool)
                    else:
                        tools.append({"name": getattr(tool, "name", str(tool))})
            out = {
                "status": "succeeded",
                "server_id": server_id,
                "runtime": runtime.public_dict() if hasattr(runtime, "public_dict") else {
                    "server_id": server_id,
                    "state": getattr(getattr(runtime, "state", None), "value", None),
                    "pid": getattr(runtime, "pid", None),
                },
                "tools": tools,
                "tool_count": len(tools),
                "worker_pid": os.getpid(),
                "capability_id": capability,
            }
            self.store.update_runtime_state(
                server_id,
                state=getattr(runtime, "state", McpServerState.READY),
                connected=True,
                seen=True,
            )
            fenced_transition(
                store, job.job_id, JobState.COMPLETED, worker_id=worker_id, ctx=ctx, result=out,
            )
            return out
        except McpError as exc:
            payload = {
                "status": "failed",
                "error": {"code": exc.code, "message": exc.message},
                "worker_pid": os.getpid(),
            }
            fenced_transition(
                store, job.job_id, JobState.FAILED, worker_id=worker_id, ctx=ctx,
                error=exc.code, result=payload,
            )
            return payload
        finally:
            try:
                session.disconnect()
            except Exception:  # noqa: BLE001
                pass
            try:
                self.store.update_runtime_state(server_id, state=McpServerState.DISCONNECTED)
            except Exception:  # noqa: BLE001
                pass
