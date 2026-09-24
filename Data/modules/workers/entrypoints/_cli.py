"""Shared CLI bootstrap for pool entrypoints."""

from __future__ import annotations

import argparse
from typing import Callable

from Data.modules.workers.loop import HandlerFn, run_pool_loop


def main_for_pool(
    pool_id: str,
    *,
    handler: HandlerFn | None = None,
    argv: list[str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=f"Leviathan {pool_id} worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-jobs", type=int, default=None)
    args = parser.parse_args(argv)
    count = run_pool_loop(
        pool_id=pool_id,
        handler=handler,
        once=args.once,
        max_jobs=args.max_jobs,
    )
    print(f"[{pool_id}-worker] processed={count}", flush=True)
    return 0
