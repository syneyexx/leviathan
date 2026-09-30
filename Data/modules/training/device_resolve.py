"""Map operator-selected stable GPU IDs to launch-time CUDA ordinals.

Only single-device training is implemented. Multi-GPU selections are rejected
rather than silently narrowed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping

from .config import TrainingConfig
from .types import GpuDeviceInfo, HardwareSnapshot


class DeviceResolutionError(RuntimeError):
    def __init__(self, message: str, *, code: str = "TRAINING_DEVICE_UNAVAILABLE") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DeviceSelection:
    strategy: str
    requested_stable_ids: tuple[str, ...]
    device: GpuDeviceInfo | None
    auto_selected: bool
    reason: str
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    candidates: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def ordinals(self) -> list[int]:
        return [self.device.index] if self.device is not None else []

    @property
    def stable_device_ids(self) -> list[str]:
        return [self.device.stable_device_id] if self.device is not None else []

    def public_dict(self) -> dict[str, Any]:
        dev = self.device
        return {
            "strategy": self.strategy,
            "requestedStableDeviceIds": list(self.requested_stable_ids),
            "stableDeviceId": dev.stable_device_id if dev else None,
            "ordinal": dev.index if dev else None,
            "name": dev.name if dev else None,
            "uuid": dev.uuid if dev else None,
            "totalVramBytes": dev.total_vram_bytes if dev else None,
            "freeVramBytes": dev.free_vram_bytes if dev else None,
            "computeCapability": dev.compute_capability if dev else None,
            "probeSource": dev.probe_source if dev else None,
            "autoSelected": self.auto_selected,
            "reason": self.reason,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "candidates": list(self.candidates),
        }


def _matches(gpu: GpuDeviceInfo, wanted: str) -> bool:
    key = wanted.strip().lower()
    if not key:
        return False
    if gpu.stable_device_id and gpu.stable_device_id.lower() == key:
        return True
    if gpu.uuid and gpu.uuid.lower() == key:
        return True
    return False


def _gib(value: int | None) -> str:
    if value is None:
        return "unmeasured"
    return f"{value / 1024**3:.1f} GiB"


def select_training_device(config: TrainingConfig, hardware: HardwareSnapshot) -> DeviceSelection:
    strategy = (config.device_strategy or "auto").strip().lower()
    requested = tuple(str(x) for x in (config.selected_stable_device_ids or []) if str(x).strip())
    gpus = list(hardware.gpus)
    candidates = tuple(
        {
            "stableDeviceId": g.stable_device_id,
            "ordinal": g.index,
            "name": g.name,
            "freeVramBytes": g.free_vram_bytes,
            "totalVramBytes": g.total_vram_bytes,
        }
        for g in gpus
    )

    if len(requested) > 1:
        return DeviceSelection(
            strategy=strategy,
            requested_stable_ids=requested,
            device=None,
            auto_selected=False,
            reason="multi-GPU selection rejected",
            errors=("multi-GPU training is not implemented — select exactly one device",),
            candidates=candidates,
        )

    if requested:
        wanted = requested[0]
        match = next((g for g in gpus if _matches(g, wanted)), None)
        if match is None:
            known = ", ".join(g.stable_device_id for g in gpus) or "none detected"
            return DeviceSelection(
                strategy="single",
                requested_stable_ids=requested,
                device=None,
                auto_selected=False,
                reason="selected device not present",
                errors=(f"selected device {wanted!r} not found (available: {known})",),
                candidates=candidates,
            )
        return DeviceSelection(
            strategy="single",
            requested_stable_ids=requested,
            device=match,
            auto_selected=False,
            reason=f"operator selected {match.stable_device_id} ({match.name})",
            candidates=candidates,
        )

    if not gpus:
        return DeviceSelection(
            strategy="cpu",
            requested_stable_ids=(),
            device=None,
            auto_selected=True,
            reason="no GPU measured — CPU execution",
            candidates=candidates,
        )

    measured = [g for g in gpus if g.free_vram_bytes is not None]
    warnings: list[str] = []
    if measured:
        best = sorted(measured, key=lambda g: (-int(g.free_vram_bytes or 0), g.index))[0]
        reason = (
            f"auto: highest free VRAM ({_gib(best.free_vram_bytes)}) among {len(gpus)} GPU(s) — "
            f"{best.stable_device_id} ({best.name})"
        )
    else:
        best = sorted(gpus, key=lambda g: g.index)[0]
        reason = f"auto: free VRAM unmeasured; lowest ordinal {best.index} ({best.name})"
        warnings.append("free VRAM unmeasured — device picked by ordinal")
    if strategy == "single":
        warnings.append("device_strategy=single without selected_stable_device_ids — auto-picked one device")
    return DeviceSelection(
        strategy="single",
        requested_stable_ids=(),
        device=best,
        auto_selected=True,
        reason=reason,
        warnings=tuple(warnings),
        candidates=candidates,
    )


def resolve_training_devices(config: TrainingConfig, hardware: HardwareSnapshot) -> list[int]:
    """Return launch ordinals for the selected device(s); raises when unresolvable."""
    selection = select_training_device(config, hardware)
    if not selection.ok:
        raise DeviceResolutionError("; ".join(selection.errors))
    return selection.ordinals


def build_device_env(
    selection: DeviceSelection,
    *,
    host_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """CUDA env for the trainer child so the selected device becomes ``cuda:0``."""
    dev = selection.device
    if dev is None:
        return {}
    source_env = dict(host_env if host_env is not None else os.environ)
    if dev.probe_source == "torch":
        # torch ordinals are relative to the probing process' visible device list.
        host_visible = [x.strip() for x in (source_env.get("CUDA_VISIBLE_DEVICES") or "").split(",") if x.strip()]
        if host_visible and dev.index < len(host_visible):
            value = host_visible[dev.index]
        elif dev.uuid:
            value = dev.uuid
        else:
            value = str(dev.index)
        env = {"CUDA_VISIBLE_DEVICES": value}
        if source_env.get("CUDA_DEVICE_ORDER"):
            env["CUDA_DEVICE_ORDER"] = str(source_env["CUDA_DEVICE_ORDER"])
        return env
    # nvidia-smi enumerates in PCI bus order; pin CUDA to the same order.
    return {"CUDA_VISIBLE_DEVICES": str(dev.index), "CUDA_DEVICE_ORDER": "PCI_BUS_ID"}
