"""model_runtime pool entrypoint — managed serving lifecycle under WorkerSupervisor."""

from __future__ import annotations

import atexit
import os

from Data.modules.workers.entrypoints._cli import main_for_pool


def _handler(ctx, job):
    executor = ctx.get("model_runtime_executor")
    if executor is None:
        from Data.modules.model_runtime.executor import ModelRuntimeExecutor

        executor = ModelRuntimeExecutor(settings=ctx.get("settings"))
        ctx["model_runtime_executor"] = executor
        atexit.register(executor.close)
        # This process is the sole managed-serving lifecycle owner.
        os.environ["LEVIATHAN_WORKER_POOL"] = "model_runtime"
        executor.bootstrap(ctx)
    ctx["worker_id"] = ctx.get("worker_id") or os.environ.get("LEVIATHAN_WORKER_ID") or (
        f"model_runtime-{os.getpid()}"
    )
    ctx["lease_ttl_seconds"] = float(
        getattr(ctx.get("worker_settings"), "lease_ttl_seconds", 60.0) or 60.0
    )
    return executor.execute_job(ctx, job)


def main(argv=None):
    os.environ.setdefault("LEVIATHAN_WORKER_POOL", "model_runtime")
    return main_for_pool("model_runtime", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
