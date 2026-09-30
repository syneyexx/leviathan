"""Honest hardware discovery — never invent GPU/VRAM figures."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .capabilities import safe_import
from .types import GpuDeviceInfo, HardwareSnapshot


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _meminfo() -> dict[str, int]:
    path = Path("/proc/meminfo")
    if not path.exists():
        return {}
    data: dict[str, int] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            key = parts[0].rstrip(":")
            try:
                data[key] = int(parts[1]) * 1024
            except ValueError:
                continue
    except OSError:
        return {}
    return data


def _cpu_model() -> str | None:
    path = Path("/proc/cpuinfo")
    if path.exists():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
        except OSError:
            pass
    return platform.processor() or platform.machine() or None


def _disk_free(path: Path) -> int | None:
    try:
        usage = shutil.disk_usage(path)
        return int(usage.free)
    except OSError:
        return None


def _slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")[:48] or "device"


def stable_device_id_for(
    *,
    uuid: str | None,
    pci_bus_id: str | None,
    ordinal: int | None,
    name: str | None,
) -> str:
    """Stable GPU identity — same scheme as ``models.resource_manager`` / admission."""
    if uuid:
        return f"gpu-uuid-{uuid}"
    if pci_bus_id:
        return f"gpu-pci-{pci_bus_id}"
    if ordinal is not None and name:
        return f"gpu-ord-{ordinal}-{_slug(str(name))}"
    if ordinal is not None:
        return f"gpu-ord-{ordinal}"
    return f"gpu-unknown-{_slug(str(name or 'device'))}"


def _probe_nvidia_smi() -> tuple[list[GpuDeviceInfo], str | None, list[str]]:
    """Best-effort nvidia-smi probe. Empty when unavailable — never fabricates."""
    from Data.modules.observability.system_telemetry import probe_nvidia_smi

    samples, notes = probe_nvidia_smi(which=shutil.which, runner=subprocess.run, timeout=5.0)
    gpus: list[GpuDeviceInfo] = []
    driver: str | None = None
    for sample in samples:
        driver = sample.driver_version or driver
        gpus.append(
            GpuDeviceInfo(
                index=sample.index,
                name=sample.name,
                total_vram_bytes=sample.vram_total_bytes,
                free_vram_bytes=sample.vram_free_bytes,
                used_vram_bytes=sample.vram_used_bytes,
                stable_device_id=stable_device_id_for(
                    uuid=sample.uuid,
                    pci_bus_id=sample.pci_bus_id,
                    ordinal=sample.index,
                    name=sample.name,
                ),
                uuid=sample.uuid,
                pci_bus_id=sample.pci_bus_id,
                utilization_pct=sample.utilization_pct,
                temperature_c=sample.temperature_c,
                probe_source="nvidia-smi",
            )
        )
    return gpus, driver, list(notes)


def _torch_props_uuid(props: Any) -> str | None:
    raw = getattr(props, "uuid", None)
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return text if text.upper().startswith("GPU-") else f"GPU-{text}"


def _probe_torch_cuda() -> tuple[bool, str | None, list[GpuDeviceInfo], list[str]]:
    notes: list[str] = []
    torch = safe_import("torch")
    if torch is None:
        notes.append("torch not installed — CUDA state unknown via torch")
        return False, None, [], notes
    cuda_available = bool(getattr(getattr(torch, "cuda", None), "is_available", lambda: False)())
    torch_cuda_ver = getattr(getattr(torch, "version", None), "cuda", None)
    gpus: list[GpuDeviceInfo] = []
    if cuda_available:
        try:
            count = int(torch.cuda.device_count())
        except Exception:  # noqa: BLE001
            count = 0
        for idx in range(count):
            try:
                name = str(torch.cuda.get_device_name(idx))
                props = torch.cuda.get_device_properties(idx)
                total = int(getattr(props, "total_memory", 0)) or None
                free = used = None
                try:
                    free_b, total_b = torch.cuda.mem_get_info(idx)
                    free = int(free_b)
                    used = int(total_b) - int(free_b)
                    total = int(total_b)
                except Exception:  # noqa: BLE001
                    pass
                major = getattr(props, "major", None)
                minor = getattr(props, "minor", None)
                cc = f"{major}.{minor}" if major is not None and minor is not None else None
                uuid = _torch_props_uuid(props)
                gpus.append(
                    GpuDeviceInfo(
                        index=idx,
                        name=name,
                        total_vram_bytes=total,
                        free_vram_bytes=free,
                        used_vram_bytes=used,
                        compute_capability=cc,
                        stable_device_id=stable_device_id_for(
                            uuid=uuid, pci_bus_id=None, ordinal=idx, name=name
                        ),
                        uuid=uuid,
                        probe_source="torch",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                notes.append(f"torch CUDA device {idx} probe failed: {exc}")
    else:
        notes.append("torch reports CUDA unavailable")
    return cuda_available, str(torch_cuda_ver) if torch_cuda_ver else None, gpus, notes


def _merge_compute_capability(
    smi_gpus: list[GpuDeviceInfo], torch_gpus: list[GpuDeviceInfo]
) -> list[GpuDeviceInfo]:
    """Attach torch-measured compute capability to nvidia-smi rows by UUID only."""
    by_uuid = {g.uuid.upper(): g for g in torch_gpus if g.uuid}
    if not by_uuid:
        return list(smi_gpus)
    merged: list[GpuDeviceInfo] = []
    for gpu in smi_gpus:
        match = by_uuid.get((gpu.uuid or "").upper())
        if match is not None and match.compute_capability and not gpu.compute_capability:
            gpu = replace(gpu, compute_capability=match.compute_capability)
        merged.append(gpu)
    return merged


def probe_hardware(*, corpus_path: Path | None = None) -> HardwareSnapshot:
    notes: list[str] = []
    mem = _meminfo()
    logical = os.cpu_count()
    physical = None
    try:
        physical = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else logical
    except OSError:
        physical = logical

    smi_gpus, driver, smi_notes = _probe_nvidia_smi()
    notes.extend(smi_notes)
    cuda_avail, torch_cuda_ver, torch_gpus, torch_notes = _probe_torch_cuda()
    notes.extend(torch_notes)

    # Prefer nvidia-smi rows when present; else torch; else empty (honest).
    gpus = _merge_compute_capability(smi_gpus, torch_gpus) if smi_gpus else torch_gpus

    bnb = safe_import("bitsandbytes")
    supports_4bit = True if bnb is not None else None
    if bnb is None:
        notes.append("bitsandbytes not installed — 4-bit support unknown/unavailable")

    supports_fp16 = True if cuda_avail else (False if gpus == [] and not cuda_avail else None)
    supports_bf16 = None
    if cuda_avail and gpus:
        # Only claim bf16 when compute capability suggests Ampere+.
        for gpu in gpus:
            if gpu.compute_capability:
                try:
                    major = int(gpu.compute_capability.split(".", 1)[0])
                    supports_bf16 = major >= 8
                    break
                except ValueError:
                    pass

    disk_path = corpus_path or Path.cwd()
    return HardwareSnapshot(
        cpu_model=_cpu_model(),
        logical_cores=logical,
        physical_cores=physical,
        ram_total_bytes=mem.get("MemTotal"),
        ram_available_bytes=mem.get("MemAvailable"),
        disk_free_bytes=_disk_free(disk_path),
        gpus=tuple(gpus),
        cuda_available=cuda_avail,
        cuda_runtime_version=None,
        torch_cuda_version=torch_cuda_ver,
        driver_version=driver,
        supports_fp16=supports_fp16,
        supports_bf16=supports_bf16,
        supports_4bit=supports_4bit,
        notes=tuple(notes),
        measured_at=utc_now(),
    )
