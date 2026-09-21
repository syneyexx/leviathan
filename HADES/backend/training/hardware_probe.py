"""Lightweight hardware snapshot for ATME planning.

Never imports PyTorch into the normal HADES process. GPU facts that require CUDA
runtime are collected via optional nvidia-smi / ctypes probes and marked with
provenance: detected | measured | estimated | unknown.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from training.execution_plan import stable_hash

FactSource = Literal["detected", "measured", "estimated", "unknown"]


class Fact(BaseModel):
    value: Any = None
    source: FactSource = "unknown"
    unit: str | None = None
    note: str | None = None


class GpuSnapshot(BaseModel):
    name: Fact = Field(default_factory=Fact)
    cuda_available: Fact = Field(default_factory=lambda: Fact(value=False, source="detected"))
    compute_capability: Fact = Field(default_factory=Fact)
    total_vram_bytes: Fact = Field(default_factory=Fact)
    free_vram_bytes: Fact = Field(default_factory=Fact)
    driver_version: Fact = Field(default_factory=Fact)
    bf16_support: Fact = Field(default_factory=Fact)
    fp16_support: Fact = Field(default_factory=Fact)
    bitsandbytes_compatible: Fact = Field(default_factory=Fact)
    gpu_utilization_percent: Fact = Field(default_factory=Fact)
    vram_utilization_percent: Fact = Field(default_factory=Fact)
    count: Fact = Field(default_factory=lambda: Fact(value=0, source="detected"))


class HostSnapshot(BaseModel):
    total_ram_bytes: Fact = Field(default_factory=Fact)
    available_ram_bytes: Fact = Field(default_factory=Fact)
    cpu_count: Fact = Field(default_factory=Fact)
    process_architecture: Fact = Field(default_factory=Fact)
    platform_system: Fact = Field(default_factory=Fact)
    pagefile_or_swap_bytes: Fact = Field(default_factory=Fact)
    pinned_memory_practical: Fact = Field(default_factory=Fact)


class StorageSnapshot(BaseModel):
    path: str
    free_bytes: Fact = Field(default_factory=Fact)
    total_bytes: Fact = Field(default_factory=Fact)
    is_local: Fact = Field(default_factory=Fact)
    device_type: Fact = Field(default_factory=Fact)
    sequential_read_bytes_per_sec: Fact = Field(default_factory=Fact)


class HardwareSnapshot(BaseModel):
    gpu: GpuSnapshot = Field(default_factory=GpuSnapshot)
    host: HostSnapshot = Field(default_factory=HostSnapshot)
    storage: list[StorageSnapshot] = Field(default_factory=list)
    packages: dict[str, dict[str, Any]] = Field(default_factory=dict)
    profile_hash: str = ""
    collected_at: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _fact(value: Any, source: FactSource, *, unit: str | None = None, note: str | None = None) -> Fact:
    return Fact(value=value, source=source, unit=unit, note=note)


def _run_command(args: list[str], *, timeout: float = 3.0) -> str | None:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return (completed.stdout or "").strip()


def _probe_ram() -> tuple[Fact, Fact, Fact]:
    total = _fact(None, "unknown")
    available = _fact(None, "unknown")
    swap = _fact(None, "unknown")
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", wintypes.DWORD),
                    ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_uint64),
                    ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64),
                    ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64),
                    ("ullAvailVirtual", ctypes.c_uint64),
                    ("ullAvailExtendedVirtual", ctypes.c_uint64),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                total = _fact(int(stat.ullTotalPhys), "detected", unit="bytes")
                available = _fact(int(stat.ullAvailPhys), "detected", unit="bytes")
                swap = _fact(int(stat.ullTotalPageFile), "detected", unit="bytes", note="total_pagefile")
                return total, available, swap
        except Exception:
            pass
    # POSIX
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        try:
            values: dict[str, int] = {}
            for line in meminfo.read_text(encoding="utf-8").splitlines():
                if ":" not in line:
                    continue
                key, raw = line.split(":", 1)
                parts = raw.strip().split()
                if not parts:
                    continue
                values[key] = int(parts[0]) * 1024
            if "MemTotal" in values:
                total = _fact(values["MemTotal"], "detected", unit="bytes")
            if "MemAvailable" in values:
                available = _fact(values["MemAvailable"], "detected", unit="bytes")
            if "SwapTotal" in values:
                swap = _fact(values["SwapTotal"], "detected", unit="bytes")
        except (OSError, ValueError):
            pass
    return total, available, swap


def _probe_nvidia_smi() -> GpuSnapshot:
    gpu = GpuSnapshot()
    smi = shutil.which("nvidia-smi")
    if not smi:
        gpu.cuda_available = _fact(False, "detected", note="nvidia-smi_not_found")
        return gpu
    query = _run_command(
        [
            smi,
            "--query-gpu=name,memory.total,memory.free,utilization.gpu,utilization.memory,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    if not query:
        gpu.cuda_available = _fact(False, "detected", note="nvidia-smi_query_failed")
        return gpu
    lines = [line.strip() for line in query.splitlines() if line.strip()]
    gpu.count = _fact(len(lines), "detected")
    if not lines:
        return gpu
    # Use first GPU for planning; multi-GPU planning is out of ATME v1 scope.
    parts = [part.strip() for part in lines[0].split(",")]
    if len(parts) < 6:
        gpu.cuda_available = _fact(False, "detected", note="nvidia-smi_parse_failed")
        return gpu
    name, mem_total_mib, mem_free_mib, util_gpu, util_mem, driver = parts[:6]
    gpu.name = _fact(name, "detected")
    gpu.cuda_available = _fact(True, "detected")
    try:
        gpu.total_vram_bytes = _fact(int(float(mem_total_mib) * 1024 * 1024), "detected", unit="bytes")
    except ValueError:
        gpu.total_vram_bytes = _fact(None, "unknown")
    try:
        gpu.free_vram_bytes = _fact(int(float(mem_free_mib) * 1024 * 1024), "detected", unit="bytes")
    except ValueError:
        gpu.free_vram_bytes = _fact(None, "unknown")
    try:
        gpu.gpu_utilization_percent = _fact(float(util_gpu), "detected", unit="percent")
    except ValueError:
        pass
    try:
        gpu.vram_utilization_percent = _fact(float(util_mem), "detected", unit="percent")
    except ValueError:
        pass
    gpu.driver_version = _fact(driver, "detected")
    # Without CUDA runtime we cannot assert BF16/FP16 or bitsandbytes compatibility.
    gpu.bf16_support = _fact(None, "unknown", note="requires_cuda_runtime")
    gpu.fp16_support = _fact(None, "unknown", note="requires_cuda_runtime")
    gpu.bitsandbytes_compatible = _fact(None, "unknown", note="requires_bitsandbytes_import")
    return gpu


def _probe_storage(paths: list[str | Path]) -> list[StorageSnapshot]:
    snapshots: list[StorageSnapshot] = []
    seen: set[str] = set()
    for raw in paths:
        path = Path(raw).expanduser()
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        target = resolved if resolved.exists() else resolved.parent
        try:
            target = target if target.exists() else Path.cwd()
            key = str(target)
            if key in seen:
                continue
            seen.add(key)
            usage = shutil.disk_usage(target)
            snapshots.append(
                StorageSnapshot(
                    path=key,
                    free_bytes=_fact(int(usage.free), "detected", unit="bytes"),
                    total_bytes=_fact(int(usage.total), "detected", unit="bytes"),
                    is_local=_fact(True, "estimated", note="network_share_detection_not_implemented"),
                    device_type=_fact(None, "unknown", note="drive_type_not_trusted_without_os_api"),
                    sequential_read_bytes_per_sec=_fact(None, "unknown", note="run_optional_benchmark"),
                )
            )
        except OSError:
            snapshots.append(
                StorageSnapshot(
                    path=str(resolved),
                    free_bytes=_fact(None, "unknown"),
                    total_bytes=_fact(None, "unknown"),
                    is_local=_fact(None, "unknown"),
                    device_type=_fact(None, "unknown"),
                )
            )
    return snapshots


def _package_availability() -> dict[str, dict[str, Any]]:
    import importlib.metadata
    import importlib.util

    packages: dict[str, dict[str, Any]] = {}
    for module_name, package_name in (
        ("torch", "torch"),
        ("transformers", "transformers"),
        ("datasets", "datasets"),
        ("peft", "peft"),
        ("accelerate", "accelerate"),
        ("bitsandbytes", "bitsandbytes"),
        ("safetensors", "safetensors"),
    ):
        available = importlib.util.find_spec(module_name) is not None
        version = None
        if available:
            try:
                version = importlib.metadata.version(package_name)
            except importlib.metadata.PackageNotFoundError:
                version = None
        packages[module_name] = {"available": available, "version": version}
    return packages


def collect_hardware_snapshot(
    *,
    storage_paths: list[str | Path] | None = None,
    collected_at: str | None = None,
) -> HardwareSnapshot:
    """Collect a best-effort hardware snapshot without importing PyTorch."""

    from datetime import UTC, datetime

    total_ram, available_ram, swap = _probe_ram()
    host = HostSnapshot(
        total_ram_bytes=total_ram,
        available_ram_bytes=available_ram,
        pagefile_or_swap_bytes=swap,
        cpu_count=_fact(os.cpu_count() or 1, "detected"),
        process_architecture=_fact(platform.machine() or sys.maxsize.bit_length(), "detected"),
        platform_system=_fact(platform.system(), "detected"),
        pinned_memory_practical=_fact(None, "unknown", note="requires_optional_benchmark"),
    )
    gpu = _probe_nvidia_smi()
    packages = _package_availability()
    if packages.get("bitsandbytes", {}).get("available") and gpu.cuda_available.value:
        # Presence of the package is not full compatibility proof; mark estimated.
        gpu.bitsandbytes_compatible = _fact(True, "estimated", note="package_present_cuda_detected")
    elif packages.get("bitsandbytes", {}).get("available") is False:
        gpu.bitsandbytes_compatible = _fact(False, "detected", note="package_missing")

    paths = list(storage_paths or [])
    if not paths:
        paths = [Path.cwd()]
    storage = _probe_storage(paths)

    snapshot = HardwareSnapshot(
        gpu=gpu,
        host=host,
        storage=storage,
        packages=packages,
        collected_at=collected_at or datetime.now(UTC).isoformat(timespec="seconds"),
    )
    fingerprint = {
        "gpu_name": gpu.name.value,
        "gpu_count": gpu.count.value,
        "total_vram": gpu.total_vram_bytes.value,
        "total_ram": host.total_ram_bytes.value,
        "cpu_count": host.cpu_count.value,
        "arch": host.process_architecture.value,
        "system": host.platform_system.value,
        "driver": gpu.driver_version.value,
        "packages": {k: v.get("version") for k, v in packages.items()},
    }
    snapshot.profile_hash = stable_hash(fingerprint)
    return snapshot
