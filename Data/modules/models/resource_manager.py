"""Resource preflight, hardware inventory, and per-device placement.

Canonical model resource owner. Never treats aggregate VRAM as single-device capacity.
Reuses SystemTelemetrySampler when injected. Never fabricates unknown VRAM as 0.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from Data.modules.models.contracts import (
    ComputeDevice,
    DeploymentPlan,
    DeviceHealth,
    HardwareSnapshot,
    HostMemorySnapshot,
    LoadOptions,
    MemoryPressure,
    ModelDescriptor,
    ModelResourceProfile,
    MultiGpuCapability,
    PinMode,
    PlacementMode,
    PlacementReason,
    PreflightResult,
    PreflightVerdict,
    ResourceEstimate,
    ResourceProvenance,
    ResourceRequirement,
    ShardingMode,
)
from Data.modules.models.placement import (
    DeviceUsableCapacity,
    PlacementPlanner,
    usable_capacity_for_device,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class ResourceManager:
    """Estimates load risk and plans per-device placement. Never pretends estimates are exact."""

    def __init__(
        self,
        *,
        telemetry_provider: Callable[[], dict[str, Any]] | None = None,
        min_ram_reserve_bytes: int = 1_073_741_824,  # 1 GiB policy default
        min_vram_reserve_bytes: int = 536_870_912,  # 512 MiB policy default
        reservation_reader: Callable[[], list[dict[str, Any]]] | None = None,
        device_policy: dict[str, Any] | None = None,
        sample_ttl_seconds: float = 2.0,
    ) -> None:
        self._telemetry_provider = telemetry_provider
        self.min_ram_reserve_bytes = int(min_ram_reserve_bytes)
        self.min_vram_reserve_bytes = int(min_vram_reserve_bytes)
        self._reservation_reader = reservation_reader
        self._device_policy: dict[str, Any] = dict(device_policy or {})
        self._sample_ttl_seconds = float(sample_ttl_seconds)
        self._planner = PlacementPlanner(
            default_vram_headroom_bytes=self.min_vram_reserve_bytes,
            default_ram_headroom_bytes=self.min_ram_reserve_bytes,
        )
        self._profiles: dict[str, ModelResourceProfile] = {}
        self._profiles_lock = threading.RLock()
        self._hw_cache: HardwareSnapshot | None = None
        self._hw_cache_at: float = 0.0
        self._hw_lock = threading.RLock()

    def set_telemetry_provider(self, provider: Callable[[], dict[str, Any]] | None) -> None:
        self._telemetry_provider = provider
        with self._hw_lock:
            self._hw_cache = None

    def set_reservation_reader(self, reader: Callable[[], list[dict[str, Any]]] | None) -> None:
        self._reservation_reader = reader

    def set_device_policy(self, policy: dict[str, Any] | None) -> None:
        self._device_policy = dict(policy or {})
        with self._hw_lock:
            self._hw_cache = None

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
            else:
                # Windows / non-Linux: try psutil without inventing GPU values.
                ps_mem = _psutil_memory()
                if ps_mem:
                    result.update(ps_mem)
                    result["available"] = True
        except OSError:
            pass
        result.setdefault("gpu", None)
        result.setdefault("vramUsedBytes", None)
        result.setdefault("vramFreeBytes", None)
        result.setdefault("vramTotalBytes", None)
        result.setdefault("largestSingleDeviceTotalBytes", None)
        result.setdefault("largestSingleDeviceFreeBytes", None)
        result.setdefault("note", "GPU/VRAM telemetry unavailable without a hardware provider")
        return result

    def hardware_snapshot(self, *, force_refresh: bool = False) -> HardwareSnapshot:
        """Canonical per-device hardware inventory with short-lived sample cache."""
        now = time.monotonic()
        with self._hw_lock:
            if (
                not force_refresh
                and self._hw_cache is not None
                and (now - self._hw_cache_at) < self._sample_ttl_seconds
            ):
                return self._hw_cache
        snap = self._build_hardware_snapshot()
        with self._hw_lock:
            self._hw_cache = snap
            self._hw_cache_at = now
        return snap

    def _build_hardware_snapshot(self) -> HardwareSnapshot:
        tele = self.system_telemetry()
        notes: list[str] = []
        if tele.get("note"):
            notes.append(str(tele["note"]))

        mem_total = tele.get("memTotalBytes")
        mem_avail = tele.get("memAvailableBytes")
        mem_used = None
        if isinstance(mem_total, int) and isinstance(mem_avail, int):
            mem_used = max(0, mem_total - mem_avail)
        pressure = self._classify_ram_pressure(mem_total, mem_avail)
        host = HostMemorySnapshot(
            total_bytes=mem_total if isinstance(mem_total, int) else None,
            used_bytes=mem_used,
            available_bytes=mem_avail if isinstance(mem_avail, int) else None,
            safety_reserve_bytes=self.min_ram_reserve_bytes,
            pressure=pressure,
            provenance=(
                ResourceProvenance.MEASURED
                if isinstance(mem_avail, int)
                else ResourceProvenance.UNKNOWN
            ),
            measured_at=_utc_now(),
        )

        devices: list[ComputeDevice] = []
        gpu = tele.get("gpu") if isinstance(tele.get("gpu"), dict) else {}
        raw_devices = gpu.get("devices") if isinstance(gpu.get("devices"), list) else []
        policy = self._device_policy
        disabled = set(policy.get("disabledDeviceIds") or [])
        for raw in raw_devices:
            if not isinstance(raw, dict):
                continue
            device = self._device_from_raw(raw, disabled=disabled)
            devices.append(device)

        agg_total: int | None = None
        largest_total: int | None = None
        largest_free: int | None = None
        if devices:
            totals = [d.total_vram_bytes for d in devices if d.total_vram_bytes is not None]
            frees = [d.free_vram_bytes for d in devices if d.free_vram_bytes is not None]
            if totals:
                agg_total = sum(int(t) for t in totals)
                largest_total = max(int(t) for t in totals)
            if frees:
                largest_free = max(int(f) for f in frees)

        # Prefer explicit keys from normalize if devices empty but aggregates set.
        if agg_total is None and isinstance(tele.get("vramTotalBytes"), int):
            agg_total = int(tele["vramTotalBytes"])
        if largest_total is None and isinstance(tele.get("largestSingleDeviceTotalBytes"), int):
            largest_total = int(tele["largestSingleDeviceTotalBytes"])
        if largest_free is None and isinstance(tele.get("largestSingleDeviceFreeBytes"), int):
            largest_free = int(tele["largestSingleDeviceFreeBytes"])

        provenance = ResourceProvenance.UNKNOWN
        health = "UNKNOWN"
        if tele.get("available") and (devices or isinstance(mem_avail, int)):
            provenance = ResourceProvenance.MEASURED
            health = "OK" if devices or isinstance(mem_avail, int) else "DEGRADED"
        elif tele.get("available") is False:
            health = "DEGRADED"
            notes.append("hardware telemetry degraded or unavailable")

        age = tele.get("ageMs")
        return HardwareSnapshot(
            host_memory=host,
            devices=tuple(devices),
            aggregate_physical_vram_bytes=agg_total,
            largest_single_device_total_bytes=largest_total,
            largest_single_device_free_bytes=largest_free,
            sample_age_ms=int(age) if isinstance(age, int) else None,
            measured_at=_utc_now(),
            provenance=provenance,
            telemetry_health=health,
            notes=tuple(notes),
        )

    def _device_from_raw(self, raw: dict[str, Any], *, disabled: set[str]) -> ComputeDevice:
        ordinal = raw.get("ordinal")
        if ordinal is None:
            ordinal = raw.get("index")
        uuid_val = raw.get("uuid") or raw.get("gpuUuid")
        pci = raw.get("pciBusId") or raw.get("pci_bus_id")
        name = raw.get("name")
        # Stable identity: prefer vendor UUID, then PCI, then synthetic fallback.
        if uuid_val:
            stable = f"gpu-uuid-{uuid_val}"
        elif pci:
            stable = f"gpu-pci-{pci}"
        elif ordinal is not None and name:
            stable = f"gpu-ord-{ordinal}-{_slug(str(name))}"
        elif ordinal is not None:
            stable = f"gpu-ord-{ordinal}"
        else:
            stable = f"gpu-unknown-{_slug(str(name or 'device'))}"

        enabled = stable not in disabled
        if raw.get("enabledForNewWork") is False:
            enabled = False

        total = raw.get("vramTotalBytes")
        used = raw.get("vramUsedBytes")
        free = raw.get("vramFreeBytes")
        if free is None and isinstance(total, int) and isinstance(used, int):
            free = max(0, int(total) - int(used))

        health_raw = str(raw.get("health") or "HEALTHY" if total is not None else "UNKNOWN")
        try:
            health = DeviceHealth(health_raw)
        except ValueError:
            health = DeviceHealth.HEALTHY if total is not None else DeviceHealth.UNKNOWN

        return ComputeDevice(
            stable_device_id=stable,
            ordinal=int(ordinal) if ordinal is not None else None,
            vendor=raw.get("vendor") or _guess_vendor(name),
            name=name,
            uuid=str(uuid_val) if uuid_val else None,
            pci_bus_id=str(pci) if pci else None,
            backend=raw.get("backend") or raw.get("runtime") or "cuda",
            driver_version=raw.get("driverVersion") or raw.get("driver_version"),
            total_vram_bytes=int(total) if isinstance(total, int) else None,
            used_vram_bytes=int(used) if isinstance(used, int) else None,
            free_vram_bytes=int(free) if isinstance(free, int) else None,
            utilization_pct=raw.get("utilizationPct"),
            temperature_c=raw.get("temperatureC") if raw.get("temperatureC") is not None else raw.get("temperature"),
            power_watts=raw.get("powerWatts"),
            compute_capability=raw.get("computeCapability"),
            health=health,
            enabled_for_new_work=enabled,
            measured_at=raw.get("measuredAt") or _utc_now(),
            provenance=ResourceProvenance.MEASURED,
        )

    def _classify_ram_pressure(
        self, total: int | None, available: int | None
    ) -> MemoryPressure:
        if not isinstance(total, int) or not isinstance(available, int) or total <= 0:
            return MemoryPressure.UNKNOWN
        ratio = available / total
        usable = max(0, available - self.min_ram_reserve_bytes)
        if usable <= 0 or ratio < 0.10:
            return MemoryPressure.CRITICAL
        if ratio < 0.20 or usable < self.min_ram_reserve_bytes:
            return MemoryPressure.WARNING
        return MemoryPressure.NORMAL

    def _normalize_telemetry(self, sample: dict[str, Any]) -> dict[str, Any]:
        """Map SystemTelemetrySampler public dict → resource manager fields."""
        out: dict[str, Any] = {
            "available": bool(sample.get("measured") or sample.get("available") or sample.get("truth", {}).get("measured")),
        }
        if "ageMs" in sample:
            out["ageMs"] = sample["ageMs"]
        mem = sample.get("memory") if isinstance(sample.get("memory"), dict) else {}
        if mem.get("totalBytes") is not None:
            out["memTotalBytes"] = mem.get("totalBytes")
        if mem.get("availableBytes") is not None:
            out["memAvailableBytes"] = mem.get("availableBytes")
        elif mem.get("usedBytes") is not None and mem.get("totalBytes") is not None:
            out["memAvailableBytes"] = int(mem["totalBytes"]) - int(mem["usedBytes"])
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
        if (gpu.get("available") or devices) and devices:
            total = 0
            used = 0
            free = 0
            have_vram = False
            largest_total = 0
            largest_free = 0
            normalized_devices: list[dict[str, Any]] = []
            for device in devices:
                if not isinstance(device, dict):
                    continue
                # Preserve per-device identity fields; normalize index→ordinal.
                nd = dict(device)
                if "ordinal" not in nd and "index" in nd:
                    nd["ordinal"] = nd["index"]
                vt = nd.get("vramTotalBytes")
                vu = nd.get("vramUsedBytes")
                vf = nd.get("vramFreeBytes")
                if vt is not None:
                    have_vram = True
                    total += int(vt)
                    largest_total = max(largest_total, int(vt))
                if vu is not None:
                    used += int(vu)
                if vf is not None:
                    free += int(vf)
                    largest_free = max(largest_free, int(vf))
                elif vt is not None and vu is not None:
                    device_free = int(vt) - int(vu)
                    free += device_free
                    largest_free = max(largest_free, device_free)
                    nd["vramFreeBytes"] = device_free
                normalized_devices.append(nd)
            out["gpu"] = {"available": True, "devices": normalized_devices}
            if have_vram:
                # Aggregate is INFORMATIONAL only — never use for single-device fit.
                out["vramTotalBytes"] = total
                out["vramUsedBytes"] = used
                out["vramFreeBytes"] = free
                out["largestSingleDeviceTotalBytes"] = largest_total or None
                out["largestSingleDeviceFreeBytes"] = largest_free or None
            else:
                out["vramTotalBytes"] = None
                out["vramUsedBytes"] = None
                out["vramFreeBytes"] = None
                out["largestSingleDeviceTotalBytes"] = None
                out["largestSingleDeviceFreeBytes"] = None
        else:
            out["gpu"] = {"available": False, "devices": []}
            out["vramTotalBytes"] = None
            out["vramUsedBytes"] = None
            out["vramFreeBytes"] = None
            out["largestSingleDeviceTotalBytes"] = None
            out["largestSingleDeviceFreeBytes"] = None
            notes = sample.get("notes") or []
            if notes:
                out["note"] = "; ".join(str(n) for n in notes if n)
            else:
                out["note"] = "GPU/VRAM telemetry unavailable"
        return out

    # --- Resource profiles / requirements ---------------------------------

    def build_resource_profile(
        self,
        model: ModelDescriptor,
        *,
        requested_context: int | None = None,
        draft_vram_bytes: int | None = None,
        kv_bytes: int | None = None,
        runtime_kind: str | None = None,
    ) -> ModelResourceProfile:
        weight = model.disk_size_bytes if isinstance(model.disk_size_bytes, int) else None
        weight_prov = ResourceProvenance.ESTIMATED if weight is not None else ResourceProvenance.UNKNOWN

        # Disk size ≠ exact GPU weight allocation — provenance ESTIMATED with headroom factor.
        vram_weight = int(weight * 1.10) if weight is not None else None  # ~10% allocator overhead guess

        kv = kv_bytes
        kv_prov = ResourceProvenance.UNKNOWN
        if kv is None and requested_context:
            # Coarse KV heuristic — never claimed exact.
            kv = int(requested_context) * 1024 * 2
            kv_prov = ResourceProvenance.ESTIMATED
        elif kv is not None:
            kv_prov = ResourceProvenance.ESTIMATED

        draft = draft_vram_bytes
        draft_prov = ResourceProvenance.ESTIMATED if draft is not None else ResourceProvenance.UNKNOWN

        total_vram = None
        total_prov = ResourceProvenance.UNKNOWN
        parts = [p for p in (vram_weight, kv, draft) if p is not None]
        if parts:
            total_vram = sum(parts)
            total_prov = ResourceProvenance.ESTIMATED

        # Measured profile override when fingerprint matches.
        measured = self.get_measured_profile(model.id, runtime_kind=runtime_kind, context=requested_context)
        if measured and measured.high_water_vram_bytes is not None:
            total_vram = measured.high_water_vram_bytes
            total_prov = ResourceProvenance.MEASURED

        fp = self._profile_fingerprint(
            model_id=model.id,
            runtime_kind=runtime_kind,
            context=requested_context,
            quantization=getattr(model, "quantization", None) or (model.metadata or {}).get("quantization"),
        )
        return ModelResourceProfile(
            model_id=model.id,
            weight_bytes=weight,
            weight_provenance=weight_prov,
            allocator_overhead_bytes=int(weight * 0.10) if weight else None,
            allocator_overhead_provenance=ResourceProvenance.ESTIMATED if weight else ResourceProvenance.UNKNOWN,
            kv_cache_bytes=kv,
            kv_cache_provenance=kv_prov,
            draft_bytes=draft,
            draft_provenance=draft_prov,
            total_vram_bytes=total_vram,
            total_vram_provenance=total_prov,
            total_ram_bytes=weight,
            total_ram_provenance=weight_prov,
            fingerprint=fp,
            sample_count=measured.sample_count if measured else 0,
            high_water_vram_bytes=measured.high_water_vram_bytes if measured else None,
            details={
                "diskSizeIsNotExactVram": True,
                "requestedContext": requested_context,
                "runtimeKind": runtime_kind,
            },
        )

    def _profile_fingerprint(
        self,
        *,
        model_id: str,
        runtime_kind: str | None,
        context: int | None,
        quantization: Any,
    ) -> str:
        h = hashlib.sha256()
        for part in (model_id, runtime_kind or "", str(context or ""), str(quantization or "")):
            h.update(str(part).encode("utf-8"))
            h.update(b"\0")
        return h.hexdigest()[:24]

    def get_measured_profile(
        self,
        model_id: str,
        *,
        runtime_kind: str | None = None,
        context: int | None = None,
    ) -> ModelResourceProfile | None:
        with self._profiles_lock:
            # Exact key first, then any profile for model.
            for key, profile in self._profiles.items():
                if profile.model_id != model_id:
                    continue
                if runtime_kind and profile.details.get("runtimeKind") not in (None, runtime_kind):
                    continue
                return profile
            return self._profiles.get(model_id)

    def record_measured_footprint(
        self,
        model_id: str,
        *,
        vram_bytes: int | None,
        ram_bytes: int | None = None,
        runtime_kind: str | None = None,
        context: int | None = None,
        fingerprint: str | None = None,
    ) -> ModelResourceProfile:
        """Lifecycle-boundary measurement update — not per-token."""
        with self._profiles_lock:
            existing = self._profiles.get(fingerprint or model_id) or self._profiles.get(model_id)
            samples = (existing.sample_count if existing else 0) + 1
            high = existing.high_water_vram_bytes if existing else None
            if isinstance(vram_bytes, int):
                high = max(int(high or 0), int(vram_bytes)) if high is not None else int(vram_bytes)
            profile = ModelResourceProfile(
                model_id=model_id,
                total_vram_bytes=high,
                total_vram_provenance=ResourceProvenance.MEASURED if high is not None else ResourceProvenance.UNKNOWN,
                total_ram_bytes=ram_bytes if ram_bytes is not None else (existing.total_ram_bytes if existing else None),
                total_ram_provenance=(
                    ResourceProvenance.MEASURED
                    if ram_bytes is not None
                    else (existing.total_ram_provenance if existing else ResourceProvenance.UNKNOWN)
                ),
                fingerprint=fingerprint or (existing.fingerprint if existing else None),
                sample_count=samples,
                high_water_vram_bytes=high,
                details={
                    "runtimeKind": runtime_kind,
                    "context": context,
                    "lastMeasuredAt": _utc_now(),
                },
            )
            key = fingerprint or model_id
            self._profiles[key] = profile
            self._profiles[model_id] = profile
            return profile

    def build_requirement(
        self,
        model: ModelDescriptor,
        *,
        load_options: LoadOptions | None = None,
        runtime_kind: str | None = None,
        workload_class: str = "MODEL_INFERENCE",
        latency_class: str = "interactive",
        multi_gpu_capability: MultiGpuCapability = MultiGpuCapability.UNKNOWN,
        vram_override: int | None = None,
        draft_vram_bytes: int | None = None,
    ) -> tuple[ResourceRequirement, ModelResourceProfile]:
        ctx = load_options.context_length if load_options else None
        profile = self.build_resource_profile(
            model,
            requested_context=ctx,
            draft_vram_bytes=draft_vram_bytes,
            runtime_kind=runtime_kind,
        )
        vram = vram_override if vram_override is not None else profile.total_vram_bytes
        pin_mode = PinMode.NONE
        pinned = None
        preferred = None
        excluded = None
        sharding_allowed = False
        sharding_required = False
        cpu_offload = False
        if load_options:
            if load_options.pinned_device_ids:
                pinned = load_options.pinned_device_ids
                pin_mode = PinMode.HARD
            elif load_options.preferred_device_ids:
                preferred = load_options.preferred_device_ids
                pin_mode = PinMode.PREFERENCE
            excluded = load_options.excluded_device_ids
            if load_options.allow_multi_gpu is True:
                sharding_allowed = True
            if load_options.sharding_mode and load_options.sharding_mode != ShardingMode.NONE.value:
                sharding_allowed = True
                if multi_gpu_capability == MultiGpuCapability.SUPPORTED:
                    sharding_required = vram is not None  # may still single-fit first
            if load_options.allow_cpu_offload is True:
                cpu_offload = True
        req = ResourceRequirement(
            ram_bytes=profile.total_ram_bytes if cpu_offload else (
                # Without offload, RAM need is lighter working set heuristic.
                int(profile.total_ram_bytes * 0.25) if profile.total_ram_bytes else None
            ),
            vram_bytes=vram,
            gpu_count=1,
            preferred_device_ids=preferred,
            pinned_device_ids=pinned,
            excluded_device_ids=excluded,
            pin_mode=pin_mode,
            accelerator_type="gpu",
            shared=True,
            workload_class=workload_class,
            latency_class=latency_class,
            model_id=model.id,
            runtime_kind=runtime_kind,
            sharding_allowed=sharding_allowed,
            sharding_required=False,  # planner decides after single-fit fails
            cpu_offload_allowed=cpu_offload,
            context_length=ctx,
            draft_vram_bytes=draft_vram_bytes,
            safety_headroom_vram_bytes=self.min_vram_reserve_bytes,
            safety_headroom_ram_bytes=self.min_ram_reserve_bytes,
            provenance=profile.total_vram_provenance,
        )
        # If VRAM exceeds largest single device, mark sharding required when allowed.
        from dataclasses import replace

        hw = self.hardware_snapshot()
        if (
            sharding_allowed
            and vram is not None
            and hw.largest_single_device_total_bytes is not None
            and int(vram) > int(hw.largest_single_device_total_bytes)
        ):
            req = replace(req, sharding_allowed=True, sharding_required=True, gpu_count=2)
        return req, profile

    def device_capacities(
        self,
        hardware: HardwareSnapshot | None = None,
        *,
        reservations: list[dict[str, Any]] | None = None,
    ) -> list[DeviceUsableCapacity]:
        hw = hardware or self.hardware_snapshot()
        held = reservations
        if held is None and self._reservation_reader is not None:
            try:
                held = list(self._reservation_reader() or [])
            except Exception:  # noqa: BLE001
                held = []
        held = held or []

        by_device: dict[str, dict[str, Any]] = {}
        for row in held:
            sid = row.get("device_stable_id") or row.get("deviceStableId")
            if not sid:
                # Legacy aggregate reservation — apply to all devices conservatively for exclusive.
                if str(row.get("resource_class") or row.get("resourceClass") or "") == "GPU_EXCLUSIVE":
                    for d in hw.devices:
                        entry = by_device.setdefault(
                            d.stable_device_id,
                            {"reserved": 0, "measured": 0, "exclusive": False},
                        )
                        entry["exclusive"] = True
                continue
            entry = by_device.setdefault(sid, {"reserved": 0, "measured": 0, "exclusive": False})
            state = str(row.get("state") or "HELD").upper()
            reserved = int(row.get("reserved_vram_bytes") or row.get("reservedVramBytes") or 0)
            measured = int(row.get("measured_vram_bytes") or row.get("measuredVramBytes") or 0)
            accounting = str(row.get("accounting") or row.get("accountingMode") or "").upper()
            if accounting == "LIVE_MEASURED" or (measured > 0 and state in {"HELD", "LIVE"}):
                # Do not double-count: measured authoritative; reservation ownership only.
                entry["measured"] = max(entry["measured"], measured)
                entry["reserved"] = max(entry["reserved"], reserved)
            else:
                entry["reserved"] += reserved
            if str(row.get("resource_class") or row.get("resourceClass") or "") == "GPU_EXCLUSIVE":
                entry["exclusive"] = True

        return [
            usable_capacity_for_device(
                d,
                headroom_bytes=self.min_vram_reserve_bytes,
                reserved_bytes=int(by_device.get(d.stable_device_id, {}).get("reserved", 0)),
                measured_owned_bytes=int(by_device.get(d.stable_device_id, {}).get("measured", 0)),
                exclusive_held=bool(by_device.get(d.stable_device_id, {}).get("exclusive", False)),
            )
            for d in hw.devices
        ]

    def plan_placement(
        self,
        model: ModelDescriptor,
        *,
        load_options: LoadOptions | None = None,
        runtime_kind: str | None = None,
        multi_gpu_capability: MultiGpuCapability = MultiGpuCapability.UNKNOWN,
        workload_class: str = "MODEL_INFERENCE",
        latency_class: str = "interactive",
        vram_override: int | None = None,
        draft_vram_bytes: int | None = None,
        force_refresh_hardware: bool = False,
    ) -> DeploymentPlan:
        hw = self.hardware_snapshot(force_refresh=force_refresh_hardware)
        req, profile = self.build_requirement(
            model,
            load_options=load_options,
            runtime_kind=runtime_kind,
            workload_class=workload_class,
            latency_class=latency_class,
            multi_gpu_capability=multi_gpu_capability,
            vram_override=vram_override,
            draft_vram_bytes=draft_vram_bytes,
        )
        # If VRAM unknown but offload to CPU requested with unsafe RAM — already handled in planner.
        if req.cpu_offload_allowed and hw.host_memory.pressure == MemoryPressure.CRITICAL:
            return DeploymentPlan(
                plan_id="blocked-ram",
                model_id=model.id,
                runtime_kind=runtime_kind,
                placement_mode=PlacementMode.UNKNOWN,
                required_vram_bytes=req.vram_bytes,
                required_ram_bytes=req.ram_bytes,
                resource_profile=profile,
                multi_gpu_capability=multi_gpu_capability,
                reasons=(PlacementReason.INSUFFICIENT_RAM,),
                feasible=False,
                warnings=("Host memory pressure CRITICAL — refusing CPU offload",),
                details={"pressure": hw.host_memory.pressure.value},
            )
        caps = self.device_capacities(hw)
        return self._planner.plan(
            req,
            hw,
            capacities=caps,
            profile=profile,
            load_options=load_options,
            multi_gpu_capability=multi_gpu_capability,
            runtime_kind=runtime_kind,
        )

    def estimate(
        self,
        model: ModelDescriptor,
        *,
        requested_context: int | None = None,
    ) -> ResourceEstimate:
        """Backward-compatible estimate. Per-device truth lives in details + hardware_snapshot."""
        telemetry = self.system_telemetry()
        hw = self.hardware_snapshot()
        profile = self.build_resource_profile(model, requested_context=requested_context)
        reasons: list[str] = []
        details: dict[str, Any] = {
            "modelDiskSizeBytes": model.disk_size_bytes,
            "requestedContext": requested_context,
            "minRamReserveBytes": self.min_ram_reserve_bytes,
            "minVramReserveBytes": self.min_vram_reserve_bytes,
            "note": "Policy headroom values are conservative defaults, not hardware requirements",
            "aggregatePhysicalVramBytes": hw.aggregate_physical_vram_bytes,
            "largestSingleDeviceTotalBytes": hw.largest_single_device_total_bytes,
            "largestSingleDeviceFreeBytes": hw.largest_single_device_free_bytes,
            "deviceCount": len(hw.devices),
            "aggregateIsNotContiguous": True,
            "resourceProfile": profile.public_dict(),
            "devices": [d.public_dict() for d in hw.devices],
        }

        ram_needed = profile.total_ram_bytes
        ram_needed_prov = profile.total_ram_provenance
        vram_needed = profile.total_vram_bytes
        vram_needed_prov = profile.total_vram_provenance

        mem_available = telemetry.get("memAvailableBytes")
        ram_avail_prov = (
            ResourceProvenance.MEASURED
            if isinstance(mem_available, int)
            else ResourceProvenance.UNKNOWN
        )
        # CRITICAL: single-device free is the placement-relevant availability, not aggregate.
        vram_available = hw.largest_single_device_free_bytes
        if vram_available is None:
            vram_available = telemetry.get("vramFreeBytes")  # informational fallback
        vram_avail_prov = (
            ResourceProvenance.MEASURED
            if isinstance(vram_available, int)
            else ResourceProvenance.UNKNOWN
        )
        if vram_available is None:
            details["vramNote"] = telemetry.get("note") or "VRAM unmeasured"
        details["vramAvailabilityScope"] = "largest_single_device"

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
        elif vram_needed is not None and usable_vram is not None:
            if vram_needed > usable_vram:
                reasons.append(
                    "estimated VRAM exceeds largest single-device free VRAM minus safety headroom "
                    "(aggregate physical VRAM is not contiguous)"
                )
                verdict = PreflightVerdict.LIKELY_OOM
            elif ram_needed is not None and usable_ram is not None and ram_needed > usable_ram:
                reasons.append("estimated working set exceeds available RAM minus safety headroom")
                verdict = PreflightVerdict.LIKELY_OOM
            elif vram_needed > usable_vram * 0.7:
                reasons.append("estimated VRAM is a large fraction of largest single-device free VRAM")
                verdict = PreflightVerdict.WARNING
            else:
                reasons.append("estimate within largest single-device VRAM budget (with headroom)")
                verdict = PreflightVerdict.SAFE
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

        details["allocatorOverhead"] = profile.allocator_overhead_bytes
        details["allocatorOverheadProvenance"] = profile.allocator_overhead_provenance.value
        details["hostMemoryPressure"] = hw.host_memory.pressure.value

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

    def placement_preflight(
        self,
        model: ModelDescriptor,
        *,
        load_options: LoadOptions | None = None,
        runtime_kind: str | None = None,
        multi_gpu_capability: MultiGpuCapability = MultiGpuCapability.UNKNOWN,
        vram_override: int | None = None,
    ) -> dict[str, Any]:
        """Dry-run placement — does NOT load or reserve."""
        plan = self.plan_placement(
            model,
            load_options=load_options,
            runtime_kind=runtime_kind,
            multi_gpu_capability=multi_gpu_capability,
            vram_override=vram_override,
        )
        hw = self.hardware_snapshot()
        return {
            "feasible": plan.feasible,
            "plan": plan.public_dict(),
            "hardware": hw.public_dict(),
            "truth": {
                "didNotLoadModel": True,
                "didNotReserve": True,
                "aggregateIsNotContiguous": True,
            },
        }


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


def _psutil_memory() -> dict[str, Any] | None:
    try:
        import psutil  # type: ignore[import-untyped]
    except ImportError:
        return None
    try:
        vm = psutil.virtual_memory()
        return {
            "memTotalBytes": int(vm.total),
            "memAvailableBytes": int(vm.available),
        }
    except Exception:  # noqa: BLE001
        return None


def _slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")[:48] or "device"


def _guess_vendor(name: str | None) -> str | None:
    if not name:
        return None
    lower = name.lower()
    if "nvidia" in lower or "geforce" in lower or "rtx" in lower or "quadro" in lower or "tesla" in lower:
        return "nvidia"
    if "amd" in lower or "radeon" in lower or "instinct" in lower:
        return "amd"
    if "intel" in lower or "arc" in lower:
        return "intel"
    return None


# Backward-compatible alias used by older tests/imports
Path_meminfo = path_meminfo
