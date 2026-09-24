"""Worker protocol contracts — identity, states, handshake."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

WORKER_PROTOCOL_VERSION = 1


class WorkerInstanceState(str, Enum):
    STARTING = "STARTING"
    READY = "READY"
    BUSY = "BUSY"
    DRAINING = "DRAINING"
    STOPPED = "STOPPED"
    STALE = "STALE"
    CRASHED = "CRASHED"
    DEGRADED = "DEGRADED"
    INCOMPATIBLE = "INCOMPATIBLE"


class SupervisorHealth(str, Enum):
    """Operator-visible generic worker supervisor health (not model serving)."""

    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    LEASE_LOST = "LEASE_LOST"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass
class WorkerRegistration:
    worker_id: str
    pool_id: str
    slot: int
    pid: int
    process_start_identity: str
    protocol_version: int = WORKER_PROTOCOL_VERSION
    implementation_version: str = "1"
    supported_job_kinds: tuple[str, ...] = ()
    host: str = "localhost"
    started_at: str | None = None
    last_heartbeat_at: str | None = None
    state: WorkerInstanceState = WorkerInstanceState.STARTING
    current_job_id: str | None = None
    supervisor_generation: str | None = None
    restart_count: int = 0
    degraded_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "pool_id": self.pool_id,
            "slot": self.slot,
            "pid": self.pid,
            "process_start_identity": self.process_start_identity,
            "protocol_version": self.protocol_version,
            "implementation_version": self.implementation_version,
            "supported_job_kinds": list(self.supported_job_kinds),
            "host": self.host,
            "started_at": self.started_at,
            "last_heartbeat_at": self.last_heartbeat_at,
            "state": self.state.value,
            "current_job_id": self.current_job_id,
            "supervisor_generation": self.supervisor_generation,
            "restart_count": self.restart_count,
            "degraded_reason": self.degraded_reason,
            "metadata": dict(self.metadata),
            "truth": {
                "pid_alive_is_not_healthy": True,
                "stale_row_is_not_live_worker": True,
            },
        }

    def negotiate(self, peer_protocol_version: int) -> None:
        if int(peer_protocol_version) != int(self.protocol_version):
            raise ValueError(
                f"WORKER_PROTOCOL_MISMATCH: local={self.protocol_version} "
                f"peer={peer_protocol_version}"
            )
