"""Live OS telemetry sampler — honest CPU/RAM/disk/network/(optional) GPU utilization.

Never fabricates percentages or rates. Unavailable metrics remain unavailable (not 0%).
Disk reports filesystem capacity utilization for a configured data root (not disk I/O).
Network reports system-wide bytes/sec from monotonic deltas of net_io_counters.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
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
class NetIoCounters:
    """Monotonic network byte counters at a point in time."""

    bytes_sent: int
    bytes_recv: int
    at_ms: float


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
    uuid: str | None = None
    pci_bus_id: str | None = None
    temperature_c: float | None = None
    power_watts: float | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "ordinal": self.index,
            "name": self.name,
            "utilizationPct": self.utilization_pct,
            "vramTotalBytes": self.vram_total_bytes,
            "vramUsedBytes": self.vram_used_bytes,
            "vramFreeBytes": self.vram_free_bytes,
            "vramUtilizationPct": self.vram_utilization_pct,
            "driverVersion": self.driver_version,
            "uuid": self.uuid,
            "pciBusId": self.pci_bus_id,
            "temperatureC": self.temperature_c,
            "powerWatts": self.power_watts,
            "vendor": _vendor_from_name(self.name),
            "backend": "cuda",
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
    disk_available: bool = False
    disk_total_bytes: int | None = None
    disk_used_bytes: int | None = None
    disk_free_bytes: int | None = None
    disk_utilization_pct: float | None = None
    disk_path: str | None = None
    network_available: bool = False
    network_bytes_per_sec: float | None = None
    network_bytes_sent_per_sec: float | None = None
    network_bytes_recv_per_sec: float | None = None
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
            "disk": {
                "available": self.disk_available,
                "totalBytes": self.disk_total_bytes,
                "usedBytes": self.disk_used_bytes,
                "freeBytes": self.disk_free_bytes,
                "utilizationPct": self.disk_utilization_pct,
                "path": self.disk_path,
                "metric": "capacity_utilization",
            },
            "network": {
                "available": self.network_available,
                "bytesPerSec": self.network_bytes_per_sec,
                "bytesSentPerSec": self.network_bytes_sent_per_sec,
                "bytesRecvPerSec": self.network_bytes_recv_per_sec,
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
            "diskPct": self.disk_utilization_pct if self.disk_available else None,
        }


def _vendor_from_name(name: str | None) -> str | None:
    if not name:
        return None
    lower = name.lower()
    if any(k in lower for k in ("nvidia", "geforce", "rtx", "quadro", "tesla", "a100", "h100")):
        return "nvidia"
    if any(k in lower for k in ("amd", "radeon", "instinct")):
        return "amd"
    if "intel" in lower or "arc" in lower:
        return "intel"
    return None


def parse_nvidia_smi_csv(stdout: str) -> list[GpuDeviceSample]:
    """Parse nvidia-smi csv rows. Malformed lines are skipped — never invented.

    Supports both legacy 7-column and extended rows with uuid/pci/temp/power.
    """
    devices: list[GpuDeviceSample] = []
    for line in stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 7:
            continue
        try:
            index = int(parts[0])
            name = parts[1]
            util = _clamp_pct(float(parts[2])) if parts[2] not in {"[N/A]", "N/A", ""} else None
            total = int(float(parts[3]) * 1024 * 1024)
            free = int(float(parts[4]) * 1024 * 1024)
            used = int(float(parts[5]) * 1024 * 1024)
        except ValueError:
            continue
        driver = parts[6] or None
        uuid = parts[7] if len(parts) > 7 and parts[7] not in {"[N/A]", "N/A", ""} else None
        pci = parts[8] if len(parts) > 8 and parts[8] not in {"[N/A]", "N/A", ""} else None
        temp: float | None = None
        power: float | None = None
        if len(parts) > 9 and parts[9] not in {"[N/A]", "N/A", ""}:
            try:
                temp = float(parts[9])
            except ValueError:
                temp = None
        if len(parts) > 10 and parts[10] not in {"[N/A]", "N/A", ""}:
            try:
                power = float(parts[10])
            except ValueError:
                power = None
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
                uuid=uuid,
                pci_bus_id=pci,
                temperature_c=temp,
                power_watts=power,
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
    query = (
        "index,name,utilization.gpu,memory.total,memory.free,memory.used,"
        "driver_version,uuid,pci.bus_id,temperature.gpu,power.draw"
    )
    try:
        proc = run(
            [
                exe,
                f"--query-gpu={query}",
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
        # Fallback to legacy query without uuid/temp (older drivers).
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


def _resolve_disk_path(data_root: Path | str | None) -> Path | None:
    if data_root is None:
        return None
    try:
        path = Path(data_root)
    except (TypeError, ValueError):
        return None
    # disk_usage needs an existing path; walk up to an existing ancestor.
    candidate = path
    try:
        if not candidate.exists():
            for parent in candidate.parents:
                if parent.exists():
                    candidate = parent
                    break
            else:
                return None
        return candidate
    except OSError:
        return None


def probe_disk_capacity(
    data_root: Path | str | None,
    *,
    disk_usage_fn: Callable[[str | Path], Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Filesystem capacity utilization for the volume containing data_root.

    Returns field dict + notes. On failure: available=False and nulls — never 0%.
    """
    notes: list[str] = []
    empty = {
        "available": False,
        "total_bytes": None,
        "used_bytes": None,
        "free_bytes": None,
        "utilization_pct": None,
        "path": None,
    }
    resolved = _resolve_disk_path(data_root)
    if resolved is None:
        if data_root is not None:
            notes.append("disk probe skipped — data_root path unresolved")
        else:
            notes.append("disk probe skipped — no data_root configured")
        return empty, notes
    usage_fn = disk_usage_fn or shutil.disk_usage
    try:
        usage = usage_fn(resolved)
        total = int(usage.total)
        used = int(usage.used)
        free = int(usage.free)
        if total <= 0:
            notes.append("disk probe returned non-positive total capacity")
            return empty, notes
        pct = _clamp_pct((used / total) * 100.0)
        return {
            "available": pct is not None,
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "utilization_pct": pct,
            "path": str(resolved),
        }, notes
    except Exception as exc:  # noqa: BLE001
        notes.append(f"disk probe failed: {exc}")
        return empty, notes


