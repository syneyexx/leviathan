"""Live OS telemetry sampler — honest CPU/RAM/(optional) GPU utilization.

Never fabricates percentages. Unavailable metrics remain unavailable (not 0%).
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _clamp_pct(value: float | None) -> float | None:
    if value is None:
        return None
    if value != value:  # NaN
        return None
    if value in (float("inf"), float("-inf")):
        return None
    return max(0.0, min(100.0, float(value)))


@dataclass(frozen=True)
class GpuDeviceSample:
    index: int
    name: str
    utilization_pct: float | None
    vram_total_bytes: int | None
    vram_used_bytes: int | None
    vram_free_bytes: int | None
    vram_utilization_pct: float | None
    driver_version: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "utilizationPct": self.utilization_pct,
            "vramTotalBytes": self.vram_total_bytes,
            "vramUsedBytes": self.vram_used_bytes,
            "vramFreeBytes": self.vram_free_bytes,
            "vramUtilizationPct": self.vram_utilization_pct,
            "driverVersion": self.driver_version,
        }


@dataclass(frozen=True)
class SystemTelemetrySample:
    collected_at: str
    collected_at_ms: float
    cpu_available: bool
    cpu_utilization_pct: float | None
    memory_available: bool
    memory_total_bytes: int | None
    memory_used_bytes: int | None
    memory_available_bytes: int | None
    memory_utilization_pct: float | None
    gpu_available: bool
    gpu_devices: tuple[GpuDeviceSample, ...] = ()
    notes: tuple[str, ...] = ()
    measured: bool = True
    synthetic: bool = False

    def public_dict(self, *, now_ms: float | None = None) -> dict[str, Any]:
        now = time.time() * 1000 if now_ms is None else now_ms
        age_ms = max(0, int(now - self.collected_at_ms))
        return {
            "collectedAt": self.collected_at,
            "ageMs": age_ms,
            "cpu": {
                "available": self.cpu_available,
                "utilizationPct": self.cpu_utilization_pct,
            },
            "memory": {
                "available": self.memory_available,
                "totalBytes": self.memory_total_bytes,
                "usedBytes": self.memory_used_bytes,
                "availableBytes": self.memory_available_bytes,
                "utilizationPct": self.memory_utilization_pct,
            },
            "gpu": {
                "available": self.gpu_available,
                "devices": [d.public_dict() for d in self.gpu_devices],
            },
            "notes": list(self.notes),
            "truth": {
                "measured": self.measured and not self.synthetic,
                "synthetic": self.synthetic,
                "unavailableIsNotZero": True,
            },
            # Dashboard gauge semantics — documented, deterministic.
            "dashboard": self.dashboard_gauges(),
        }

    def dashboard_gauges(self) -> dict[str, Any]:
        """Compact gauge view for Command dashboard.

        CPU = system CPU %
        RAM = system RAM %
        GPU = max utilization across measured devices (null if none measured)
        VRAM = total used / total VRAM across devices with both totals (null if none)
        """
        gpu_util: float | None = None
        vram_util: float | None = None
        if self.gpu_available and self.gpu_devices:
            utils = [d.utilization_pct for d in self.gpu_devices if d.utilization_pct is not None]
            if utils:
                gpu_util = _clamp_pct(max(utils))
            total = sum(d.vram_total_bytes or 0 for d in self.gpu_devices)
            used = sum(d.vram_used_bytes or 0 for d in self.gpu_devices if d.vram_total_bytes)
            if total > 0:
                vram_util = _clamp_pct((used / total) * 100.0)
        return {
            "cpuPct": self.cpu_utilization_pct if self.cpu_available else None,
            "ramPct": self.memory_utilization_pct if self.memory_available else None,
            "gpuPct": gpu_util,
            "vramPct": vram_util,
        }


def parse_nvidia_smi_csv(stdout: str) -> list[GpuDeviceSample]:
    """Parse nvidia-smi csv rows. Malformed lines are skipped — never invented."""
    devices: list[GpuDeviceSample] = []
    for line in stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 7:
            continue
        try:
            index = int(parts[0])
            name = parts[1]
            util = _clamp_pct(float(parts[2]))
            total = int(float(parts[3]) * 1024 * 1024)
            free = int(float(parts[4]) * 1024 * 1024)
            used = int(float(parts[5]) * 1024 * 1024)
        except ValueError:
            continue
        driver = parts[6] or None
        vram_pct = _clamp_pct((used / total) * 100.0) if total > 0 else None
        devices.append(
            GpuDeviceSample(
                index=index,
                name=name,
                utilization_pct=util,
                vram_total_bytes=total,
                vram_used_bytes=used,
                vram_free_bytes=free,
                vram_utilization_pct=vram_pct,
                driver_version=driver,
            )
        )
    return devices


def probe_nvidia_smi(
    *,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    timeout: float = 3.0,
) -> tuple[list[GpuDeviceSample], list[str]]:
    notes: list[str] = []
    exe = which("nvidia-smi")
    if not exe:
        notes.append("nvidia-smi not found — GPU telemetry unavailable")
        return [], notes
    run = runner or subprocess.run
    try:
        proc = run(
            [
                exe,
                "--query-gpu=index,name,utilization.gpu,memory.total,memory.free,memory.used,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        notes.append(f"nvidia-smi probe failed: {exc}")
        return [], notes
    if proc.returncode != 0:
        notes.append("nvidia-smi returned non-zero — GPU telemetry unavailable")
        return [], notes
    devices = parse_nvidia_smi_csv(proc.stdout or "")
    if not devices:
        notes.append("nvidia-smi produced no parseable GPU rows")
    return devices, notes


def collect_system_sample(
    *,
    psutil_module: Any | None = None,
    nvidia_probe: Callable[[], tuple[list[GpuDeviceSample], list[str]]] | None = None,
    include_gpu: bool = True,
) -> SystemTelemetrySample:
    """Collect one sample. Inject psutil_module / nvidia_probe for tests."""
    notes: list[str] = []
    collected_at_ms = time.time() * 1000
    collected_at = utc_now_iso()

    cpu_available = False
    cpu_pct: float | None = None
    mem_available = False
    mem_total = mem_used = mem_avail = None
    mem_pct: float | None = None

    psutil = psutil_module
    if psutil is None:
        try:
            import psutil as _psutil  # type: ignore[import-untyped]

            psutil = _psutil
        except ImportError:
            notes.append("psutil not installed — CPU/RAM telemetry unavailable")
            psutil = None

    if psutil is not None:
        try:
            # interval=None uses last cpu_percent baseline (non-blocking after first call).
            raw = psutil.cpu_percent(interval=None)
            cpu_pct = _clamp_pct(float(raw))
            cpu_available = cpu_pct is not None
        except Exception as exc:  # noqa: BLE001
            notes.append(f"CPU probe failed: {exc}")
        try:
            vm = psutil.virtual_memory()
            mem_total = int(vm.total)
            mem_avail = int(vm.available)
            mem_used = int(getattr(vm, "used", mem_total - mem_avail))
            mem_pct = _clamp_pct(float(vm.percent))
            mem_available = mem_total is not None and mem_pct is not None
        except Exception as exc:  # noqa: BLE001
            notes.append(f"memory probe failed: {exc}")

    gpu_devices: list[GpuDeviceSample] = []
    gpu_available = False
    if include_gpu:
        probe = nvidia_probe or (lambda: probe_nvidia_smi())
        devices, gpu_notes = probe()
        notes.extend(gpu_notes)
        gpu_devices = devices
        gpu_available = len(devices) > 0

    measured = cpu_available or mem_available or gpu_available
    return SystemTelemetrySample(
        collected_at=collected_at,
        collected_at_ms=collected_at_ms,
        cpu_available=cpu_available,
        cpu_utilization_pct=cpu_pct if cpu_available else None,
        memory_available=mem_available,
        memory_total_bytes=mem_total if mem_available else None,
        memory_used_bytes=mem_used if mem_available else None,
        memory_available_bytes=mem_avail if mem_available else None,
        memory_utilization_pct=mem_pct if mem_available else None,
        gpu_available=gpu_available,
        gpu_devices=tuple(gpu_devices),
        notes=tuple(notes),
        measured=measured,
        synthetic=False,
    )


@dataclass
class SystemTelemetrySampler:
    """Background sampler with thread-safe latest-sample cache."""

    interval_s: float = 1.0
    gpu_interval_s: float = 2.0
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _latest: SystemTelemetrySample | None = field(default=None, init=False, repr=False)
    _started: bool = field(default=False, init=False, repr=False)
    _last_gpu_at: float = field(default=0.0, init=False, repr=False)
    _last_gpu_devices: tuple[GpuDeviceSample, ...] = field(default=(), init=False, repr=False)
    _last_gpu_available: bool = field(default=False, init=False, repr=False)
    _last_gpu_notes: tuple[str, ...] = field(default=(), init=False, repr=False)

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._stop.clear()
            # Prime cpu_percent baseline so first interval reading is meaningful.
            try:
                import psutil  # type: ignore[import-untyped]

                psutil.cpu_percent(interval=None)
            except Exception:  # noqa: BLE001
                pass
            self._sample_once(force_gpu=True)
            self._thread = threading.Thread(
                target=self._run,
                name="leviathan-system-telemetry",
                daemon=True,
            )
            self._started = True
            self._thread.start()

    def stop(self, *, timeout: float = 2.0) -> None:
        with self._lock:
            if not self._started:
                return
            self._stop.set()
            thread = self._thread
            self._started = False
            self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def latest(self) -> SystemTelemetrySample | None:
        with self._lock:
            return self._latest

    def latest_public(self) -> dict[str, Any]:
        sample = self.latest()
        if sample is None:
            return {
                "collectedAt": None,
                "ageMs": None,
                "cpu": {"available": False, "utilizationPct": None},
                "memory": {
                    "available": False,
                    "totalBytes": None,
                    "usedBytes": None,
                    "availableBytes": None,
                    "utilizationPct": None,
                },
                "gpu": {"available": False, "devices": []},
                "notes": ["sampler not started"],
                "truth": {
                    "measured": False,
                    "synthetic": False,
                    "unavailableIsNotZero": True,
                },
                "dashboard": {
                    "cpuPct": None,
                    "ramPct": None,
                    "gpuPct": None,
                    "vramPct": None,
                },
            }
        return sample.public_dict()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self._sample_once(force_gpu=False)
            except Exception:  # noqa: BLE001 — sampler must not die on probe errors
                continue

    def _sample_once(self, *, force_gpu: bool) -> None:
        now = time.time()
        include_gpu = force_gpu or (now - self._last_gpu_at) >= self.gpu_interval_s
        if include_gpu:
            sample = collect_system_sample(include_gpu=True)
            with self._lock:
                self._last_gpu_at = now
                self._last_gpu_devices = sample.gpu_devices
                self._last_gpu_available = sample.gpu_available
                self._last_gpu_notes = tuple(n for n in sample.notes if "nvidia" in n.lower() or "GPU" in n)
                self._latest = sample
            return

        sample = collect_system_sample(include_gpu=False)
        # Reattach last GPU snapshot so API stays stable between GPU probes.
        notes = list(sample.notes) + list(self._last_gpu_notes)
        merged = SystemTelemetrySample(
            collected_at=sample.collected_at,
            collected_at_ms=sample.collected_at_ms,
            cpu_available=sample.cpu_available,
            cpu_utilization_pct=sample.cpu_utilization_pct,
            memory_available=sample.memory_available,
            memory_total_bytes=sample.memory_total_bytes,
            memory_used_bytes=sample.memory_used_bytes,
            memory_available_bytes=sample.memory_available_bytes,
            memory_utilization_pct=sample.memory_utilization_pct,
            gpu_available=self._last_gpu_available,
            gpu_devices=self._last_gpu_devices,
            notes=tuple(notes),
            measured=sample.measured or self._last_gpu_available,
            synthetic=False,
        )
        with self._lock:
            self._latest = merged
