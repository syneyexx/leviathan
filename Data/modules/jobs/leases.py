"""Worker lease / heartbeat contracts for JobRuntime (U005, U014).

Foundation only: durable fields + negotiation helpers. Full takeover semantics
activate behind ``LEVIATHAN_FEATURE_DURABLE_KERNEL``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

WORKER_PROTOCOL_VERSION = 1


class LeaseState(str, Enum):
    UNOWNED = "UNOWNED"
    HELD = "HELD"
    EXPIRED = "EXPIRED"
    RELEASED = "RELEASED"


@dataclass(frozen=True)
class WorkerProtocolInfo:
    """Protocol/version negotiation for supervised workers (U014)."""

    protocol_version: int = WORKER_PROTOCOL_VERSION
    worker_version: str = "unknown"
    capability_version: str = "1"
    supported_job_kinds: tuple[str, ...] = ()

    def negotiate(self, peer: WorkerProtocolInfo) -> None:
        if peer.protocol_version != self.protocol_version:
            raise ValueError(
                f"WORKER_VERSION_MISMATCH: local protocol={self.protocol_version} "
                f"peer protocol={peer.protocol_version}"
            )

    def public_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "worker_version": self.worker_version,
            "capability_version": self.capability_version,
            "supported_job_kinds": list(self.supported_job_kinds),
        }


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class WorkerLease:
    """Durable worker claim over a job.

    Heartbeat freshness is required — process existence alone is not health.
    """

    job_id: str
    worker_id: str
    state: LeaseState = LeaseState.HELD
    leased_at: str | None = None
    expires_at: str | None = None
    last_heartbeat_at: str | None = None
    protocol: WorkerProtocolInfo = field(default_factory=WorkerProtocolInfo)
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_expired(self, *, now: datetime | None = None) -> bool:
        if self.state != LeaseState.HELD:
            return self.state == LeaseState.EXPIRED
        expires = _parse_ts(self.expires_at)
        if expires is None:
            return False
        current = now or datetime.now(timezone.utc)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return current >= expires

    def public_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "worker_id": self.worker_id,
            "state": self.state.value,
            "leased_at": self.leased_at,
            "expires_at": self.expires_at,
            "last_heartbeat_at": self.last_heartbeat_at,
            "protocol": self.protocol.public_dict(),
            "metadata": self.metadata,
            "truth": {
                "process_exists_is_not_healthy": True,
                "lease_expiry_enables_takeover": True,
            },
        }
