"""Worker lease / heartbeat contracts for JobRuntime (U005, U014).

Foundation only: durable fields + negotiation helpers. Full takeover semantics
activate behind ``LEVIATHAN_FEATURE_DURABLE_KERNEL``.

Lease fencing helpers (Wave 4 WORKER-001..008):
- No side effect without a proven lease.
- Lease lost → fence (stop work).
- Cancel-state read failure → fail closed (treat as cancelled / stop).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

WORKER_PROTOCOL_VERSION = 1


class LeaseState(str, Enum):
    UNOWNED = "UNOWNED"
    HELD = "HELD"
    EXPIRED = "EXPIRED"
    RELEASED = "RELEASED"


class LeaseFenceError(RuntimeError):
    """Worker must stop side effects — lease unproven or lost."""

    def __init__(
        self,
        message: str,
        *,
        job_id: str | None = None,
        worker_id: str | None = None,
        reason: str = "lease_fence",
    ) -> None:
        super().__init__(message)
        self.job_id = job_id
        self.worker_id = worker_id
        self.reason = reason


def _signal_fence(ctx: dict[str, Any] | None) -> None:
    if not ctx:
        return
    for key in ("lease_lost", "job_cancel_fence"):
        ev = ctx.get(key)
        if ev is not None and hasattr(ev, "set"):
            ev.set()


def _fence_already_signaled(ctx: dict[str, Any] | None) -> bool:
    if not ctx:
        return False
    for key in ("lease_lost", "job_cancel_fence"):
        ev = ctx.get(key)
        if ev is not None and getattr(ev, "is_set", lambda: False)():
            return True
    return False


def _state_name(state: Any) -> str:
    if state is None:
        return ""
    name = getattr(state, "name", None) or getattr(state, "value", None)
    return str(name or state)


def observe_job_cancel_state(
    store: Any,
    job_id: str,
    *,
    worker_id: str | None = None,
    ctx: dict[str, Any] | None = None,
    cancel_states: frozenset[str] | None = None,
) -> bool:
    """Return True when work must stop (cancel / missing job / wrong owner).

    Fail-closed: any inability to read authoritative job state returns True.
    """
    if _fence_already_signaled(ctx):
        return True
    parent = (ctx or {}).get("job_cancel_check") if ctx else None
    # Avoid re-entrancy when this helper *is* the parent check.
    if callable(parent) and getattr(parent, "_leviathan_lease_bound", False) is not True:
        try:
            if parent():
                _signal_fence(ctx)
                return True
        except Exception:  # noqa: BLE001 — cancel probe failure fails closed
            _signal_fence(ctx)
            return True
    stopped = cancel_states or frozenset({"CANCEL_REQUESTED", "CANCELLED"})
    try:
        current = store.get(job_id)
    except Exception:  # noqa: BLE001
        _signal_fence(ctx)
        return True
    if current is None:
        _signal_fence(ctx)
        return True
    if _state_name(getattr(current, "state", None)) in stopped:
        return True
    owner = getattr(current, "lease_owner", None)
    if worker_id and owner and owner != worker_id:
        _signal_fence(ctx)
        return True
    return False


def require_lease_heartbeat(
    store: Any,
    job_id: str,
    *,
    worker_id: str,
    ttl_seconds: float,
    ctx: dict[str, Any] | None = None,
) -> None:
    """Extend the lease or fence. Never swallow definitive / unproven lease health."""
    if not hasattr(store, "heartbeat_lease"):
        raise LeaseFenceError(
            f"store cannot heartbeat lease for job {job_id}",
            job_id=job_id,
            worker_id=worker_id,
            reason="heartbeat_unsupported",
        )
    try:
        store.heartbeat_lease(job_id, worker_id=worker_id, ttl_seconds=float(ttl_seconds))
    except Exception as exc:  # noqa: BLE001
        _signal_fence(ctx)
        raise LeaseFenceError(
            f"lease heartbeat failed for job {job_id}: {exc}",
            job_id=job_id,
            worker_id=worker_id,
            reason="heartbeat_failed",
        ) from exc


def make_lease_bound_checks(
    ctx: dict[str, Any],
    store: Any,
    job_id: str,
    *,
    worker_id: str,
    ttl_seconds: float,
    extra_cancel: Callable[[Any], bool] | None = None,
) -> tuple[Callable[[], bool], Callable[[], None]]:
    """Shared cancel_check + heartbeat for provider_io / MCP / model_download / gateway."""

    def cancel_check() -> bool:
        if observe_job_cancel_state(store, job_id, worker_id=worker_id, ctx=ctx):
            return True
        if extra_cancel is None:
            return False
        try:
            current = store.get(job_id)
        except Exception:  # noqa: BLE001
            _signal_fence(ctx)
            return True
        try:
            return bool(extra_cancel(current))
        except Exception:  # noqa: BLE001 — extra cancel probe fails closed
            _signal_fence(ctx)
            return True

    cancel_check._leviathan_lease_bound = True  # type: ignore[attr-defined]

    def heartbeat() -> None:
        require_lease_heartbeat(
            store,
            job_id,
            worker_id=worker_id,
            ttl_seconds=ttl_seconds,
            ctx=ctx,
        )

    return cancel_check, heartbeat


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
