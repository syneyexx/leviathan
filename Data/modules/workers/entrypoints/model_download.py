"""Model download pool entrypoint — bulk model acquisition under WorkerSupervisor."""

from __future__ import annotations

import atexit
import os

from Data.modules.workers.entrypoints._cli import main_for_pool


def _handler(ctx, job):
    executor = ctx.get("model_download_executor")
    if executor is None:
        from Data.modules.model_download.executor import ModelDownloadExecutor

        db_path = str(getattr(ctx.get("settings"), "database_path", "") or "")
        executor = ModelDownloadExecutor(db_path=db_path or None)
        ctx["model_download_executor"] = executor
        atexit.register(executor.close)
    ctx["worker_id"] = ctx.get("worker_id") or os.environ.get("LEVIATHAN_WORKER_ID") or (
        f"model_download-{os.getpid()}"
    )
    ctx["lease_ttl_seconds"] = float(
        getattr(ctx.get("worker_settings"), "lease_ttl_seconds", 60.0) or 60.0
    )
    return executor.execute_job(ctx, job)


def main(argv=None):
    return main_for_pool("model_download", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
