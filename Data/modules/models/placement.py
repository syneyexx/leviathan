"""Per-device placement planner — owned by ResourceManager.

Deterministic device selection. Never treats aggregate VRAM as contiguous.
Never asks an LLM which GPU to use.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any, Sequence

from Data.modules.models.contracts import (
    ComputeDevice,
    DeploymentPlan,
    DeviceAssignment,
    DeviceHealth,
    HardwareSnapshot,
    LoadOptions,
    ModelResourceProfile,
    MultiGpuCapability,
    PinMode,
    PlacementMode,
    PlacementReason,
    ResourceRequirement,
    ShardingMode,
)


@dataclass
class DeviceUsableCapacity:
    device: ComputeDevice
    free_bytes: int | None
    reserved_bytes: int
    measured_owned_bytes: int
    usable_bytes: int | None
    exclusive: bool = False
    reasons: list[PlacementReason] = field(default_factory=list)


def _device_free(device: ComputeDevice) -> int | None:
    if device.free_vram_bytes is not None:
        return int(device.free_vram_bytes)
    if device.total_vram_bytes is not None and device.used_vram_bytes is not None:
        return max(0, int(device.total_vram_bytes) - int(device.used_vram_bytes))
    return None


def usable_capacity_for_device(
    device: ComputeDevice,
    *,
    headroom_bytes: int,
    reserved_bytes: int = 0,
    measured_owned_bytes: int = 0,
    exclusive_held: bool = False,
) -> DeviceUsableCapacity:
    """Compute allocatable VRAM without double-counting reservation + measured owned use.

    Reconciliation:
      LIVE_MEASURED: measured_owned is authoritative occupancy for LEVIATHAN-owned use;
                     reservation preserves ownership but is not added on top.
      LIVE_UNMEASURED / PENDING: reservation projects occupancy.
    """
    reasons: list[PlacementReason] = []
    if exclusive_held:
        reasons.append(PlacementReason.DEVICE_RESERVED)
    if not device.enabled_for_new_work:
        reasons.append(PlacementReason.DEVICE_DISABLED)
    if device.health == DeviceHealth.REMOVED:
        reasons.append(PlacementReason.DEVICE_UNAVAILABLE)

    free = _device_free(device)
    # Occupancy attributed to LEVIATHAN: max(reservation, measured) — never sum.
    leviathan_occupancy = max(int(reserved_bytes), int(measured_owned_bytes))
    usable: int | None = None
    if free is not None:
        # free already reflects external + owned measured use on the device.
        # If we have a pending reservation not yet reflected in free, subtract the
        # excess of reservation over measured_owned.
        pending_extra = max(0, int(reserved_bytes) - int(measured_owned_bytes))
        usable = max(0, free - pending_extra - int(headroom_bytes))
    return DeviceUsableCapacity(
        device=device,
        free_bytes=free,
        reserved_bytes=int(reserved_bytes),
        measured_owned_bytes=int(measured_owned_bytes),
        usable_bytes=usable,
        exclusive=exclusive_held,
        reasons=reasons,
    )


def _fingerprint(parts: Sequence[str]) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:24]


class PlacementPlanner:
    """Deterministic per-device placement. Aggregate VRAM is never used for single-device fit."""

    def __init__(
        self,
        *,
        default_vram_headroom_bytes: int = 536_870_912,
        default_ram_headroom_bytes: int = 1_073_741_824,
        specialist_vram_threshold_bytes: int = 4 * 1024**3,
        preserve_large_gpu: bool = True,
    ) -> None:
        self.default_vram_headroom_bytes = int(default_vram_headroom_bytes)
        self.default_ram_headroom_bytes = int(default_ram_headroom_bytes)
        self.specialist_vram_threshold_bytes = int(specialist_vram_threshold_bytes)
        self.preserve_large_gpu = bool(preserve_large_gpu)

    def plan(
        self,
        requirement: ResourceRequirement,
        hardware: HardwareSnapshot,
        *,
        capacities: Sequence[DeviceUsableCapacity] | None = None,
        profile: ModelResourceProfile | None = None,
        load_options: LoadOptions | None = None,
        multi_gpu_capability: MultiGpuCapability = MultiGpuCapability.UNKNOWN,
        runtime_kind: str | None = None,
    ) -> DeploymentPlan:
        plan_id = str(uuid.uuid4())
        reasons: list[PlacementReason] = []
        warnings: list[str] = []
        headroom_vram = (
            requirement.safety_headroom_vram_bytes
            if requirement.safety_headroom_vram_bytes is not None
            else self.default_vram_headroom_bytes
        )
        headroom_ram = (
            requirement.safety_headroom_ram_bytes
            if requirement.safety_headroom_ram_bytes is not None
            else self.default_ram_headroom_bytes
        )

        # Host RAM gate.
        ram_needed = requirement.ram_bytes
        host = hardware.host_memory
        if ram_needed is not None and host.available_bytes is not None:
            usable_ram = max(0, int(host.available_bytes) - int(headroom_ram))
            if ram_needed > usable_ram:
                reasons.append(PlacementReason.INSUFFICIENT_RAM)
                return DeploymentPlan(
                    plan_id=plan_id,
                    model_id=requirement.model_id or "",
                    runtime_kind=runtime_kind or requirement.runtime_kind,
                    placement_mode=PlacementMode.UNKNOWN,
                    required_vram_bytes=requirement.vram_bytes,
                    required_ram_bytes=ram_needed,
                    reserved_headroom_vram_bytes=headroom_vram,
                    reserved_headroom_ram_bytes=headroom_ram,
                    resource_profile=profile,
                    multi_gpu_capability=multi_gpu_capability,
                    reasons=tuple(reasons),
                    feasible=False,
                    warnings=tuple(warnings),
                    details={
                        "usableRamBytes": usable_ram,
                        "hostAvailableBytes": host.available_bytes,
                        "pressure": host.pressure.value,
                    },
                )

        # External / CPU-only paths.
        accel = (requirement.accelerator_type or "gpu").lower()
        if accel == "cpu" or not hardware.devices:
            if accel == "gpu" and requirement.vram_bytes and requirement.vram_bytes > 0:
                reasons.append(PlacementReason.NO_DEVICES)
                return DeploymentPlan(
                    plan_id=plan_id,
                    model_id=requirement.model_id or "",
                    runtime_kind=runtime_kind or requirement.runtime_kind,
                    placement_mode=PlacementMode.UNKNOWN,
                    required_vram_bytes=requirement.vram_bytes,
                    required_ram_bytes=ram_needed,
                    reasons=tuple(reasons),
                    feasible=False,
                    details={"deviceCount": 0},
                )
            reasons.append(PlacementReason.CPU_ONLY if not hardware.devices else PlacementReason.FEASIBLE)
            return DeploymentPlan(
                plan_id=plan_id,
                model_id=requirement.model_id or "",
                runtime_kind=runtime_kind or requirement.runtime_kind,
                placement_mode=PlacementMode.CPU,
                sharding_mode=ShardingMode.NONE,
                load_options=load_options,
                required_vram_bytes=requirement.vram_bytes,
                required_ram_bytes=ram_needed,
                reserved_headroom_vram_bytes=headroom_vram,
                reserved_headroom_ram_bytes=headroom_ram,
                resource_profile=profile,
                multi_gpu_capability=multi_gpu_capability,
                fingerprint=_fingerprint(
                    [requirement.model_id or "", "cpu", str(ram_needed)]
                ),
                reasons=tuple(reasons) or (PlacementReason.CPU_ONLY,),
                feasible=True,
            )

        caps = list(capacities) if capacities is not None else [
            usable_capacity_for_device(d, headroom_bytes=headroom_vram) for d in hardware.devices
        ]
        by_id = {c.device.stable_device_id: c for c in caps}

        pin_mode = requirement.pin_mode
        pinned = list(requirement.pinned_device_ids or ())
        preferred = list(requirement.preferred_device_ids or ())
        excluded = set(requirement.excluded_device_ids or ())
        acceptable = set(requirement.acceptable_device_ids) if requirement.acceptable_device_ids else None

        if load_options:
            if load_options.pinned_device_ids:
                pinned = list(load_options.pinned_device_ids)
                pin_mode = PinMode.HARD
            elif load_options.preferred_device_ids:
                preferred = list(load_options.preferred_device_ids)
                if pin_mode == PinMode.NONE:
                    pin_mode = PinMode.PREFERENCE
            if load_options.excluded_device_ids:
                excluded.update(load_options.excluded_device_ids)

        vram_needed = requirement.vram_bytes
        if vram_needed is None and profile and profile.total_vram_bytes is not None:
            vram_needed = profile.total_vram_bytes

        candidates: list[DeviceUsableCapacity] = []
        for cap in caps:
            dev = cap.device
            sid = dev.stable_device_id
            if sid in excluded:
                continue
            if acceptable is not None and sid not in acceptable:
                continue
            if not dev.enabled_for_new_work:
                continue
            if dev.health in {DeviceHealth.REMOVED}:
                continue
            if cap.exclusive:
                continue
            if pin_mode == PinMode.HARD and pinned and sid not in pinned:
                continue
            candidates.append(cap)

        if pin_mode == PinMode.HARD and pinned:
            missing = [p for p in pinned if p not in by_id]
            if missing:
                return DeploymentPlan(
                    plan_id=plan_id,
                    model_id=requirement.model_id or "",
                    runtime_kind=runtime_kind or requirement.runtime_kind,
                    placement_mode=PlacementMode.UNKNOWN,
                    required_vram_bytes=vram_needed,
                    required_ram_bytes=ram_needed,
                    multi_gpu_capability=multi_gpu_capability,
                    reasons=(PlacementReason.EXPLICIT_PIN, PlacementReason.DEVICE_UNAVAILABLE),
                    feasible=False,
                    details={"missingPinnedDeviceIds": missing},
                )
            # Restrict candidates to pinned set that remain eligible.
            candidates = [c for c in candidates if c.device.stable_device_id in pinned]
            if not candidates:
                reasons.extend([PlacementReason.EXPLICIT_PIN, PlacementReason.INSUFFICIENT_VRAM])
                return DeploymentPlan(
                    plan_id=plan_id,
                    model_id=requirement.model_id or "",
                    runtime_kind=runtime_kind or requirement.runtime_kind,
                    required_vram_bytes=vram_needed,
                    required_ram_bytes=ram_needed,
                    multi_gpu_capability=multi_gpu_capability,
                    reasons=tuple(reasons),
                    feasible=False,
                    details={"pinnedDeviceIds": pinned, "note": "hard pin cannot relocate"},
                )

        # Single-device fit — NEVER use aggregate VRAM.
        single_fit: list[DeviceUsableCapacity] = []
        if vram_needed is None:
            reasons.append(PlacementReason.UNKNOWN_RESOURCE_REQUIREMENT)
            # Without a VRAM requirement we can only place when caller allows unknown.
            # Conservative: if any enabled device exists, pick smallest for specialist packing
            # only when workload is non-interactive specialist; else refuse certainty.
            if requirement.latency_class.lower() in {"interactive", "foreground"}:
                return DeploymentPlan(
                    plan_id=plan_id,
                    model_id=requirement.model_id or "",
                    runtime_kind=runtime_kind or requirement.runtime_kind,
                    required_vram_bytes=None,
                    required_ram_bytes=ram_needed,
                    multi_gpu_capability=multi_gpu_capability,
                    reasons=tuple(reasons),
                    feasible=False,
                    warnings=("VRAM requirement unknown — refusing interactive placement certainty",),
                    details={"aggregatePhysicalVramBytes": hardware.aggregate_physical_vram_bytes},
                )
            single_fit = list(candidates)
        else:
            for cap in candidates:
                if cap.usable_bytes is None:
                    continue
                if cap.usable_bytes >= int(vram_needed):
                    single_fit.append(cap)

        if single_fit:
            chosen = self._select_single(
                single_fit,
                hardware=hardware,
                vram_needed=vram_needed,
                preferred=preferred,
                pin_mode=pin_mode,
                workload_class=requirement.workload_class,
                latency_class=requirement.latency_class,
            )
            select_reasons = list(chosen[1])
            if pin_mode == PinMode.HARD:
                select_reasons.insert(0, PlacementReason.EXPLICIT_PIN)
            cap = chosen[0]
            assignment = DeviceAssignment(
                stable_device_id=cap.device.stable_device_id,
                ordinal=cap.device.ordinal,
                reserved_vram_bytes=int(vram_needed) if vram_needed is not None else None,
                process_visible_ordinal=0,
                role="primary",
            )
            fp = _fingerprint(
                [
                    requirement.model_id or "",
                    runtime_kind or "",
                    cap.device.stable_device_id,
                    str(vram_needed),
                    ShardingMode.NONE.value,
                ]
            )
            return DeploymentPlan(
                plan_id=plan_id,
                model_id=requirement.model_id or "",
                runtime_kind=runtime_kind or requirement.runtime_kind,
                devices=(assignment,),
                placement_mode=PlacementMode.SINGLE_DEVICE,
                sharding_mode=ShardingMode.NONE,
                load_options=self._augment_options(load_options, [assignment], ShardingMode.NONE),
                required_vram_bytes=vram_needed,
                required_ram_bytes=ram_needed,
                reserved_headroom_vram_bytes=headroom_vram,
                reserved_headroom_ram_bytes=headroom_ram,
                resource_profile=profile,
                multi_gpu_capability=multi_gpu_capability,
                fingerprint=fp,
                reasons=tuple(select_reasons) or (PlacementReason.FEASIBLE,),
                feasible=True,
                warnings=tuple(warnings),
                details={
                    "largestSingleDeviceTotalBytes": hardware.largest_single_device_total_bytes,
                    "aggregatePhysicalVramBytes": hardware.aggregate_physical_vram_bytes,
                    "candidateCount": len(single_fit),
                    "usableBytesOnSelected": cap.usable_bytes,
                },
            )

        # No single-device fit. Aggregate must NOT make it fit.
        aggregate = hardware.aggregate_physical_vram_bytes
        if vram_needed is not None and aggregate is not None and int(vram_needed) <= int(aggregate):
            warnings.append(
                "Aggregate physical VRAM appears sufficient but is not contiguous single-device capacity"
            )

        want_shard = requirement.sharding_required or requirement.sharding_allowed
        if load_options and load_options.allow_multi_gpu is True:
            want_shard = True
        if load_options and load_options.sharding_mode and load_options.sharding_mode != ShardingMode.NONE.value:
            want_shard = True

        if not want_shard or multi_gpu_capability != MultiGpuCapability.SUPPORTED:
            if pin_mode == PinMode.HARD and pinned:
                reasons.append(PlacementReason.EXPLICIT_PIN)
            if want_shard and multi_gpu_capability != MultiGpuCapability.SUPPORTED:
                reasons.append(PlacementReason.SHARDING_UNSUPPORTED)
            else:
                reasons.append(PlacementReason.INSUFFICIENT_VRAM)
            return DeploymentPlan(
                plan_id=plan_id,
                model_id=requirement.model_id or "",
                runtime_kind=runtime_kind or requirement.runtime_kind,
                required_vram_bytes=vram_needed,
                required_ram_bytes=ram_needed,
                multi_gpu_capability=multi_gpu_capability,
                reasons=tuple(reasons),
                feasible=False,
                warnings=tuple(warnings),
                details={
                    "aggregatePhysicalVramBytes": aggregate,
                    "largestSingleDeviceTotalBytes": hardware.largest_single_device_total_bytes,
                    "largestSingleDeviceFreeBytes": hardware.largest_single_device_free_bytes,
                    "pinnedDeviceIds": pinned if pin_mode == PinMode.HARD else None,
                    "note": "single-device fit failed; aggregate VRAM is not contiguous allocation capacity",
                },
            )

        # Verified multi-GPU plan (backend-native only).
        multi = self._plan_multi_gpu(
            candidates=candidates,
            vram_needed=int(vram_needed or 0),
            headroom_vram=headroom_vram,
            load_options=load_options,
            multi_gpu_capability=multi_gpu_capability,
        )
        if multi is None:
            reasons.extend([PlacementReason.SHARDING_REQUIRED, PlacementReason.INSUFFICIENT_VRAM])
            return DeploymentPlan(
                plan_id=plan_id,
                model_id=requirement.model_id or "",
                runtime_kind=runtime_kind or requirement.runtime_kind,
                required_vram_bytes=vram_needed,
                required_ram_bytes=ram_needed,
                multi_gpu_capability=multi_gpu_capability,
                reasons=tuple(reasons),
                feasible=False,
                warnings=tuple(warnings),
                details={"note": "no valid per-device shard headroom"},
            )

        devices, shard_mode, tensor_split, shard_reasons = multi
        fp = _fingerprint(
            [
                requirement.model_id or "",
                runtime_kind or "",
                ",".join(d.stable_device_id for d in devices),
                str(vram_needed),
                shard_mode.value,
            ]
        )
        return DeploymentPlan(
            plan_id=plan_id,
            model_id=requirement.model_id or "",
            runtime_kind=runtime_kind or requirement.runtime_kind,
            devices=tuple(devices),
            placement_mode=PlacementMode.MULTI_DEVICE,
            sharding_mode=shard_mode,
            load_options=self._augment_options(load_options, devices, shard_mode, tensor_split),
            required_vram_bytes=vram_needed,
            required_ram_bytes=ram_needed,
            reserved_headroom_vram_bytes=headroom_vram,
            reserved_headroom_ram_bytes=headroom_ram,
            resource_profile=profile,
            multi_gpu_capability=multi_gpu_capability,
            fingerprint=fp,
            reasons=tuple(shard_reasons),
            feasible=True,
            warnings=tuple(warnings),
            details={
                "tensorSplit": list(tensor_split) if tensor_split else None,
                "aggregatePhysicalVramBytes": aggregate,
            },
        )

    def _select_single(
        self,
        fit: Sequence[DeviceUsableCapacity],
        *,
        hardware: HardwareSnapshot,
        vram_needed: int | None,
        preferred: Sequence[str],
        pin_mode: PinMode,
        workload_class: str,
        latency_class: str,
    ) -> tuple[DeviceUsableCapacity, list[PlacementReason]]:
        reasons: list[PlacementReason] = []
        # Preference first.
        if preferred:
            pref_set = set(preferred)
            preferred_fit = [c for c in fit if c.device.stable_device_id in pref_set]
            if preferred_fit:
                reasons.append(PlacementReason.PREFERRED_DEVICE)
                fit = preferred_fit

        is_specialist = (
            workload_class.upper()
            in {
                "GPU_SHARED",
                "EMBEDDING",
                "RERANK",
                "VISION",
                "DOCUMENT_AI",
                "DRAFT",
                "SPECIALIST",
            }
            or (
                vram_needed is not None
                and vram_needed <= self.specialist_vram_threshold_bytes
                and latency_class.lower() in {"background", "batch", "specialist"}
            )
        )

        # Sort: for specialists prefer smaller GPUs (packing); for interactive prefer
        # best fit that preserves largest GPU when multiple options and preserve_large_gpu.
        largest_id = None
        if hardware.devices:
            ranked = sorted(
                [d for d in hardware.devices if d.total_vram_bytes is not None],
                key=lambda d: int(d.total_vram_bytes or 0),
                reverse=True,
            )
            if ranked:
                largest_id = ranked[0].stable_device_id

        if is_specialist and self.preserve_large_gpu and len(fit) > 1 and largest_id:
            non_large = [c for c in fit if c.device.stable_device_id != largest_id]
            if non_large:
                reasons.append(PlacementReason.SPECIALIST_PACKING)
                reasons.append(PlacementReason.PRESERVE_LARGE_GPU_HEADROOM)
                fit = non_large

        def sort_key(c: DeviceUsableCapacity) -> tuple[Any, ...]:
            total = c.device.total_vram_bytes if c.device.total_vram_bytes is not None else 0
            usable = c.usable_bytes if c.usable_bytes is not None else 0
            if is_specialist:
                # Smallest sufficient device first.
                return (total, usable)
            # Best fit: least leftover that still fits; prefer larger free for interactive.
            leftover = usable - int(vram_needed or 0)
            return (leftover, -total)

        ordered = sorted(fit, key=sort_key)
        chosen = ordered[0]
        if len(fit) == 1:
            reasons.append(PlacementReason.ONLY_DEVICE_WITH_CAPACITY)
        elif PlacementReason.SPECIALIST_PACKING not in reasons:
            reasons.append(PlacementReason.FEASIBLE)
        return chosen, reasons

    def _plan_multi_gpu(
        self,
        *,
        candidates: Sequence[DeviceUsableCapacity],
        vram_needed: int,
        headroom_vram: int,
        load_options: LoadOptions | None,
        multi_gpu_capability: MultiGpuCapability,
    ) -> tuple[list[DeviceAssignment], ShardingMode, tuple[float, ...] | None, list[PlacementReason]] | None:
        if multi_gpu_capability != MultiGpuCapability.SUPPORTED:
            return None
        # Prefer devices with known usable capacity, same backend.
        usable = [c for c in candidates if c.usable_bytes is not None and c.usable_bytes > 0]
        if len(usable) < 2:
            return None
        backends = {c.device.backend for c in usable if c.device.backend}
        if len(backends) > 1:
            # Mixed vendor — refuse sharding (may still separate workloads elsewhere).
            return None

        # Uneven tensor-split proportional to usable memory, with per-device headroom already applied.
        total_usable = sum(int(c.usable_bytes or 0) for c in usable)
        if total_usable < vram_needed:
            return None

        # Cap participating devices to those that leave headroom after proportional share.
        ordered = sorted(usable, key=lambda c: int(c.usable_bytes or 0), reverse=True)
        # Use all candidates that share backend; proportions by usable.
        splits: list[float] = []
        assignments: list[DeviceAssignment] = []
        for idx, cap in enumerate(ordered):
            share = int(cap.usable_bytes or 0) / total_usable
            shard_bytes = int(vram_needed * share)
            # Require remaining usable after shard > 0 (headroom already in usable).
            if shard_bytes > int(cap.usable_bytes or 0):
                return None
            splits.append(round(share, 4))
            assignments.append(
                DeviceAssignment(
                    stable_device_id=cap.device.stable_device_id,
                    ordinal=cap.device.ordinal,
                    reserved_vram_bytes=shard_bytes,
                    process_visible_ordinal=idx,
                    role="primary" if idx == 0 else "shard",
                )
            )

        # Normalize split to sum ~1.0
        s = sum(splits) or 1.0
        tensor_split = tuple(round(x / s, 4) for x in splits)

        # vLLM-class tensor parallel typically wants near-symmetric devices — reject if ratio extreme
        # unless load_options explicitly request TENSOR_SPLIT (llama.cpp-style).
        mode = ShardingMode.TENSOR_SPLIT
        if load_options and load_options.sharding_mode:
            try:
                mode = ShardingMode(load_options.sharding_mode)
            except ValueError:
                mode = ShardingMode.TENSOR_SPLIT
        if mode == ShardingMode.TENSOR_PARALLEL:
            totals = [int(c.device.total_vram_bytes or 0) for c in ordered]
            if totals and min(totals) > 0 and (max(totals) / min(totals)) > 1.5:
                # Asymmetric pair unsafe for TP — refuse.
                return None

        reasons = [PlacementReason.SHARDING_REQUIRED, PlacementReason.FEASIBLE]
        return assignments, mode, tensor_split, reasons

    def _augment_options(
        self,
        options: LoadOptions | None,
        devices: Sequence[DeviceAssignment],
        sharding_mode: ShardingMode,
        tensor_split: tuple[float, ...] | None = None,
    ) -> LoadOptions | None:
        base = options or LoadOptions()
        main_ord = devices[0].ordinal if devices else None
        return LoadOptions(
            context_length=base.context_length,
            gpu_offload_layers=base.gpu_offload_layers,
            gpu_memory_limit_bytes=base.gpu_memory_limit_bytes,
            cpu_threads=base.cpu_threads,
            batch_size=base.batch_size,
            flash_attention=base.flash_attention,
            preferred_device_ids=base.preferred_device_ids,
            pinned_device_ids=tuple(d.stable_device_id for d in devices) if devices else base.pinned_device_ids,
            excluded_device_ids=base.excluded_device_ids,
            tensor_split=tensor_split if tensor_split is not None else base.tensor_split,
            main_gpu_ordinal=0 if sharding_mode != ShardingMode.NONE else (
                base.main_gpu_ordinal if base.main_gpu_ordinal is not None else 0
            ),
            tensor_parallel_size=(
                len(devices)
                if sharding_mode == ShardingMode.TENSOR_PARALLEL
                else base.tensor_parallel_size
            ),
            allow_multi_gpu=sharding_mode != ShardingMode.NONE,
            allow_cpu_offload=base.allow_cpu_offload,
            sharding_mode=sharding_mode.value,
        )
