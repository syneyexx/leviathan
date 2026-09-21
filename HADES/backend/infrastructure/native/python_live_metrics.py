"""Python host metrics for when the native companion is offline.

Mirrors the shape of native `system.metrics` so the FINALBETA dashboard can
poll `/api/native/metrics` regardless of companion availability.
"""

from __future__ import annotations

import platform
import socket
import time
from typing import Any


def collect_python_live_metrics() -> dict[str, Any]:
    cpu_percent: float | None = None
    memory: dict[str, int] | None = None
    uptime_ms: int | None = None
    logical_cpu_count: int | None = None

    try:
        import psutil  # type: ignore

        cpu_percent = float(psutil.cpu_percent(interval=None))
        mem = psutil.virtual_memory()
        memory = {
            "total_bytes": int(mem.total),
            "available_bytes": int(mem.available),
            "used_bytes": int(mem.used),
        }
        uptime_ms = int(max(0.0, time.time() - float(psutil.boot_time())) * 1000)
        logical_cpu_count = int(psutil.cpu_count() or 0) or None
    except Exception:
        pass

    if memory is None or uptime_ms is None:
        try:
            from training.hardware_probe import collect_hardware_snapshot

            snap = collect_hardware_snapshot()
            host = snap.host
            total = host.total_ram_bytes.value
            available = host.available_ram_bytes.value
            if memory is None and isinstance(total, int) and isinstance(available, int):
                memory = {
                    "total_bytes": total,
                    "available_bytes": available,
                    "used_bytes": max(0, total - available),
                }
            if logical_cpu_count is None and isinstance(host.cpu_count.value, int):
                logical_cpu_count = int(host.cpu_count.value)
        except Exception:
            pass

    if uptime_ms is None:
        try:
            # Best-effort Windows tick counter without native companion.
            import ctypes

            uptime_ms = int(ctypes.windll.kernel32.GetTickCount64())  # type: ignore[attr-defined]
        except Exception:
            uptime_ms = None

    return {
        "active_jobs": 0,
        "cpu_percent": cpu_percent,
        "memory": memory,
        "uptime_ms": uptime_ms,
        "logical_cpu_count": logical_cpu_count,
        "hostname": socket.gethostname() or None,
        "os": f"{platform.system()} {platform.release()}".strip() or None,
        "source": "python",
    }
