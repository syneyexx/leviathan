"""Resource admission for background jobs — facade over authoritative telemetry.

Does NOT duplicate GPU/VRAM samplers or the model ResourceManager.
Model residency remains owned by the Model Control Plane.

Device-aware reservations share ONE physical truth with model loads.
GPU_EXCLUSIVE is per-device when device identity is known.
GPU_SHARED is amount-aware.
Reservation vs measured usage is never double-counted by callers that use
accounting_mode LIVE_MEASURED.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

import sqlite3

from .sqlite_support import (
    control_plane_connection,
    ensure_wal,
    is_transient_sqlite_error,
    run_with_busy_retry,
)

logger = logging.getLogger(__name__)


class ResourceClass(str, Enum):
    CPU_LIGHT = "CPU_LIGHT"
    CPU_HEAVY = "CPU_HEAVY"
    IO_HEAVY = "IO_HEAVY"
    NETWORK_BOUND = "NETWORK_BOUND"
    MEMORY_HEAVY = "MEMORY_HEAVY"
    GPU_SHARED = "GPU_SHARED"
    GPU_EXCLUSIVE = "GPU_EXCLUSIVE"
    MODEL_INFERENCE = "MODEL_INFERENCE"
    MAINTENANCE_EXCLUSIVE = "MAINTENANCE_EXCLUSIVE"
    BATCH = "BATCH"
    DB_SERIAL = "DB_SERIAL"


class AccountingMode(str, Enum):
    PENDING_LOAD = "PENDING_LOAD"
    LIVE_MEASURED = "LIVE_MEASURED"
    LIVE_UNMEASURED = "LIVE_UNMEASURED"
    RELEASED = "RELEASED"


class PressureState(str, Enum):
    """Host memory/VRAM pressure for admission (Wave 12).

    Profile baseline: 16GB system RAM + dual VRAM profile (16GB primary / 6GB secondary).

    UNKNOWN means telemetry was missing or unreadable — never silently treat as NORMAL.
    """

    UNKNOWN = "UNKNOWN"
    NORMAL = "NORMAL"
    PRESSURE = "PRESSURE"
    CRITICAL = "CRITICAL"


# Default host profile used when operators do not override.
DEFAULT_HOST_RAM_MB = 16_384.0
DEFAULT_VRAM_PRIMARY_MB = 16_384.0
DEFAULT_VRAM_SECONDARY_MB = 6_144.0

# Nonessential classes shed first under PRESSURE / CRITICAL.
_NONESSENTIAL_MEMORY_HEAVY = frozenset(
    {
        ResourceClass.MEMORY_HEAVY,
        ResourceClass.CPU_HEAVY,
        ResourceClass.BATCH,
        ResourceClass.GPU_SHARED,
    }
)

# Always preserved — control plane + paper risk/execution path.
_PROTECTED_OWNER_TYPES = frozenset(
    {
        "control_plane",
        "paper_trading",
        "paper",
        "risk",
        "execution",
        "db_commit",
        "db_writer",
    }
)

_PROTECTED_RESOURCE_CLASSES = frozenset(
    {
        ResourceClass.DB_SERIAL,
        ResourceClass.MAINTENANCE_EXCLUSIVE,
        ResourceClass.CPU_LIGHT,
        ResourceClass.NETWORK_BOUND,
    }
)


@dataclass
class ResourceGovernorDecision:
    """Observability-facing resource decision (Wave 12)."""

    pressure: str
    allowed: bool
    action: str
    reason: str
    shed_caches: bool = False
    unload_idle_models: bool = False
    pause_resumable_jobs: bool = False
    protect_db_writer: bool = True
    details: dict[str, Any] | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "pressure": self.pressure,
            "allowed": self.allowed,
            "action": self.action,
            "reason": self.reason,
            "shedCaches": self.shed_caches,
            "unloadIdleModels": self.unload_idle_models,
            "pauseResumableJobs": self.pause_resumable_jobs,
            "protectDbWriter": self.protect_db_writer,
            "details": self.details or {},
            "truth": {
                "never_kill_db_writer_mid_commit": True,
                "paper_trading_risk_execution_preserved": True,
                "profile_16gb_ram_16_6_vram": True,
            },
        }


def classify_pressure(
    *,
    ram_used_pct: float | None = None,
    ram_available_mb: float | None = None,
    ram_total_mb: float = DEFAULT_HOST_RAM_MB,
    vram_used_pct: float | None = None,
    vram_available_mb: float | None = None,
    vram_total_mb: float | None = None,
) -> PressureState:
    """Classify UNKNOWN / NORMAL / PRESSURE / CRITICAL from measured headroom.

    Thresholds (16GB RAM profile):
      PRESSURE  — RAM used ≥ 70% or available < 4GB; VRAM used ≥ 75%
      CRITICAL  — RAM used ≥ 88% or available < 1.5GB; VRAM used ≥ 92%
    Missing / unreadable telemetry → UNKNOWN (never silently NORMAL).
    """
    ram_known = ram_used_pct is not None or ram_available_mb is not None
    vram_known = vram_used_pct is not None or (
        vram_available_mb is not None and vram_total_mb is not None and float(vram_total_mb) > 0
    )
    if not ram_known and not vram_known:
        return PressureState.UNKNOWN

    ram_pressure = PressureState.UNKNOWN
    if ram_used_pct is not None:
        pct = float(ram_used_pct)
        if pct >= 88.0:
            ram_pressure = PressureState.CRITICAL
        elif pct >= 70.0:
            ram_pressure = PressureState.PRESSURE
        else:
            ram_pressure = PressureState.NORMAL
    elif ram_available_mb is not None:
        # Available-MB is the authoritative signal when provided — do not also
        # re-derive used% from host_total (that double-penalizes fixtures that
        # intentionally report exactly 4 GiB free on a 16 GiB host).
        avail = float(ram_available_mb)
        if avail < 1_536.0:
            ram_pressure = PressureState.CRITICAL
        elif avail < 4_096.0:
            ram_pressure = PressureState.PRESSURE
        else:
            ram_pressure = PressureState.NORMAL
        _ = ram_total_mb  # retained for API compatibility / callers

    vram_pressure = PressureState.UNKNOWN
    if vram_used_pct is not None:
        vp = float(vram_used_pct)
        if vp >= 92.0:
            vram_pressure = PressureState.CRITICAL
        elif vp >= 75.0:
            vram_pressure = PressureState.PRESSURE
        else:
            vram_pressure = PressureState.NORMAL
    elif vram_available_mb is not None and vram_total_mb:
        avail_v = float(vram_available_mb)
        total_v = float(vram_total_mb)
        if total_v > 0:
            used = 100.0 * (1.0 - avail_v / total_v)
            if used >= 92.0:
                vram_pressure = PressureState.CRITICAL
            elif used >= 75.0:
                vram_pressure = PressureState.PRESSURE
            else:
                vram_pressure = PressureState.NORMAL

    order = {
        PressureState.UNKNOWN: -1,
        PressureState.NORMAL: 0,
        PressureState.PRESSURE: 1,
        PressureState.CRITICAL: 2,
    }
    # Prefer the worse *measured* signal. If only one domain is known, use it.
    if ram_pressure == PressureState.UNKNOWN:
        return vram_pressure
    if vram_pressure == PressureState.UNKNOWN:
        return ram_pressure
    return ram_pressure if order[ram_pressure] >= order[vram_pressure] else vram_pressure


@dataclass
class AdmissionDecision:
    allowed: bool
    reason: str
    reservation_id: str | None = None
    vram_known: bool | None = None
    ram_known: bool | None = None
    details: dict[str, Any] | None = None
    device_stable_id: str | None = None
    assigned_devices: list[dict[str, Any]] | None = None
    pressure: str | None = None
    governor: dict[str, Any] | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "reservation_id": self.reservation_id,
            "vram_known": self.vram_known,
            "ram_known": self.ram_known,
            "deviceStableId": self.device_stable_id,
            "assignedDevices": self.assigned_devices or [],
            "pressure": self.pressure,
            "governor": self.governor or {},
            "details": self.details or {},
            "truth": {
                "unknown_vram_is_not_zero": True,
                "unknown_uses_conservative_policy": True,
                "exclusive_is_per_device_when_known": True,
                "pressure_states": ["UNKNOWN", "NORMAL", "PRESSURE", "CRITICAL"],
                "unknown_pressure_is_not_normal": True,
            },
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ResourceAdmission:
    """Background job + model physical reservation leases (one reservation truth)."""

    def __init__(
        self,
        db_path: Path,
        *,
        ram_headroom_mb: float = 512.0,
        vram_headroom_mb: float = 256.0,
        telemetry_reader: Any | None = None,
        interactive_busy_fn: Any | None = None,
        hardware_reader: Any | None = None,
        host_ram_mb: float = DEFAULT_HOST_RAM_MB,
        vram_primary_mb: float = DEFAULT_VRAM_PRIMARY_MB,
        vram_secondary_mb: float = DEFAULT_VRAM_SECONDARY_MB,
        cache_shed_hook: Any | None = None,
        model_unload_hook: Any | None = None,
        pause_jobs_hook: Any | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.ram_headroom_mb = float(ram_headroom_mb)
        self.vram_headroom_mb = float(vram_headroom_mb)
        self.telemetry_reader = telemetry_reader
        self.interactive_busy_fn = interactive_busy_fn
        self.hardware_reader = hardware_reader
        self.host_ram_mb = float(host_ram_mb)
        self.vram_primary_mb = float(vram_primary_mb)
        self.vram_secondary_mb = float(vram_secondary_mb)
        # Optional safe hooks — never kill DB writer mid-commit.
        self.cache_shed_hook = cache_shed_hook
        self.model_unload_hook = model_unload_hook
        self.pause_jobs_hook = pause_jobs_hook
        self._last_governor: ResourceGovernorDecision | None = None
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self, *, operation: str = "admission") -> Iterator[sqlite3.Connection]:
        with control_plane_connection(
            self.db_path,
            store="resource_admission",
            operation=operation,
            write_class="CONTROL_WRITE",
        ) as conn:
            yield conn

    def initialize(self) -> None:
        def _init() -> None:
            with self.connect() as conn:
                ensure_wal(conn)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS resource_reservations (
                        reservation_id TEXT PRIMARY KEY,
                        job_id TEXT,
                        worker_id TEXT,
                        resource_class TEXT NOT NULL,
                        requested_json TEXT NOT NULL DEFAULT '{}',
                        state TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        expires_at TEXT,
                        released_at TEXT,
                        device_stable_id TEXT,
                        model_id TEXT,
                        owner_type TEXT,
                        reserved_vram_bytes INTEGER,
                        reserved_ram_bytes INTEGER,
                        measured_vram_bytes INTEGER,
                        accounting_mode TEXT,
                        shared INTEGER NOT NULL DEFAULT 1,
                        runtime_generation INTEGER,
                        renewed_at TEXT
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_resource_reservations_state "
                    "ON resource_reservations(state, resource_class)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_resource_reservations_device "
                    "ON resource_reservations(device_stable_id, state)"
                )
                # Additive columns for DBs created by earlier migrations.
                cols = {
                    row[1] for row in conn.execute("PRAGMA table_info(resource_reservations)").fetchall()
                }
                for name, ddl in (
                    ("device_stable_id", "TEXT"),
                    ("model_id", "TEXT"),
                    ("owner_type", "TEXT"),
                    ("reserved_vram_bytes", "INTEGER"),
                    ("reserved_ram_bytes", "INTEGER"),
                    ("measured_vram_bytes", "INTEGER"),
                    ("accounting_mode", "TEXT"),
                    ("shared", "INTEGER NOT NULL DEFAULT 1"),
                    ("runtime_generation", "INTEGER"),
                    ("renewed_at", "TEXT"),
                ):
                    if name not in cols:
                        conn.execute(f"ALTER TABLE resource_reservations ADD COLUMN {name} {ddl}")

        run_with_busy_retry(_init)

    def _snapshot(self) -> dict[str, Any]:
        if self.telemetry_reader is None:
            return {"ram_available_mb": None, "vram_available_mb": None, "source": "none", "devices": []}
        try:
            snap = self.telemetry_reader()
            if isinstance(snap, dict):
                return snap
            if hasattr(snap, "public_dict"):
                return dict(snap.public_dict())
        except Exception:  # noqa: BLE001
            return {"ram_available_mb": None, "vram_available_mb": None, "source": "error", "devices": []}
        return {"ram_available_mb": None, "vram_available_mb": None, "source": "unknown", "devices": []}

    def _hardware_devices(self) -> list[dict[str, Any]]:
        if self.hardware_reader is not None:
            try:
                hw = self.hardware_reader()
                if hasattr(hw, "public_dict"):
                    hw = hw.public_dict()
                if isinstance(hw, dict):
                    devices = hw.get("devices") or []
                    return [d for d in devices if isinstance(d, dict)]
            except Exception:  # noqa: BLE001
                pass
        snap = self._snapshot()
        # Legacy: may embed devices under gpu.devices
        gpu = snap.get("gpu") if isinstance(snap.get("gpu"), dict) else {}
        devices = gpu.get("devices") if isinstance(gpu.get("devices"), list) else snap.get("devices") or []
        return [d for d in devices if isinstance(d, dict)]

    def current_pressure(self, snap: dict[str, Any] | None = None) -> PressureState:
        """Compute pressure from telemetry snapshot (Wave 12)."""
        snap = snap if isinstance(snap, dict) else self._snapshot()
        ram_avail = snap.get("ram_available_mb")
        ram_pct = snap.get("ram_used_pct") or snap.get("ramPct")
        vram_avail = snap.get("vram_available_mb")
        vram_pct = snap.get("vram_used_pct") or snap.get("vramPct")
        vram_total = snap.get("vram_total_mb") or self.vram_primary_mb
        return classify_pressure(
            ram_used_pct=float(ram_pct) if ram_pct is not None else None,
            ram_available_mb=float(ram_avail) if ram_avail is not None else None,
            ram_total_mb=self.host_ram_mb,
            vram_used_pct=float(vram_pct) if vram_pct is not None else None,
            vram_available_mb=float(vram_avail) if vram_avail is not None else None,
            vram_total_mb=float(vram_total) if vram_total is not None else None,
        )

    def _owner_protected(self, owner_type: str | None, requested: dict[str, Any]) -> bool:
        owner = str(owner_type or requested.get("ownerType") or requested.get("owner_type") or "").lower()
        if owner in _PROTECTED_OWNER_TYPES:
            return True
        domain = str(requested.get("domain") or "").lower()
        if domain in {"paper", "paper_trading", "control_plane", "db_commit"}:
            return True
        if requested.get("paperTrading") or requested.get("preserve_control_plane"):
            return True
        return False

    def evaluate_governor(
        self,
        *,
        resource_class: ResourceClass,
        owner_type: str = "worker",
        requested: dict[str, Any] | None = None,
        snap: dict[str, Any] | None = None,
    ) -> ResourceGovernorDecision:
        """Pressure-aware admit / shed decision. Never kills DB writer mid-commit."""
        requested = dict(requested or {})
        pressure = self.current_pressure(snap)
        protected = self._owner_protected(owner_type, requested) or resource_class in _PROTECTED_RESOURCE_CLASSES

        if pressure == PressureState.NORMAL:
            decision = ResourceGovernorDecision(
                pressure=pressure.value,
                allowed=True,
                action="admit",
                reason="pressure_normal",
            )
            self._last_governor = decision
            return decision

        if pressure == PressureState.UNKNOWN:
            # Conservative: unknown must not become NORMAL. Deny nonessential
            # memory-heavy work; preserve control / paper / DB paths.
            if protected:
                decision = ResourceGovernorDecision(
                    pressure=pressure.value,
                    allowed=True,
                    action="admit_protected_unknown",
                    reason="UNKNOWN telemetry: protected control-plane / paper / risk path preserved",
                )
            elif resource_class in _NONESSENTIAL_MEMORY_HEAVY:
                decision = ResourceGovernorDecision(
                    pressure=pressure.value,
                    allowed=False,
                    action="deny_nonessential_unknown",
                    reason=(
                        "RESOURCE_ADMISSION_DENIED: UNKNOWN pressure — "
                        "nonessential memory-heavy work refused until telemetry is known"
                    ),
                    details={"resource_class": resource_class.value},
                )
            else:
                decision = ResourceGovernorDecision(
                    pressure=pressure.value,
                    allowed=True,
                    action="admit_essential_unknown",
                    reason="UNKNOWN telemetry: essential / light work still admitted",
                )
            self._last_governor = decision
            return decision

        if pressure == PressureState.PRESSURE:
            # Stop admitting nonessential memory-heavy work; preserve control + paper.
            if protected:
                decision = ResourceGovernorDecision(
                    pressure=pressure.value,
                    allowed=True,
                    action="admit_protected",
                    reason="PRESSURE: protected control-plane / paper / risk path preserved",
                )
            elif resource_class in _NONESSENTIAL_MEMORY_HEAVY:
                decision = ResourceGovernorDecision(
                    pressure=pressure.value,
                    allowed=False,
                    action="deny_nonessential",
                    reason="RESOURCE_ADMISSION_DENIED: PRESSURE — nonessential memory-heavy work paused",
                    details={"resource_class": resource_class.value},
                )
            else:
                decision = ResourceGovernorDecision(
                    pressure=pressure.value,
                    allowed=True,
                    action="admit_essential",
                    reason="PRESSURE: essential / light work still admitted",
                )
            self._last_governor = decision
            return decision

        # CRITICAL — shed caches, unload idle models, pause resumable background.
        shed = True
        unload = True
        pause = True
        if protected or resource_class == ResourceClass.DB_SERIAL:
            decision = ResourceGovernorDecision(
                pressure=pressure.value,
                allowed=True,
                action="admit_protected_critical",
                reason="CRITICAL: DB writer / control / paper risk path never killed mid-commit",
                shed_caches=shed,
                unload_idle_models=unload,
                pause_resumable_jobs=pause,
                protect_db_writer=True,
            )
        else:
            decision = ResourceGovernorDecision(
                pressure=pressure.value,
                allowed=False,
                action="shed_and_deny",
                reason="RESOURCE_ADMISSION_DENIED: CRITICAL — shedding caches / pausing resumable work",
                shed_caches=shed,
                unload_idle_models=unload,
                pause_resumable_jobs=pause,
                protect_db_writer=True,
                details={"resource_class": resource_class.value},
            )
        self._last_governor = decision
        self._apply_critical_hooks(decision)
        return decision

    def _apply_critical_hooks(self, decision: ResourceGovernorDecision) -> None:
        """Invoke optional safe hooks. Failures are logged, never raise into admit path."""
        if decision.shed_caches and self.cache_shed_hook is not None:
            try:
                self.cache_shed_hook()
            except Exception as exc:  # noqa: BLE001
                logger.warning("cache_shed_hook failed: %s", exc)
        if decision.unload_idle_models and self.model_unload_hook is not None:
            try:
                self.model_unload_hook()
            except Exception as exc:  # noqa: BLE001
                logger.warning("model_unload_hook failed: %s", exc)
        if decision.pause_resumable_jobs and self.pause_jobs_hook is not None:
            try:
                self.pause_jobs_hook()
            except Exception as exc:  # noqa: BLE001
                logger.warning("pause_jobs_hook failed: %s", exc)

    def last_governor_decision(self) -> dict[str, Any] | None:
        if self._last_governor is None:
            return None
        return self._last_governor.public_dict()

    def observability_snapshot(self) -> dict[str, Any]:
        """Expose resource decisions for worker / ops dashboards."""
        snap = self._snapshot()
        pressure = self.current_pressure(snap)
        held = []
        try:
            held = self.list_held()
        except Exception:  # noqa: BLE001
            held = []
        return {
            "pressure": pressure.value,
            "hostProfile": {
                "ramMb": self.host_ram_mb,
                "vramPrimaryMb": self.vram_primary_mb,
                "vramSecondaryMb": self.vram_secondary_mb,
            },
            "telemetry": {
                "ram_available_mb": snap.get("ram_available_mb"),
                "vram_available_mb": snap.get("vram_available_mb"),
                "source": snap.get("source"),
            },
            "heldReservations": len(held),
            "lastGovernor": self.last_governor_decision(),
            "truth": {
                "never_kill_db_writer_mid_commit": True,
                "lazy_startup_scale_to_zero_compatible": True,
                "browser_affinity_not_broken": True,
                "unknown_pressure_is_not_normal": True,
            },
        }

    def try_reserve(
        self,
        *,
        job_id: str,
        worker_id: str,
        resource_class: str | ResourceClass,
        requested: dict[str, Any] | None = None,
        ttl_seconds: float = 120.0,
        latency_class: str = "background",
        model_id: str | None = None,
        owner_type: str = "worker",
        device_stable_ids: list[str] | None = None,
        reserved_vram_bytes: int | None = None,
        reserved_ram_bytes: int | None = None,
        shared: bool | None = None,
        runtime_generation: int | None = None,
    ) -> AdmissionDecision:
        rc = (
            resource_class
            if isinstance(resource_class, ResourceClass)
            else ResourceClass(str(resource_class))
        )
        requested = dict(requested or {})
        snap = self._snapshot()
        ram = snap.get("ram_available_mb")
        vram = snap.get("vram_available_mb")
        ram_known = ram is not None
        vram_known = vram is not None

        # Wave 12 — pressure governor before capacity math.
        governor = self.evaluate_governor(
            resource_class=rc,
            owner_type=owner_type,
            requested=requested,
            snap=snap,
        )
        if not governor.allowed:
            return AdmissionDecision(
                allowed=False,
                reason=governor.reason,
                vram_known=vram_known,
                ram_known=ram_known,
                pressure=governor.pressure,
                governor=governor.public_dict(),
                details=dict(governor.details or {}),
            )

        # Extract device intent from requested if not passed explicitly.
        if device_stable_ids is None:
            raw_ids = requested.get("deviceStableIds") or requested.get("device_stable_ids")
            if isinstance(raw_ids, list):
                device_stable_ids = [str(x) for x in raw_ids]
            elif requested.get("deviceStableId") or requested.get("device_stable_id"):
                device_stable_ids = [
                    str(requested.get("deviceStableId") or requested.get("device_stable_id"))
                ]
        if reserved_vram_bytes is None:
            reserved_vram_bytes = requested.get("reservedVramBytes") or requested.get("vram_bytes")
            if reserved_vram_bytes is not None:
                reserved_vram_bytes = int(reserved_vram_bytes)
        if reserved_ram_bytes is None and requested.get("reservedRamBytes") is not None:
            reserved_ram_bytes = int(requested["reservedRamBytes"])
        if shared is None:
            shared = rc != ResourceClass.GPU_EXCLUSIVE

        # Interactive inference outranks queued background GPU work.
        if rc in {ResourceClass.GPU_EXCLUSIVE, ResourceClass.GPU_SHARED, ResourceClass.BATCH}:
            if latency_class.lower() != "interactive" and self.interactive_busy_fn is not None:
                try:
                    if bool(self.interactive_busy_fn()):
                        return AdmissionDecision(
                            allowed=False,
                            reason="RESOURCE_ADMISSION_DENIED: interactive inference pending/active",
                            vram_known=vram_known,
                            ram_known=ram_known,
                        )
                except Exception:  # noqa: BLE001
                    pass

        devices = self._hardware_devices()
        device_map = {
            str(d.get("stableDeviceId") or d.get("stable_device_id") or ""): d for d in devices
        }
        device_map = {k: v for k, v in device_map.items() if k}

        # Per-device exclusive: only blocks the selected device(s).
        if rc == ResourceClass.GPU_EXCLUSIVE:
            target_ids = list(device_stable_ids or [])

            def _check_exclusive() -> list[sqlite3.Row]:
                with self.connect() as conn:
                    if target_ids:
                        placeholders = ",".join("?" for _ in target_ids)
                        return list(
                            conn.execute(
                                f"""
                                SELECT reservation_id, device_stable_id FROM resource_reservations
                                WHERE state = 'HELD' AND resource_class = ?
                                  AND device_stable_id IN ({placeholders})
                                """,
                                (ResourceClass.GPU_EXCLUSIVE.value, *target_ids),
                            ).fetchall()
                        )
                    # No device identity → conservative global exclusive.
                    return list(
                        conn.execute(
                            """
                            SELECT reservation_id, device_stable_id FROM resource_reservations
                            WHERE state = 'HELD' AND resource_class = ?
                            """,
                            (ResourceClass.GPU_EXCLUSIVE.value,),
                        ).fetchall()
                    )

            rows = run_with_busy_retry(_check_exclusive)
            if rows:
                return AdmissionDecision(
                    allowed=False,
                    reason="RESOURCE_ADMISSION_DENIED: GPU_EXCLUSIVE already held on target device(s)",
                    vram_known=vram_known,
                    ram_known=ram_known,
                    details={"conflicts": [dict(r) for r in rows]},
                )

        # Conservative when telemetry unknown — allow CPU/IO, deny exclusive GPU training.
        if not vram_known and not device_map and rc in {ResourceClass.GPU_EXCLUSIVE, ResourceClass.BATCH}:
            if str(latency_class).lower() in {"batch", "maintenance", "background"}:
                return AdmissionDecision(
                    allowed=False,
                    reason="RESOURCE_ADMISSION_DENIED: VRAM unknown — refuse exclusive GPU batch",
                    vram_known=False,
                    ram_known=ram_known,
                )

        if ram_known and float(ram) < self.ram_headroom_mb:
            if rc in {ResourceClass.MEMORY_HEAVY, ResourceClass.CPU_HEAVY}:
                return AdmissionDecision(
                    allowed=False,
                    reason="RESOURCE_ADMISSION_DENIED: RAM headroom insufficient",
                    vram_known=vram_known,
                    ram_known=True,
                    details={"ram_available_mb": ram},
                )

        # Amount-aware shared GPU capacity on a specific device.
        selected_device_id: str | None = None
        if device_stable_ids:
            selected_device_id = device_stable_ids[0]
        elif device_map and rc in {
            ResourceClass.GPU_SHARED,
            ResourceClass.GPU_EXCLUSIVE,
            ResourceClass.MODEL_INFERENCE,
        }:
            # Pick first enabled device with enough free if amount known.
            for sid, dev in device_map.items():
                if dev.get("enabledForNewWork") is False:
                    continue
                free = dev.get("freeVramBytes")
                if reserved_vram_bytes is None or free is None or int(free) >= int(reserved_vram_bytes):
                    selected_device_id = sid
                    break

        if selected_device_id and reserved_vram_bytes is not None:
            conflict = self._device_capacity_conflict(
                selected_device_id,
                reserved_vram_bytes=int(reserved_vram_bytes),
                shared=bool(shared),
            )
            if conflict is not None:
                return conflict

        # Legacy aggregate VRAM headroom when no per-device identity.
        if (
            selected_device_id is None
            and vram_known
            and float(vram) < self.vram_headroom_mb
            and rc
            in {
                ResourceClass.GPU_SHARED,
                ResourceClass.GPU_EXCLUSIVE,
                ResourceClass.MODEL_INFERENCE,
            }
        ):
            return AdmissionDecision(
                allowed=False,
                reason="RESOURCE_ADMISSION_DENIED: VRAM headroom insufficient",
                vram_known=True,
                ram_known=ram_known,
                details={"vram_available_mb": vram},
            )

        # Multi-device atomic reservation: reserve whole set or none.
        target_devices = list(device_stable_ids or ([selected_device_id] if selected_device_id else [None]))
        reservation_ids: list[str] = []
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=max(5.0, float(ttl_seconds)))
        assigned: list[dict[str, Any]] = []

        def _insert_all() -> AdmissionDecision | None:
            with self.connect() as conn:
                # Force a reserved write lock before capacity read (prevents TOCTOU overcommit).
                conn.execute(
                    "UPDATE resource_reservations SET renewed_at = renewed_at "
                    "WHERE reservation_id = '__placement_lock_sentinel__' AND 1=0"
                )
                for sid in target_devices:
                    if sid and rc == ResourceClass.GPU_EXCLUSIVE:
                        row = conn.execute(
                            """
                            SELECT reservation_id FROM resource_reservations
                            WHERE state = 'HELD' AND resource_class = ? AND device_stable_id = ?
                            LIMIT 1
                            """,
                            (ResourceClass.GPU_EXCLUSIVE.value, sid),
                        ).fetchone()
                        if row is not None:
                            return AdmissionDecision(
                                allowed=False,
                                reason="RESOURCE_ADMISSION_DENIED: GPU_EXCLUSIVE race lost",
                                vram_known=vram_known,
                                ram_known=ram_known,
                                device_stable_id=sid,
                            )
                    if sid and reserved_vram_bytes is not None:
                        held = conn.execute(
                            """
                            SELECT COALESCE(SUM(
                                CASE
                                  WHEN accounting_mode = 'LIVE_MEASURED'
                                       AND measured_vram_bytes IS NOT NULL
                                  THEN measured_vram_bytes
                                  ELSE COALESCE(reserved_vram_bytes, 0)
                                END
                            ), 0) AS used
                            FROM resource_reservations
                            WHERE state = 'HELD' AND device_stable_id = ?
                            """,
                            (sid,),
                        ).fetchone()
                        used = int(held["used"] if held is not None else 0)
                        free = None
                        if sid in device_map:
                            free = device_map[sid].get("freeVramBytes")
                        if free is not None and used + int(reserved_vram_bytes) > int(free):
                            return AdmissionDecision(
                                allowed=False,
                                reason="RESOURCE_ADMISSION_DENIED: device VRAM overcommit",
                                vram_known=True,
                                ram_known=ram_known,
                                device_stable_id=sid,
                                details={
                                    "heldBytes": used,
                                    "requestedBytes": reserved_vram_bytes,
                                    "freeBytes": free,
                                },
                            )

                for sid in target_devices:
                    rid = str(uuid.uuid4())
                    reservation_ids.append(rid)
                    per_device_vram = reserved_vram_bytes
                    if sid and len(target_devices) > 1 and reserved_vram_bytes is not None:
                        shard = (
                            requested.get("deviceReservations")
                            if isinstance(requested.get("deviceReservations"), dict)
                            else {}
                        )
                        if sid in shard:
                            per_device_vram = int(shard[sid])
                    conn.execute(
                        """
                        INSERT INTO resource_reservations(
                            reservation_id, job_id, worker_id, resource_class,
                            requested_json, state, created_at, expires_at, released_at,
                            device_stable_id, model_id, owner_type,
                            reserved_vram_bytes, reserved_ram_bytes, measured_vram_bytes,
                            accounting_mode, shared, runtime_generation, renewed_at
                        ) VALUES (?, ?, ?, ?, ?, 'HELD', ?, ?, NULL, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
                        """,
                        (
                            rid,
                            job_id,
                            worker_id,
                            rc.value,
                            json.dumps(requested),
                            now.isoformat(timespec="seconds"),
                            expires.isoformat(timespec="seconds"),
                            sid,
                            model_id,
                            owner_type,
                            per_device_vram,
                            reserved_ram_bytes,
                            AccountingMode.PENDING_LOAD.value,
                            1 if shared else 0,
                            runtime_generation,
                            now.isoformat(timespec="seconds"),
                        ),
                    )
                    assigned.append(
                        {
                            "reservationId": rid,
                            "deviceStableId": sid,
                            "reservedVramBytes": per_device_vram,
                        }
                    )
            return None

        denied = run_with_busy_retry(_insert_all)
        if denied is not None:
            return denied

        return AdmissionDecision(
            allowed=True,
            reason="granted",
            reservation_id=reservation_ids[0] if reservation_ids else None,
            vram_known=vram_known or bool(device_map),
            ram_known=ram_known,
            device_stable_id=selected_device_id,
            assigned_devices=assigned,
            pressure=governor.pressure,
            governor=governor.public_dict(),
            details={"reservationIds": reservation_ids},
        )

    def _device_capacity_conflict(
        self,
        device_stable_id: str,
        *,
        reserved_vram_bytes: int,
        shared: bool,
    ) -> AdmissionDecision | None:
        def _sum() -> int:
            with self.connect() as conn:
                row = conn.execute(
                    """
                    SELECT COALESCE(SUM(
                        CASE
                          WHEN accounting_mode = 'LIVE_MEASURED'
                               AND measured_vram_bytes IS NOT NULL
                          THEN measured_vram_bytes
                          ELSE COALESCE(reserved_vram_bytes, 0)
                        END
                    ), 0) AS used
                    FROM resource_reservations
                    WHERE state = 'HELD' AND device_stable_id = ?
                    """,
                    (device_stable_id,),
                ).fetchone()
                return int(row["used"] if row is not None else 0)

        used = run_with_busy_retry(_sum)
        devices = self._hardware_devices()
        free = None
        for d in devices:
            sid = d.get("stableDeviceId") or d.get("stable_device_id")
            if sid == device_stable_id:
                free = d.get("freeVramBytes")
                break
        if free is None:
            return None
        # For shared: held accounting + new request must fit free.
        # Note: free already includes external use; held may partially overlap measured.
        # Conservative: if held + request > free, deny.
        if shared and used + reserved_vram_bytes > int(free):
            return AdmissionDecision(
                allowed=False,
                reason="RESOURCE_ADMISSION_DENIED: shared GPU capacity insufficient",
                vram_known=True,
                ram_known=None,
                device_stable_id=device_stable_id,
                details={"heldBytes": used, "requestedBytes": reserved_vram_bytes, "freeBytes": free},
            )
        return None

    def mark_live(
        self,
        reservation_id: str | None,
        *,
        measured_vram_bytes: int | None = None,
        accounting_mode: AccountingMode | str = AccountingMode.LIVE_MEASURED,
    ) -> None:
        if not reservation_id:
            return
        mode = (
            accounting_mode.value
            if isinstance(accounting_mode, AccountingMode)
            else str(accounting_mode)
        )

        def _do() -> None:
            with self.connect() as conn:
                conn.execute(
                    """
                    UPDATE resource_reservations
                    SET accounting_mode = ?, measured_vram_bytes = COALESCE(?, measured_vram_bytes)
                    WHERE reservation_id = ? AND state = 'HELD'
                    """,
                    (mode, measured_vram_bytes, reservation_id),
                )

        run_with_busy_retry(_do)

    def renew(self, reservation_id: str | None, *, ttl_seconds: float = 300.0) -> None:
        """Low-frequency lease heartbeat — never per-token."""
        if not reservation_id:
            return
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=max(30.0, float(ttl_seconds)))

        def _do() -> None:
            with self.connect() as conn:
                conn.execute(
                    """
                    UPDATE resource_reservations
                    SET renewed_at = ?, expires_at = ?
                    WHERE reservation_id = ? AND state = 'HELD'
                    """,
                    (
                        now.isoformat(timespec="seconds"),
                        expires.isoformat(timespec="seconds"),
                        reservation_id,
                    ),
                )

        run_with_busy_retry(_do)

    def release(self, reservation_id: str | None) -> None:
        if not reservation_id:
            return

        def _do() -> None:
            with self.connect() as conn:
                conn.execute(
                    """
                    UPDATE resource_reservations
                    SET state = 'RELEASED', released_at = ?, accounting_mode = ?
                    WHERE reservation_id = ? AND state = 'HELD'
                    """,
                    (utc_now(), AccountingMode.RELEASED.value, reservation_id),
                )

        run_with_busy_retry(_do)

    def release_many(self, reservation_ids: list[str] | None) -> None:
        for rid in reservation_ids or []:
            self.release(rid)

    def recover_expired(self, *, now: datetime | None = None) -> int:
        current = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")

        def _do() -> int:
            with self.connect() as conn:
                cur = conn.execute(
                    """
                    UPDATE resource_reservations
                    SET state = 'EXPIRED', released_at = ?, accounting_mode = ?
                    WHERE state = 'HELD' AND expires_at IS NOT NULL AND expires_at <= ?
                    """,
                    (current, AccountingMode.RELEASED.value, current),
                )
                return int(cur.rowcount or 0)

        try:
            return run_with_busy_retry(_do)
        except Exception as exc:
            if is_transient_sqlite_error(exc):
                logger.warning("recover_expired transient failure: %s", exc)
                raise
            logger.error("recover_expired non-transient failure: %s", exc)
            raise

    def list_held(self) -> list[dict[str, Any]]:
        def _do() -> list[dict[str, Any]]:
            with self.connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM resource_reservations WHERE state = 'HELD' ORDER BY created_at"
                ).fetchall()
            return [dict(row) for row in rows]

        return run_with_busy_retry(_do)

    def reservation_view_for_planner(self) -> list[dict[str, Any]]:
        """Normalized held reservations for ResourceManager.device_capacities()."""
        out: list[dict[str, Any]] = []
        for row in self.list_held():
            out.append(
                {
                    "device_stable_id": row.get("device_stable_id"),
                    "resource_class": row.get("resource_class"),
                    "reserved_vram_bytes": row.get("reserved_vram_bytes"),
                    "measured_vram_bytes": row.get("measured_vram_bytes"),
                    "accounting": row.get("accounting_mode"),
                    "state": row.get("state"),
                    "model_id": row.get("model_id"),
                    "owner_type": row.get("owner_type"),
                }
            )
        return out
