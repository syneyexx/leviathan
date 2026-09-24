"""Scheduler worker — evaluate due schedules and enqueue only (no inline execute)."""

from __future__ import annotations

from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool
from Data.modules.workers.loop import build_minimal_job_context


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    from Data.modules.jobs.states import JobState
    from Data.modules.schedules.runner import ScheduleRunner
    from Data.modules.schedules.store import ScheduleStore

    settings = ctx["settings"]
    store = ScheduleStore(settings.database_path)
    store.initialize()
    # Enqueue-only runner: process_next disabled via wrapper
    runner = ScheduleRunner(store, jobs=ctx["job_runtime"], workflows=None)
    # Prefer enqueue_only if available
    if hasattr(runner, "tick_enqueue_only"):
        results = runner.tick_enqueue_only()
    else:
        # Fallback: tick but monkey-patch process_next away
        jobs = ctx["job_runtime"]
        original = jobs.process_next
        jobs.process_next = lambda: None  # type: ignore[method-assign]
        try:
            results = runner.tick()
        finally:
            jobs.process_next = original  # type: ignore[method-assign]
    ctx["job_store"].transition(
        job.job_id,
        JobState.COMPLETED,
        result={"fired": results},
    )
    return {"results": results}


def run_scheduler_idle_tick() -> list[dict[str, Any]]:
    """Direct tick used when no schedule.tick job is queued."""
    ctx = build_minimal_job_context()
    from Data.modules.schedules.runner import ScheduleRunner
    from Data.modules.schedules.store import ScheduleStore

    store = ScheduleStore(ctx["settings"].database_path)
    store.initialize()
    runner = ScheduleRunner(store, jobs=ctx["job_runtime"], workflows=None)
    jobs = ctx["job_runtime"]
    original = jobs.process_next
    jobs.process_next = lambda: None  # type: ignore[method-assign]
    try:
        return runner.tick()
    finally:
        jobs.process_next = original  # type: ignore[method-assign]


def main(argv: list[str] | None = None) -> int:
    # Scheduler also wakes on idle to evaluate due schedules without a job.
    import argparse
    import time

    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll", type=float, default=1.0)
    args = parser.parse_args(argv)
    if args.once:
        print(run_scheduler_idle_tick(), flush=True)
        return 0
    # Hybrid: claim schedule.tick jobs when present; otherwise idle tick.
    return main_for_pool("scheduler", handler=_handler, argv=["--once"] if False else None)


if __name__ == "__main__":
    # Persistent idle loop evaluating schedules without inline job execution.
    import signal
    import time as _time

    stop = {"f": False}

    def _s(*_a):  # noqa: ANN001
        stop["f"] = True

    signal.signal(signal.SIGINT, _s)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _s)
    while not stop["f"]:
        try:
            run_scheduler_idle_tick()
        except Exception as exc:  # noqa: BLE001
            print(f"[scheduler-worker] tick error: {exc}", flush=True)
        _time.sleep(1.0)