def probe_network_counters(
    *,
    psutil_module: Any | None = None,
) -> tuple[NetIoCounters | None, list[str]]:
    """Read system-wide net_io_counters. Failure → None (not zeros)."""
    notes: list[str] = []
    psutil = psutil_module
    if psutil is None:
        try:
            import psutil as _psutil  # type: ignore[import-untyped]

            psutil = _psutil
        except ImportError:
            notes.append("psutil not installed — network telemetry unavailable")
            return None, notes
    try:
        counters = psutil.net_io_counters()
        if counters is None:
            notes.append("net_io_counters returned None")
            return None, notes
        sent = int(counters.bytes_sent)
        recv = int(counters.bytes_recv)
        return NetIoCounters(bytes_sent=sent, bytes_recv=recv, at_ms=time.time() * 1000), notes
    except Exception as exc:  # noqa: BLE001
        notes.append(f"network probe failed: {exc}")
        return None, notes


def network_rate_from_delta(
    prev: NetIoCounters | None,
    current: NetIoCounters | None,
) -> tuple[float | None, float | None, float | None]:
    """Compute bytes/sec from monotonic counter deltas.

    Returns (total_bps, sent_bps, recv_bps).
    First sample or counter reset → all None (UNMEASURED), never fabricated 0.
    Idle with a valid interval → measured 0.
    """
    if prev is None or current is None:
        return None, None, None
    dt_ms = current.at_ms - prev.at_ms
    if dt_ms <= 0:
        return None, None, None
    # Counter reset / wrap — do not invent a rate from a negative delta.
    if current.bytes_sent < prev.bytes_sent or current.bytes_recv < prev.bytes_recv:
        return None, None, None
    dt_s = dt_ms / 1000.0
    sent_bps = (current.bytes_sent - prev.bytes_sent) / dt_s
    recv_bps = (current.bytes_recv - prev.bytes_recv) / dt_s
    total_bps = sent_bps + recv_bps
    return total_bps, sent_bps, recv_bps


