"""MCP execution pool entrypoint — long tools/call under WorkerSupervisor."""

from __future__ import annotations

import atexit
import os

from Data.modules.workers.entrypoints._cli import main_for_pool


def _handler(ctx, job):
    executor = ctx.get("mcp_execution_executor")
    if executor is None:
        from Data.modules.mcp.execution import McpExecutionExecutor

        db_path = str(getattr(ctx.get("settings"), "database_path", "") or "")
        executor = McpExecutionExecutor(db_path=db_path or None)
        ctx["mcp_execution_executor"] = executor
        atexit.register(executor.close)
    ctx["worker_id"] = ctx.get("worker_id") or os.environ.get("LEVIATHAN_WORKER_ID") or (
        f"mcp_execution-{os.getpid()}"
    )
    ctx["lease_ttl_seconds"] = float(
        getattr(ctx.get("worker_settings"), "lease_ttl_seconds", 30.0) or 30.0
    )
    return executor.execute_job(ctx, job)


def main(argv=None):
    return main_for_pool("mcp_execution", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
