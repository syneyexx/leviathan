"""Bounded per-worker process resource sampling.

Never invent metrics. Unavailable values remain None.
Do not call nvidia-smi per worker at high frequency.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Cache last sample per PID to avoid hammering /proc.
_CACHE: dict[int, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 2.0
_CPU_PRIMED: set[int] = set()


def sample_process_resources(pid: int) -> dict[str, Any]:
    """Return CPU %, RSS bytes, and optional GPU fields for a live PID.

    GPU/VRAM are only populated when process-attributed values are genuinely
    available; otherwise they stay null.
    """
    if pid <= 0:
        return _empty()
    now = time.monotonic()
    cached = _CACHE.get(pid)
    if cached is not None and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return dict(cached[1])

    out = _empty()
    try:
        import psutil  # type: ignore
    except ImportError:
        _CACHE[pid] = (now, out)
        return dict(out)

    try:
        proc = psutil.Process(int(pid))
        if not proc.is_running():
            _CACHE[pid] = (now, out)
            return dict(out)
        # First call with interval=None returns 0.0 — prime once then sample.
        if pid not in _CPU_PRIMED:
            proc.cpu_percent(interval=None)
            _CPU_PRIMED.add(pid)
            cpu = None
        else:
            cpu = float(proc.cpu_percent(interval=None))
        mem = proc.memory_info()
        out = {
            "cpu_percent": cpu,
            "rss_bytes": int(getattr(mem, "rss", 0) or 0) or None,
            "rss_mb": round(float(getattr(mem, "rss", 0) or 0) / (1024 * 1024), 2) or None,
            "gpu_percent": None,
            "vram_bytes": None,
            "vram_mb": None,
            "sampled_at": time.time(),
            "truth": {
                "gpu_null_when_unattributed": True,
                "cpu_null_until_second_sample": cpu is None,
            },
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("process sample failed pid=%s: %s", pid, exc)
        out = _empty()

    _CACHE[pid] = (now, out)
    # Bound cache size.
    if len(_CACHE) > 512:
        oldest = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:64]
        for stale_pid, _ in oldest:
            _CACHE.pop(stale_pid, None)
            _CPU_PRIMED.discard(stale_pid)
    return dict(out)


def _empty() -> dict[str, Any]:
    return {
        "cpu_percent": None,
        "rss_bytes": None,
        "rss_mb": None,
        "gpu_percent": None,
        "vram_bytes": None,
        "vram_mb": None,
        "sampled_at": None,
        "truth": {
            "gpu_null_when_unattributed": True,
            "unavailable_is_null": True,
        },
    }
