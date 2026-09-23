"""Fixture GPU device scheduler (U363).

Claims VRAM/device slots for jobs — telemetry/budgets already exist; this adds
reservation windows without claiming MIG/cloud autoscaling.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GpuDevice:
    device_id: str
    name: str
    vram_mb: int
    compute_capability: str = "8.0"
    available_vram_mb: int = 0
    labels: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.available_vram_mb <= 0:
            self.available_vram_mb = self.vram_mb

    def public_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "name": self.name,
            "vram_mb": self.vram_mb,
            "available_vram_mb": self.available_vram_mb,
            "compute_capability": self.compute_capability,
            "labels": self.labels,
        }


@dataclass(frozen=True)
class GpuReservation:
    reservation_id: str
    device_id: str
    job_id: str
    vram_mb: int
    created_at_ms: float
    expires_at_ms: float

    def public_dict(self) -> dict[str, Any]:
        return {
            "reservation_id": self.reservation_id,
            "device_id": self.device_id,
            "job_id": self.job_id,
            "vram_mb": self.vram_mb,
            "created_at_ms": self.created_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "truth": {
                "fixture_gpu_scheduler_not_mig_product": True,
            },
        }


class FixtureGpuScheduler:
    """In-process GPU claim queue for fixture / single-host mode."""

    def __init__(self, devices: list[GpuDevice] | None = None) -> None:
        self._lock = threading.RLock()
        self._devices: dict[str, GpuDevice] = {
            d.device_id: d for d in (devices or [GpuDevice(device_id="gpu0", name="fixture-gpu", vram_mb=8192)])
        }
        self._reservations: dict[str, GpuReservation] = {}

    def list_devices(self) -> list[GpuDevice]:
        with self._lock:
            return list(self._devices.values())

    def claim(
        self,
        *,
        job_id: str,
        vram_mb: int,
        ttl_ms: float = 60_000.0,
        min_compute_capability: str | None = None,
    ) -> GpuReservation:
        now = time.time() * 1000
        self._expire(now)
        need = max(1, int(vram_mb))
        with self._lock:
            for device in self._devices.values():
                if min_compute_capability and device.compute_capability < min_compute_capability:
                    continue
                if device.available_vram_mb < need:
                    continue
                device.available_vram_mb -= need
                reservation = GpuReservation(
                    reservation_id=f"gres_{uuid.uuid4().hex[:12]}",
                    device_id=device.device_id,
                    job_id=job_id,
                    vram_mb=need,
                    created_at_ms=now,
                    expires_at_ms=now + ttl_ms,
                )
                self._reservations[reservation.reservation_id] = reservation
                return reservation
        raise RuntimeError("GPU_ADMISSION_DENIED: insufficient VRAM/devices")

    def release(self, reservation_id: str) -> None:
        with self._lock:
            reservation = self._reservations.pop(reservation_id, None)
            if reservation is None:
                return
            device = self._devices.get(reservation.device_id)
            if device is not None:
                device.available_vram_mb = min(
                    device.vram_mb, device.available_vram_mb + reservation.vram_mb
                )

    def release_for_job(self, job_id: str) -> int:
        with self._lock:
            ids = [r.reservation_id for r in self._reservations.values() if r.job_id == job_id]
        for rid in ids:
            self.release(rid)
        return len(ids)

    def _expire(self, now_ms: float) -> None:
        with self._lock:
            expired = [r.reservation_id for r in self._reservations.values() if r.expires_at_ms <= now_ms]
        for rid in expired:
            self.release(rid)

    def public_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "devices": [d.public_dict() for d in self._devices.values()],
                "reservations": [r.public_dict() for r in self._reservations.values()],
                "truth": {
                    "fixture_gpu_scheduler_not_mig_product": True,
                    "cloud_autoscaling_not_mandatory": True,
                },
            }
