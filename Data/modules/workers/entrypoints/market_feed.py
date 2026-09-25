"""Market feed pool entrypoint — long-lived public market streams under WorkerSupervisor.

Reuses ProviderIoExecutor / MarketStreamAdapter so network ownership stays in
provider_io adapters while the pool claim is market_feed-specific.
"""

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
        f"market_feed-{os.getpid()}"
    )
    ctx["lease_ttl_seconds"] = float(
        getattr(ctx.get("worker_settings"), "lease_ttl_seconds", 30.0) or 30.0
    )
    # Longer lease heartbeats for streaming jobs.
    cap = str(getattr(job, "capability_id", "") or "")
    if cap.startswith("provider.market.stream"):
        ctx["lease_ttl_seconds"] = max(float(ctx["lease_ttl_seconds"]), 60.0)
    return executor.execute_job(ctx, job)


def main(argv=None):
    return main_for_pool("market_feed", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
