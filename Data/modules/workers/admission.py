"""Resource admission for background jobs — facade over authoritative telemetry.

Does NOT duplicate GPU/VRAM samplers or the model ResourceManager.
Model residency remains owned by the Model Control Plane.
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

    def public_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "reservation_id": self.reservation_id,
            "vram_known": self.vram_known,
            "ram_known": self.ram_known,
            "details": self.details or {},
            "truth": {
                "unknown_vram_is_not_zero": True,
                "unknown_uses_conservative_policy": True,
            },
        }


class ResourceAdmission:
    """Background job admission + durable reservation leases."""

    def __init__(
        self,
        db_path: Path,
        *,
        ram_headroom_mb: float = 512.0,
        vram_headroom_mb: float = 256.0,
        telemetry_reader: Any | None = None,
        interactive_busy_fn: Any | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.ram_headroom_mb = float(ram_headroom_mb)
        self.vram_headroom_mb = float(vram_headroom_mb)
        self.telemetry_reader = telemetry_reader
        self.interactive_busy_fn = interactive_busy_fn
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
                        released_at TEXT
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_resource_reservations_state "
                    "ON resource_reservations(state, resource_class)"
                )

        run_with_busy_retry(_init)

    def _snapshot(self) -> dict[str, Any]:
        if self.telemetry_reader is None:
            return {"ram_available_mb": None, "vram_available_mb": None, "source": "none"}
        try:
            snap = self.telemetry_reader()
            if isinstance(snap, dict):
                return snap
            if hasattr(snap, "public_dict"):
                return dict(snap.public_dict())
        except Exception:  # noqa: BLE001
            return {"ram_available_mb": None, "vram_available_mb": None, "source": "error"}
        return {"ram_available_mb": None, "vram_available_mb": None, "source": "unknown"}

    def try_reserve(
        self,
        *,
        job_id: str,
        worker_id: str,
        resource_class: str | ResourceClass,
        requested: dict[str, Any] | None = None,
        ttl_seconds: float = 120.0,
        latency_class: str = "background",
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

        # Interactive inference outranks queued background GPU work.
        if rc in {ResourceClass.GPU_EXCLUSIVE, ResourceClass.GPU_SHARED, ResourceClass.BATCH}:
            if self.interactive_busy_fn is not None:
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

        if rc == ResourceClass.GPU_EXCLUSIVE:

            def _check_exclusive() -> sqlite3.Row | None:
                with self.connect() as conn:
                    return conn.execute(
                        """
                        SELECT reservation_id FROM resource_reservations
                        WHERE state = 'HELD' AND resource_class = ?
                        LIMIT 1
                        """,
                        (ResourceClass.GPU_EXCLUSIVE.value,),
                    ).fetchone()

            row = run_with_busy_retry(_check_exclusive)
            if row is not None:
                return AdmissionDecision(
                    allowed=False,
                    reason="RESOURCE_ADMISSION_DENIED: GPU_EXCLUSIVE already held",
                    vram_known=vram_known,
                    ram_known=ram_known,
                )

        # Conservative when telemetry unknown — allow CPU/IO, deny exclusive GPU training.
        if not vram_known and rc in {ResourceClass.GPU_EXCLUSIVE, ResourceClass.BATCH}:
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

        if vram_known and float(vram) < self.vram_headroom_mb:
            if rc in {
                ResourceClass.GPU_SHARED,
                ResourceClass.GPU_EXCLUSIVE,
                ResourceClass.MODEL_INFERENCE,
            }:
                return AdmissionDecision(
                    allowed=False,
                    reason="RESOURCE_ADMISSION_DENIED: VRAM headroom insufficient",
                    vram_known=True,
                    ram_known=ram_known,
                    details={"vram_available_mb": vram},
                )

        reservation_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=max(5.0, float(ttl_seconds)))

        def _insert() -> None:
            with self.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO resource_reservations(
                        reservation_id, job_id, worker_id, resource_class,
                        requested_json, state, created_at, expires_at, released_at
                    ) VALUES (?, ?, ?, ?, ?, 'HELD', ?, ?, NULL)
                    """,
                    (
                        reservation_id,
                        job_id,
                        worker_id,
                        rc.value,
                        json.dumps(requested),
                        now.isoformat(timespec="seconds"),
                        expires.isoformat(timespec="seconds"),
                    ),
                )

        run_with_busy_retry(_insert)
        return AdmissionDecision(
            allowed=True,
            reason="granted",
            reservation_id=reservation_id,
            vram_known=vram_known,
            ram_known=ram_known,
        )

    def release(self, reservation_id: str | None) -> None:
        if not reservation_id:
            return

        def _do() -> None:
            with self.connect() as conn:
                conn.execute(
                    """
                    UPDATE resource_reservations
                    SET state = 'RELEASED', released_at = ?
                    WHERE reservation_id = ? AND state = 'HELD'
                    """,
                    (utc_now(), reservation_id),
                )

        run_with_busy_retry(_do)

    def recover_expired(self, *, now: datetime | None = None) -> int:
        current = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")

        def _do() -> int:
            with self.connect() as conn:
                cur = conn.execute(
                    """
                    UPDATE resource_reservations
                    SET state = 'EXPIRED', released_at = ?
                    WHERE state = 'HELD' AND expires_at IS NOT NULL AND expires_at <= ?
                    """,
                    (current, current),
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
