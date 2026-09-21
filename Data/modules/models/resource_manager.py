"""Resource preflight estimates — honest and never exact."""

from __future__ import annotations

import os
from typing import Any

from Data.modules.models.contracts import ModelDescriptor, PreflightResult, PreflightVerdict


class ResourceManager:
    """Estimates load risk when data is available. Never pretends estimates are exact."""

    def system_telemetry(self) -> dict[str, Any]:
        """Best-effort host telemetry. Omit fields that cannot be measured."""
        result: dict[str, Any] = {"available": False}
        try:
            # POSIX memory via /proc when present.
            meminfo = Path_meminfo()
            if meminfo:
                result.update(meminfo)
                result["available"] = True
        except OSError:
            pass
        # GPU/VRAM attribution is not available without a real telemetry provider.
        result.setdefault("gpu", None)
        result.setdefault("vramUsedBytes", None)
        result.setdefault("vramFreeBytes", None)
        result.setdefault("note", "GPU/VRAM telemetry unavailable without a hardware provider")
        return result

    def preflight(self, model: ModelDescriptor, *, requested_context: int | None = None) -> PreflightResult:
        telemetry = self.system_telemetry()
        reasons: list[str] = []
        details: dict[str, Any] = {
            "modelDiskSizeBytes": model.disk_size_bytes,
            "requestedContext": requested_context,
            "estimated": True,
        }

        if model.disk_size_bytes is None and telemetry.get("memAvailableBytes") is None:
            return PreflightResult(
                verdict=PreflightVerdict.UNKNOWN,
                reasons=("insufficient data for preflight",),
                estimated=True,
                details=details,
            )

        mem_available = telemetry.get("memAvailableBytes")
        if isinstance(model.disk_size_bytes, int) and isinstance(mem_available, int):
            # Extremely rough: weights + KV estimate heuristic.
            kv_estimate = None
            if requested_context:
                # Unknown architecture → do not invent precise KV; use coarse heuristic only as warning.
                kv_estimate = requested_context * 1024 * 2  # coarse bytes heuristic, labeled estimated
                details["estimatedKvCacheBytes"] = kv_estimate
            needed = model.disk_size_bytes + (kv_estimate or 0)
            details["estimatedNeededBytes"] = needed
            details["memAvailableBytes"] = mem_available
            if needed > mem_available:
                reasons.append("estimated working set exceeds available RAM")
                return PreflightResult(
                    verdict=PreflightVerdict.LIKELY_OOM,
                    reasons=tuple(reasons),
                    estimated=True,
                    details=details,
                )
            if needed > mem_available * 0.7:
                reasons.append("estimated working set is a large fraction of available RAM")
                return PreflightResult(
                    verdict=PreflightVerdict.WARNING,
                    reasons=tuple(reasons),
                    estimated=True,
                    details=details,
                )
            return PreflightResult(
                verdict=PreflightVerdict.SAFE,
                reasons=("estimate within available RAM budget",),
                estimated=True,
                details=details,
            )

        return PreflightResult(
            verdict=PreflightVerdict.UNKNOWN,
            reasons=("partial telemetry only",),
            estimated=True,
            details=details,
        )


def Path_meminfo() -> dict[str, Any] | None:
    path = "/proc/meminfo"
    if not os.path.exists(path):
        return None
    data: dict[str, int] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            parts = line.split()
            if len(parts) < 2:
                continue
            key = parts[0].rstrip(":")
            try:
                kb = int(parts[1])
            except ValueError:
                continue
            data[key] = kb * 1024
    out: dict[str, Any] = {}
    if "MemTotal" in data:
        out["memTotalBytes"] = data["MemTotal"]
    if "MemAvailable" in data:
        out["memAvailableBytes"] = data["MemAvailable"]
    return out or None
