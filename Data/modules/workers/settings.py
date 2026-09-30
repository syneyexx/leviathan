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


def _env_csv_tuple(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    parts = tuple(p.strip() for p in raw.split(",") if p.strip())
    return parts or default


# Pools that must stay warm even when scale-to-zero is enabled.
# db_commit: serialized COMMIT_WRITE owner. scheduler: control-plane ticks.
# market_sim: paper risk / sticky paper-session owner when paper trading is active.
ESSENTIAL_WARM_POOLS: frozenset[str] = frozenset({"db_commit", "scheduler", "market_sim"})


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
    terminal_summary_seconds: float = 30.0

    # Wave 12 — 16GB RAM + 16GB/6GB VRAM host profile for ResourceAdmission.
    host_ram_mb: float = 16_384.0
    vram_primary_mb: float = 16_384.0
    vram_secondary_mb: float = 6_144.0
    # Lazy startup / scale-to-zero: pools with no queue demand stay cold.
    # Do NOT scale browser/playwright pools to zero while sticky session
    # affinity is required — keep at least one warm worker for affinity.
    scale_to_zero_enabled: bool = True
    scale_to_zero_idle_seconds: float = 120.0
    # browser/playwright: sticky session affinity.
    # model_runtime: singleton owns ServingSupervisor children — do not scale to zero.
    scale_to_zero_exempt_pools: tuple[str, ...] = ("browser", "playwright", "model_runtime")

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
            "terminal_summary_seconds": self.terminal_summary_seconds,
            "restart": {
                "max_attempts": self.restart_max_attempts,
                "window_seconds": self.restart_window_seconds,
                "base_backoff": self.restart_base_backoff,
                "max_backoff": self.restart_max_backoff,
            },
            "resource": {
                "ram_headroom_mb": self.ram_headroom_mb,
                "vram_headroom_mb": self.vram_headroom_mb,
                "host_ram_mb": self.host_ram_mb,
                "vram_primary_mb": self.vram_primary_mb,
                "vram_secondary_mb": self.vram_secondary_mb,
                "scale_to_zero_enabled": self.scale_to_zero_enabled,
                "scale_to_zero_idle_seconds": self.scale_to_zero_idle_seconds,
                "scale_to_zero_exempt_pools": list(self.scale_to_zero_exempt_pools),
                "essential_warm_pools": sorted(ESSENTIAL_WARM_POOLS),
                "pressure_profile": "16GB_RAM_16_6_VRAM",
            },
            "pools": dict(self.pool_counts),
        }

    def desired_count(self, pool_id: str) -> int:
        """Configured catalog/env desired count (before scale-to-zero demand gating)."""
        if pool_id not in POOL_CATALOG:
            return 0
        raw = int(self.pool_counts.get(pool_id, POOL_CATALOG[pool_id].default_count))
        return max(0, min(raw, POOL_CATALOG[pool_id].max_count))

    def is_scale_to_zero_eligible(self, pool_id: str) -> bool:
        """True when this pool may cold-start / scale to zero under demand gating."""
        if not self.scale_to_zero_enabled:
            return False
        if pool_id in ESSENTIAL_WARM_POOLS:
            return False
        if pool_id in self.scale_to_zero_exempt_pools:
            return False
        return pool_id in POOL_CATALOG

    def scale_to_zero_desired(
        self,
        pool_id: str,
        *,
        queued: int = 0,
        busy: int = 0,
        idle_seconds: float | None = None,
        configured: int | None = None,
    ) -> int:
        """Compute queue-aware desired count for one pool.

        Essential / exempt pools keep their configured warm count.
        Eligible cold pools scale to configured demand when queued/busy > 0,
        otherwise scale to zero after idle timeout (prevents thrashing).
        """
        cfg = self.desired_count(pool_id) if configured is None else max(0, int(configured))
        if not self.is_scale_to_zero_eligible(pool_id):
            return cfg
        if cfg <= 0:
            return 0
        demand = max(0, int(queued)) + max(0, int(busy))
        if demand > 0:
            # Meet demand without overshooting configured / max_count.
            return max(1, min(cfg, demand))
        idle = float(idle_seconds) if idle_seconds is not None else float("inf")
        if idle < float(self.scale_to_zero_idle_seconds):
            # Grace window — keep one warm worker to avoid thrash on bursty queues.
            return min(cfg, 1)
        return 0


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
        terminal_summary_seconds=_env_float(
            "LEVIATHAN_WORKERS_TERMINAL_SUMMARY_SECONDS", 30.0
        ),
        host_ram_mb=_env_float("LEVIATHAN_HOST_RAM_MB", 16_384.0),
        vram_primary_mb=_env_float("LEVIATHAN_VRAM_PRIMARY_MB", 16_384.0),
        vram_secondary_mb=_env_float("LEVIATHAN_VRAM_SECONDARY_MB", 6_144.0),
        scale_to_zero_enabled=_env_bool("LEVIATHAN_WORKERS_SCALE_TO_ZERO_ENABLED", True),
        scale_to_zero_idle_seconds=_env_float(
            "LEVIATHAN_WORKERS_SCALE_TO_ZERO_IDLE_SECONDS", 120.0
        ),
        scale_to_zero_exempt_pools=_env_csv_tuple(
            "LEVIATHAN_WORKERS_SCALE_TO_ZERO_EXEMPT_POOLS",
            ("browser", "playwright", "model_runtime"),
        ),
        pool_counts=counts,
    )
