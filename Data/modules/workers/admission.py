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


class AccountingMode(str, Enum):
    PENDING_LOAD = "PENDING_LOAD"
    LIVE_MEASURED = "LIVE_MEASURED"
    LIVE_UNMEASURED = "LIVE_UNMEASURED"
    RELEASED = "RELEASED"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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

    def public_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "reservation_id": self.reservation_id,
            "vram_known": self.vram_known,
            "ram_known": self.ram_known,
            "deviceStableId": self.device_stable_id,
            "assignedDevices": self.assigned_devices or [],
            "details": self.details or {},
            "truth": {
                "unknown_vram_is_not_zero": True,
                "unknown_uses_conservative_policy": True,
                "exclusive_is_per_device_when_known": True,
            },
        }


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
    ) -> None:
        self.db_path = Path(db_path)
        self.ram_headroom_mb = float(ram_headroom_mb)
        self.vram_headroom_mb = float(vram_headroom_mb)
        self.telemetry_reader = telemetry_reader
        self.interactive_busy_fn = interactive_busy_fn
        self.hardware_reader = hardware_reader
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        with control_plane_connection(self.db_path) as conn:
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
