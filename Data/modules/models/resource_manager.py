"""Resource preflight estimates — honest and never exact.

Reuses authoritative SystemTelemetrySampler when injected.
Never fabricates unknown VRAM as 0.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from Data.modules.models.contracts import (
    ModelDescriptor,
    PreflightResult,
    PreflightVerdict,
    ResourceEstimate,
    ResourceProvenance,
)


class ResourceManager:
    """Estimates load risk when data is available. Never pretends estimates are exact."""

    def __init__(
        self,
        *,
        telemetry_provider: Callable[[], dict[str, Any]] | None = None,
        min_ram_reserve_bytes: int = 1_073_741_824,  # 1 GiB policy default
        min_vram_reserve_bytes: int = 536_870_912,  # 512 MiB policy default
    ) -> None:
        self._telemetry_provider = telemetry_provider
        self.min_ram_reserve_bytes = int(min_ram_reserve_bytes)
        self.min_vram_reserve_bytes = int(min_vram_reserve_bytes)

    def set_telemetry_provider(self, provider: Callable[[], dict[str, Any]] | None) -> None:
        self._telemetry_provider = provider

    def system_telemetry(self) -> dict[str, Any]:
        """Best-effort host telemetry. Omit fields that cannot be measured."""
        if self._telemetry_provider is not None:
            try:
                sample = self._telemetry_provider()
                return self._normalize_telemetry(sample)
            except Exception:  # noqa: BLE001 — fall through to local probe
                pass
        result: dict[str, Any] = {"available": False}
        try:
            meminfo = path_meminfo()
            if meminfo:
                result.update(meminfo)
                result["available"] = True
        except OSError:
            pass
        # GPU/VRAM attribution unavailable without a real telemetry provider.
        result.setdefault("gpu", None)
        result.setdefault("vramUsedBytes", None)
        result.setdefault("vramFreeBytes", None)
        result.setdefault("vramTotalBytes", None)
        result.setdefault("note", "GPU/VRAM telemetry unavailable without a hardware provider")
        return result

    def _normalize_telemetry(self, sample: dict[str, Any]) -> dict[str, Any]:
        """Map SystemTelemetrySampler public dict → resource manager fields."""
        out: dict[str, Any] = {"available": bool(sample.get("measured") or sample.get("available"))}
        mem = sample.get("memory") if isinstance(sample.get("memory"), dict) else {}
        if mem.get("totalBytes") is not None:
            out["memTotalBytes"] = mem.get("totalBytes")
        if mem.get("availableBytes") is not None:
            out["memAvailableBytes"] = mem.get("availableBytes")
        elif mem.get("usedBytes") is not None and mem.get("totalBytes") is not None:
            out["memAvailableBytes"] = int(mem["totalBytes"]) - int(mem["usedBytes"])
        # Flat keys from some callers
        for src, dst in (
            ("memTotalBytes", "memTotalBytes"),
            ("memAvailableBytes", "memAvailableBytes"),
            ("ramTotalBytes", "memTotalBytes"),
            ("ramAvailableBytes", "memAvailableBytes"),
        ):
            if sample.get(src) is not None:
                out[dst] = sample[src]

        gpu = sample.get("gpu") if isinstance(sample.get("gpu"), dict) else {}
        devices = gpu.get("devices") if isinstance(gpu.get("devices"), list) else []
        if gpu.get("available") and devices:
            total = 0
            used = 0
            free = 0
            have_vram = False
            for device in devices:
                if not isinstance(device, dict):
                    continue
                vt = device.get("vramTotalBytes")
                vu = device.get("vramUsedBytes")
                vf = device.get("vramFreeBytes")
                if vt is not None:
                    have_vram = True
                    total += int(vt)
                if vu is not None:
                    used += int(vu)
                if vf is not None:
                    free += int(vf)
                elif vt is not None and vu is not None:
                    free += int(vt) - int(vu)
            out["gpu"] = {"available": True, "devices": devices}
            if have_vram:
                out["vramTotalBytes"] = total
                out["vramUsedBytes"] = used
                out["vramFreeBytes"] = free
            else:
                out["vramTotalBytes"] = None
                out["vramUsedBytes"] = None
                out["vramFreeBytes"] = None
        else:
            out["gpu"] = {"available": False, "devices": []}
            out["vramTotalBytes"] = None
            out["vramUsedBytes"] = None
            out["vramFreeBytes"] = None
            notes = sample.get("notes") or []
            if notes:
                out["note"] = "; ".join(str(n) for n in notes if n)
            else:
                out["note"] = "GPU/VRAM telemetry unavailable"
        return out

    def estimate(
        self,
        model: ModelDescriptor,
        *,
        requested_context: int | None = None,
    ) -> ResourceEstimate:
        telemetry = self.system_telemetry()
        reasons: list[str] = []
        details: dict[str, Any] = {
            "modelDiskSizeBytes": model.disk_size_bytes,
            "requestedContext": requested_context,
            "minRamReserveBytes": self.min_ram_reserve_bytes,
            "minVramReserveBytes": self.min_vram_reserve_bytes,
            "note": "Policy headroom values are conservative defaults, not hardware requirements",
        }

        ram_needed: int | None = None
        ram_needed_prov = ResourceProvenance.UNKNOWN
        vram_needed: int | None = None
        vram_needed_prov = ResourceProvenance.UNKNOWN

        if isinstance(model.disk_size_bytes, int):
            # Weight size is an ESTIMATE of runtime working set, not exact allocator use.
            ram_needed = int(model.disk_size_bytes)
            ram_needed_prov = ResourceProvenance.ESTIMATED
            if requested_context:
                # Coarse KV heuristic — labeled estimated, never claimed exact.
                kv = requested_context * 1024 * 2
                details["estimatedKvCacheBytes"] = kv
                details["kvProvenance"] = ResourceProvenance.ESTIMATED.value
                ram_needed += kv

        mem_available = telemetry.get("memAvailableBytes")
        ram_avail_prov = (
            ResourceProvenance.MEASURED
            if isinstance(mem_available, int)
            else ResourceProvenance.UNKNOWN
        )
        vram_available = telemetry.get("vramFreeBytes")
        vram_avail_prov = (
            ResourceProvenance.MEASURED
            if isinstance(vram_available, int)
            else ResourceProvenance.UNKNOWN
        )
        # Critical: unknown VRAM must remain None — never 0.
        if vram_available is None:
            details["vramNote"] = telemetry.get("note") or "VRAM unmeasured"

        usable_ram = None
        if isinstance(mem_available, int):
            usable_ram = max(0, mem_available - self.min_ram_reserve_bytes)
            details["usableRamBytes"] = usable_ram

        usable_vram = None
        if isinstance(vram_available, int):
            usable_vram = max(0, vram_available - self.min_vram_reserve_bytes)
            details["usableVramBytes"] = usable_vram

        verdict = PreflightVerdict.UNKNOWN
        if ram_needed is None and mem_available is None and vram_available is None:
            reasons.append("insufficient data for preflight")
            verdict = PreflightVerdict.UNKNOWN
        elif ram_needed is not None and usable_ram is not None:
            if ram_needed > usable_ram:
                reasons.append("estimated working set exceeds available RAM minus safety headroom")
                verdict = PreflightVerdict.LIKELY_OOM
            elif ram_needed > usable_ram * 0.7:
                reasons.append("estimated working set is a large fraction of available RAM")
                verdict = PreflightVerdict.WARNING
            else:
                reasons.append("estimate within available RAM budget (with headroom)")
                verdict = PreflightVerdict.SAFE
        else:
            reasons.append("partial telemetry only")
            verdict = PreflightVerdict.UNKNOWN

        details["allocatorOverhead"] = None
        details["allocatorOverheadProvenance"] = ResourceProvenance.UNKNOWN.value

        return ResourceEstimate(
            ram_needed_bytes=ram_needed,
            ram_needed_provenance=ram_needed_prov,
            vram_needed_bytes=vram_needed,
            vram_needed_provenance=vram_needed_prov,
            ram_available_bytes=mem_available if isinstance(mem_available, int) else None,
            ram_available_provenance=ram_avail_prov,
            vram_available_bytes=vram_available if isinstance(vram_available, int) else None,
            vram_available_provenance=vram_avail_prov,
            headroom_ram_bytes=self.min_ram_reserve_bytes,
            headroom_vram_bytes=self.min_vram_reserve_bytes,
            verdict=verdict,
            reasons=tuple(reasons),
            details=details,
        )

    def preflight(self, model: ModelDescriptor, *, requested_context: int | None = None) -> PreflightResult:
        estimate = self.estimate(model, requested_context=requested_context)
        return PreflightResult(
            verdict=estimate.verdict,
            reasons=estimate.reasons,
            estimated=True,
            details=estimate.public_dict(),
        )


def path_meminfo() -> dict[str, Any] | None:
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


# Backward-compatible alias used by older tests/imports
Path_meminfo = path_meminfo
