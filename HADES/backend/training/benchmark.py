"""Optional bounded ATME calibration benchmark metadata (no silent long runs)."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from training.execution_plan import stable_hash
from training.hardware_probe import HardwareSnapshot


class BenchmarkProfile(BaseModel):
    id: str
    created_at: str
    hardware_profile_hash: str
    driver_version: str | None = None
    platform_system: str | None = None
    cancelled: bool = False
    duration_ms: int = 0
    host_to_device_bytes_per_sec: float | None = None
    pinned_host_to_device_bytes_per_sec: float | None = None
    storage_sequential_read_bytes_per_sec: float | None = None
    gpu_microbenchmark_throughput: float | None = None
    allocation_headroom_bytes: int | None = None
    sync_overhead_ms: float | None = None
    notes: list[str] = Field(default_factory=list)
    status: str = "not_run"
    provenance: dict[str, str] = Field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def benchmark_path(root: Path) -> Path:
    return Path(root).expanduser().resolve() / "atme" / "benchmarks" / "latest.json"


def load_latest_benchmark(root: Path) -> BenchmarkProfile | None:
    path = benchmark_path(root)
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        if not isinstance(raw, dict):
            return None
        return BenchmarkProfile.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def save_benchmark(root: Path, profile: BenchmarkProfile) -> BenchmarkProfile:
    path = benchmark_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = profile.to_public_dict()
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temp_name = handle.name
        os.replace(temp_name, path)
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass
    return profile


def benchmark_is_stale(profile: BenchmarkProfile, hardware: HardwareSnapshot) -> bool:
    if profile.hardware_profile_hash != hardware.profile_hash:
        return True
    driver = hardware.gpu.driver_version.value
    if profile.driver_version and driver and profile.driver_version != driver:
        return True
    return False


def create_placeholder_benchmark(hardware: HardwareSnapshot) -> BenchmarkProfile:
    """Record that no benchmark has been measured yet (honest empty profile)."""

    now = datetime.now(UTC).isoformat(timespec="seconds")
    return BenchmarkProfile(
        id=f"bench_{stable_hash({'hw': hardware.profile_hash, 'ts': now})[:16]}",
        created_at=now,
        hardware_profile_hash=hardware.profile_hash,
        driver_version=str(hardware.gpu.driver_version.value) if hardware.gpu.driver_version.value else None,
        platform_system=str(hardware.host.platform_system.value) if hardware.host.platform_system.value else None,
        status="not_run",
        notes=["Benchmark was not executed; estimates remain uncalibrated."],
        provenance={"kind": "placeholder"},
    )
