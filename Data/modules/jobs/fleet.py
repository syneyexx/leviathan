"""Worker/fleet registry extending JobRuntime (U361–U364 foundations).

One registry for inference/training/browser/generic workers — not per-domain fleets.
Remote transport is fixture-only in Wave 10 (no production wire protocol claimed).
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .leases import WORKER_PROTOCOL_VERSION, WorkerProtocolInfo


class WorkerKind(str, Enum):
    LOCAL = "local"
    FIXTURE_REMOTE = "fixture_remote"


class WorkerHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DEAD = "dead"
    DRAINING = "draining"


@dataclass
class FleetWorker:
    worker_id: str
    kind: WorkerKind
    protocol: WorkerProtocolInfo
    health: WorkerHealth = WorkerHealth.HEALTHY
    load: float = 0.0
    labels: dict[str, Any] = field(default_factory=dict)
    last_heartbeat_ms: float = 0.0
    project_affinity: tuple[str, ...] = ()
    gpu_device_ids: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "kind": self.kind.value,
            "health": self.health.value,
            "load": self.load,
            "protocol": self.protocol.public_dict(),
            "labels": self.labels,
            "last_heartbeat_ms": self.last_heartbeat_ms,
            "project_affinity": list(self.project_affinity),
            "gpu_device_ids": list(self.gpu_device_ids),
            "truth": {
                "fixture_remote_not_production_transport": self.kind == WorkerKind.FIXTURE_REMOTE,
                "process_exists_is_not_healthy": True,
            },
        }


class WorkerFleetRegistry:
    """Canonical worker registry for JobRuntime placement (U361)."""

    def __init__(self, *, heartbeat_ttl_ms: float = 30_000.0) -> None:
        self.heartbeat_ttl_ms = heartbeat_ttl_ms
        self._lock = threading.RLock()
        self._workers: dict[str, FleetWorker] = {}

    def register(
        self,
        *,
        worker_id: str | None = None,
        kind: WorkerKind = WorkerKind.LOCAL,
        supported_job_kinds: tuple[str, ...] = (),
        project_affinity: tuple[str, ...] = (),
        gpu_device_ids: tuple[str, ...] = (),
        labels: dict[str, Any] | None = None,
        worker_version: str = "wave10-fixture",
    ) -> FleetWorker:
        wid = worker_id or f"worker_{uuid.uuid4().hex[:10]}"
        worker = FleetWorker(
            worker_id=wid,
            kind=kind,
            protocol=WorkerProtocolInfo(
                protocol_version=WORKER_PROTOCOL_VERSION,
                worker_version=worker_version,
                supported_job_kinds=supported_job_kinds,
            ),
            last_heartbeat_ms=time.time() * 1000,
            project_affinity=project_affinity,
            gpu_device_ids=gpu_device_ids,
            labels=dict(labels or {}),
        )
        with self._lock:
            self._workers[wid] = worker
        return worker

    def heartbeat(self, worker_id: str, *, load: float | None = None) -> FleetWorker:
        with self._lock:
            worker = self._workers.get(worker_id)
            if worker is None:
                raise KeyError(f"Unknown worker: {worker_id}")
            worker.last_heartbeat_ms = time.time() * 1000
            if load is not None:
                worker.load = float(load)
            if worker.health == WorkerHealth.DEAD:
                worker.health = WorkerHealth.HEALTHY
            return worker

    def mark_dead(self, worker_id: str) -> FleetWorker | None:
        with self._lock:
            worker = self._workers.get(worker_id)
            if worker is None:
                return None
            worker.health = WorkerHealth.DEAD
            return worker

    def drain(self, worker_id: str) -> FleetWorker | None:
        with self._lock:
            worker = self._workers.get(worker_id)
            if worker is None:
                return None
            worker.health = WorkerHealth.DRAINING
            return worker

    def refresh_health(self, *, now_ms: float | None = None) -> list[FleetWorker]:
        current = now_ms if now_ms is not None else time.time() * 1000
        changed: list[FleetWorker] = []
        with self._lock:
            for worker in self._workers.values():
                if worker.health in {WorkerHealth.DEAD, WorkerHealth.DRAINING}:
                    continue
                if current - worker.last_heartbeat_ms > self.heartbeat_ttl_ms:
                    worker.health = WorkerHealth.DEAD
                    changed.append(worker)
        return changed

    def list_workers(self, *, healthy_only: bool = False) -> list[FleetWorker]:
        self.refresh_health()
        with self._lock:
            workers = list(self._workers.values())
        if healthy_only:
            workers = [w for w in workers if w.health == WorkerHealth.HEALTHY]
        return workers

    def pick(
        self,
        *,
        job_kind: str | None = None,
        project_id: str | None = None,
        require_gpu: bool = False,
    ) -> FleetWorker | None:
        candidates = self.list_workers(healthy_only=True)
        scored: list[tuple[float, FleetWorker]] = []
        for worker in candidates:
            if job_kind and worker.protocol.supported_job_kinds:
                if job_kind not in worker.protocol.supported_job_kinds:
                    continue
            if require_gpu and not worker.gpu_device_ids:
                continue
            score = worker.load
            if project_id and worker.project_affinity:
                if project_id in worker.project_affinity:
                    score -= 1.0
                else:
                    score += 0.5
            scored.append((score, worker))
        if not scored:
            return None
        scored.sort(key=lambda item: item[0])
        return scored[0][1]

    def public_dict(self) -> dict[str, Any]:
        return {
            "workers": [w.public_dict() for w in self.list_workers()],
            "truth": {
                "one_fleet_registry": True,
                "fixture_remote_not_production_transport": True,
            },
        }