def collect_system_sample(
    *,
    psutil_module: Any | None = None,
    nvidia_probe: Callable[[], tuple[list[GpuDeviceSample], list[str]]] | None = None,
    include_gpu: bool = True,
    data_root: Path | str | None = None,
    prev_net_io: NetIoCounters | None = None,
    disk_usage_fn: Callable[[str | Path], Any] | None = None,
) -> tuple[SystemTelemetrySample, NetIoCounters | None]:
    """Collect one sample. Inject psutil_module / nvidia_probe for tests.

    Returns (sample, current_net_io_counters). Current counters are None when
    the network probe failed. Rate may be UNMEASURED (null) on the first sample
    even when counters were read successfully.
    """
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

    disk_fields, disk_notes = probe_disk_capacity(data_root, disk_usage_fn=disk_usage_fn)
    notes.extend(disk_notes)

    current_net, net_notes = probe_network_counters(psutil_module=psutil)
    notes.extend(net_notes)
    total_bps, sent_bps, recv_bps = network_rate_from_delta(prev_net_io, current_net)
    # Network is "available" when we successfully read counters; rate may still be null.
    network_available = current_net is not None

    gpu_devices: list[GpuDeviceSample] = []
    gpu_available = False
    if include_gpu:
        probe = nvidia_probe or (lambda: probe_nvidia_smi())
        devices, gpu_notes = probe()
        notes.extend(gpu_notes)
        gpu_devices = devices
        gpu_available = len(devices) > 0

    disk_available = bool(disk_fields["available"])
    measured = (
        cpu_available
        or mem_available
        or gpu_available
        or disk_available
        or network_available
    )
    sample = SystemTelemetrySample(
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
        disk_available=disk_available,
        disk_total_bytes=disk_fields["total_bytes"] if disk_available else None,
        disk_used_bytes=disk_fields["used_bytes"] if disk_available else None,
        disk_free_bytes=disk_fields["free_bytes"] if disk_available else None,
        disk_utilization_pct=disk_fields["utilization_pct"] if disk_available else None,
        disk_path=disk_fields["path"] if disk_available else None,
        network_available=network_available,
        network_bytes_per_sec=total_bps if network_available else None,
        network_bytes_sent_per_sec=sent_bps if network_available else None,
        network_bytes_recv_per_sec=recv_bps if network_available else None,
        notes=tuple(notes),
        measured=measured,
        synthetic=False,
    )
    return sample, current_net


def _empty_public_shape(*, notes: list[str] | None = None) -> dict[str, Any]:
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
        "disk": {
            "available": False,
            "totalBytes": None,
            "usedBytes": None,
            "freeBytes": None,
            "utilizationPct": None,
            "path": None,
            "metric": "capacity_utilization",
        },
        "network": {
            "available": False,
            "bytesPerSec": None,
            "bytesSentPerSec": None,
            "bytesRecvPerSec": None,
        },
        "gpu": {"available": False, "devices": []},
        "notes": list(notes or ["sampler not started"]),
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
            "diskPct": None,
        },
    }


@dataclass
class SystemTelemetrySampler:
    """Background sampler with thread-safe latest-sample cache."""

    interval_s: float = 1.0
    gpu_interval_s: float = 2.0
    data_root: Path | str | None = None
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _latest: SystemTelemetrySample | None = field(default=None, init=False, repr=False)
    _started: bool = field(default=False, init=False, repr=False)
    _last_gpu_at: float = field(default=0.0, init=False, repr=False)
    _last_gpu_devices: tuple[GpuDeviceSample, ...] = field(default=(), init=False, repr=False)
    _last_gpu_available: bool = field(default=False, init=False, repr=False)
    _last_gpu_notes: tuple[str, ...] = field(default=(), init=False, repr=False)
    _prev_net_io: NetIoCounters | None = field(default=None, init=False, repr=False)

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
            return _empty_public_shape()
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
        with self._lock:
            prev_net = self._prev_net_io
            data_root = self.data_root
        if include_gpu:
            sample, current_net = collect_system_sample(
                include_gpu=True,
                data_root=data_root,
                prev_net_io=prev_net,
            )
            with self._lock:
                self._last_gpu_at = now
                self._last_gpu_devices = sample.gpu_devices
                self._last_gpu_available = sample.gpu_available
                self._last_gpu_notes = tuple(
                    n for n in sample.notes if "nvidia" in n.lower() or "GPU" in n
                )
                if current_net is not None:
                    self._prev_net_io = current_net
                self._latest = sample
            return

        sample, current_net = collect_system_sample(
            include_gpu=False,
            data_root=data_root,
            prev_net_io=prev_net,
        )
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
            disk_available=sample.disk_available,
            disk_total_bytes=sample.disk_total_bytes,
            disk_used_bytes=sample.disk_used_bytes,
            disk_free_bytes=sample.disk_free_bytes,
            disk_utilization_pct=sample.disk_utilization_pct,
            disk_path=sample.disk_path,
            network_available=sample.network_available,
            network_bytes_per_sec=sample.network_bytes_per_sec,
            network_bytes_sent_per_sec=sample.network_bytes_sent_per_sec,
            network_bytes_recv_per_sec=sample.network_bytes_recv_per_sec,
            notes=tuple(notes),
            measured=sample.measured or self._last_gpu_available,
            synthetic=False,
        )
        with self._lock:
            if current_net is not None:
                self._prev_net_io = current_net
            self._latest = merged
