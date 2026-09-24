"""Helpers to decide when Control Plane may await provider_io workers."""

from __future__ import annotations

from typing import Any


def provider_io_workers_ready(database_path: Any | None = None) -> bool:
    """True when at least one provider_io worker is READY or BUSY in the registry."""
    try:
        from Data.modules.workers.settings import load_worker_settings

        if load_worker_settings().desired_count("provider_io") <= 0:
            return False
    except Exception:  # noqa: BLE001
        return False
    try:
        from pathlib import Path

        from Data.modules.workers.protocol import WorkerInstanceState
        from Data.modules.workers.registry import WorkerRegistry

        if database_path is None:
            from Data.backend.config import load_settings

            database_path = load_settings().database_path
        registry = WorkerRegistry(Path(database_path))
        registry.initialize()
        workers = registry.list(pool_id="provider_io")
        return any(
            w.state in {WorkerInstanceState.READY, WorkerInstanceState.BUSY}
            for w in workers
        )
    except Exception:  # noqa: BLE001
        return False
