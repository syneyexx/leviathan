"""Helpers to decide when Control Plane may enqueue model_runtime work."""

from __future__ import annotations

from typing import Any


def model_runtime_workers_ready(database_path: Any | None = None) -> bool:
    """True when the singleton model_runtime worker is READY or BUSY."""
    try:
        from Data.modules.workers.settings import load_worker_settings

        if load_worker_settings().desired_count("model_runtime") <= 0:
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
        workers = registry.list(pool_id="model_runtime")
        return any(
            w.state in {WorkerInstanceState.READY, WorkerInstanceState.BUSY}
            for w in workers
        )
    except Exception:  # noqa: BLE001
        return False


def model_runtime_readiness_snapshot(database_path: Any | None = None) -> dict[str, Any]:
    """Separate worker readiness from serving-backend / model readiness."""
    ready = model_runtime_workers_ready(database_path)
    return {
        "pool": "model_runtime",
        "state": "READY" if ready else "UNAVAILABLE",
        "truth": {
            "worker_ready_is_not_backend_ready": True,
            "worker_ready_is_not_model_loaded": True,
        },
    }
