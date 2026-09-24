"""Worker settings — operator-configurable pool counts and lease timings."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from .pools import POOL_CATALOG, default_pool_counts


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class WorkerSettings:
    enabled: bool = True
    supervisor_enabled: bool = True
    # When True, FastAPI must not start heavy domain daemon threads.
    externalize_api_runners: bool = True

    heartbeat_seconds: float = 5.0
    lease_ttl_seconds: float = 30.0
    poll_seconds: float = 0.5
    shutdown_grace_seconds: float = 30.0

    restart_max_attempts: int = 5
    restart_window_seconds: float = 120.0
    restart_base_backoff: float = 2.0
    restart_max_backoff: float = 60.0

    supervisor_lease_ttl_seconds: float = 20.0
    ram_headroom_mb: float = 512.0
    vram_headroom_mb: float = 256.0

    pool_counts: dict[str, int] = field(default_factory=default_pool_counts)

    def public_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "supervisor_enabled": self.supervisor_enabled,
            "externalize_api_runners": self.externalize_api_runners,
            "heartbeat_seconds": self.heartbeat_seconds,
            "lease_ttl_seconds": self.lease_ttl_seconds,
            "poll_seconds": self.poll_seconds,
            "shutdown_grace_seconds": self.shutdown_grace_seconds,
            "restart": {
                "max_attempts": self.restart_max_attempts,
                "window_seconds": self.restart_window_seconds,
                "base_backoff": self.restart_base_backoff,
                "max_backoff": self.restart_max_backoff,
            },
            "resource": {
                "ram_headroom_mb": self.ram_headroom_mb,
                "vram_headroom_mb": self.vram_headroom_mb,
            },
            "pools": dict(self.pool_counts),
        }

    def desired_count(self, pool_id: str) -> int:
        if pool_id not in POOL_CATALOG:
            return 0
        raw = int(self.pool_counts.get(pool_id, POOL_CATALOG[pool_id].default_count))
        return max(0, min(raw, POOL_CATALOG[pool_id].max_count))


def load_worker_settings() -> WorkerSettings:
    counts = default_pool_counts()
    for pool_id in POOL_CATALOG:
        env_key = f"LEVIATHAN_WORKERS_POOL_{pool_id.upper()}_COUNT"
        if env_key in os.environ:
            counts[pool_id] = _env_int(env_key, counts[pool_id])
    return WorkerSettings(
        enabled=_env_bool("LEVIATHAN_WORKERS_ENABLED", True),
        supervisor_enabled=_env_bool("LEVIATHAN_WORKERS_SUPERVISOR_ENABLED", True),
        externalize_api_runners=_env_bool("LEVIATHAN_WORKERS_EXTERNALIZE_API", True),
        heartbeat_seconds=_env_float("LEVIATHAN_WORKERS_HEARTBEAT_SECONDS", 5.0),
        lease_ttl_seconds=_env_float("LEVIATHAN_WORKERS_LEASE_TTL_SECONDS", 30.0),
        poll_seconds=_env_float("LEVIATHAN_WORKERS_POLL_SECONDS", 0.5),
        shutdown_grace_seconds=_env_float("LEVIATHAN_WORKERS_SHUTDOWN_GRACE_SECONDS", 30.0),
        restart_max_attempts=_env_int("LEVIATHAN_WORKERS_RESTART_MAX_ATTEMPTS", 5),
        restart_window_seconds=_env_float("LEVIATHAN_WORKERS_RESTART_WINDOW_SECONDS", 120.0),
        restart_base_backoff=_env_float("LEVIATHAN_WORKERS_RESTART_BASE_BACKOFF", 2.0),
        restart_max_backoff=_env_float("LEVIATHAN_WORKERS_RESTART_MAX_BACKOFF", 60.0),
        supervisor_lease_ttl_seconds=_env_float(
            "LEVIATHAN_WORKERS_SUPERVISOR_LEASE_TTL_SECONDS", 20.0
        ),
        ram_headroom_mb=_env_float("LEVIATHAN_RESOURCE_BACKGROUND_RAM_HEADROOM", 512.0),
        vram_headroom_mb=_env_float("LEVIATHAN_RESOURCE_BACKGROUND_VRAM_HEADROOM", 256.0),
        pool_counts=counts,
    )
