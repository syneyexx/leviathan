"""Provider I/O pool entrypoint — external API execution under WorkerSupervisor."""

from __future__ import annotations

import atexit
import os

from Data.modules.workers.entrypoints._cli import main_for_pool


def _handler(ctx, job):
    executor = ctx.get("provider_io_executor")
    if executor is None:
        from Data.modules.provider_io.executor import ProviderIoExecutor

        db_path = str(getattr(ctx.get("settings"), "database_path", "") or "")
        executor = ProviderIoExecutor(db_path=db_path or None)
        ctx["provider_io_executor"] = executor
        atexit.register(executor.close)
    ctx["worker_id"] = ctx.get("worker_id") or os.environ.get("LEVIATHAN_WORKER_ID") or (
        f"provider_io-{os.getpid()}"
    )
    ctx["lease_ttl_seconds"] = float(
        getattr(ctx.get("worker_settings"), "lease_ttl_seconds", 30.0) or 30.0
    )
    return executor.execute_job(ctx, job)


def main(argv=None):
    return main_for_pool("provider_io", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
