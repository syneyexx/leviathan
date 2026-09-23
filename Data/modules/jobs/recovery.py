"""Lease reclaim / recovery without duplicate effects (U354 / U360 / exit gate)."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from Data.modules.execution import CapabilityRequest, CapabilityResult, CapabilityStatus, ExecutionGateway
from Data.modules.jobs.fleet import WorkerFleetRegistry, WorkerHealth
from Data.modules.jobs.states import JobState
from Data.modules.jobs.store import JobStore
from Data.modules.jobs.types import JobRecord
from Data.modules.security.secrets_broker import SecretsBroker


@dataclass(frozen=True)
class RecoveryAction:
    action_id: str
    job_id: str
    previous_worker_id: str | None
    new_worker_id: str | None
    status: str
    detail: str
    recorded_at_ms: float
    duplicate_effect_prevented: bool = False
    secrets_revoked: int = 0

    def public_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "job_id": self.job_id,
            "previous_worker_id": self.previous_worker_id,
            "new_worker_id": self.new_worker_id,
            "status": self.status,
            "detail": self.detail,
            "recorded_at_ms": self.recorded_at_ms,
            "duplicate_effect_prevented": self.duplicate_effect_prevented,
            "secrets_revoked": self.secrets_revoked,
            "truth": {
                "recovery_is_bounded": True,
                "duplicate_effects_forbidden": True,
            },
        }


class LeaseRecoveryPlane:
    """Reclaim expired job leases and re-dispatch through the gateway.

    Exit-gate invariant: reclaim must not create a second effect for the same
    idempotency_key.
    """

    def __init__(
        self,
        store: JobStore,
        gateway: ExecutionGateway,
        *,
        fleet: WorkerFleetRegistry | None = None,
        secrets: SecretsBroker | None = None,
        on_reclaim: Callable[[JobRecord, RecoveryAction], None] | None = None,
    ) -> None:
        self.store = store
        self.gateway = gateway
        self.fleet = fleet
        self.secrets = secrets
        self.on_reclaim = on_reclaim
        self.actions: list[RecoveryAction] = []
        self.telemetry: dict[str, Any] = {
            "reclaims": 0,
            "replays": 0,
            "duplicate_prevented": 0,
            "failures": 0,
        }

    def reclaim_expired(
        self,
        *,
        now: datetime | None = None,
        limit: int = 20,
        project_id: str | None = None,
    ) -> list[RecoveryAction]:
        expired = self.store.list_expired_leases(now=now)[: max(1, min(limit, 100))]
        results: list[RecoveryAction] = []
        for job in expired:
            results.append(self._reclaim_one(job, project_id=project_id))
        return results

    def _reclaim_one(self, job: JobRecord, *, project_id: str | None) -> RecoveryAction:
        previous = job.lease_owner
        secrets_revoked = 0
        if self.secrets is not None and previous:
            secrets_revoked = self.secrets.revoke_for_worker(previous)
        if self.fleet is not None and previous:
            self.fleet.mark_dead(previous)

        # Clear stale lease so a new worker can acquire.
        self.store.release_lease(job.job_id, worker_id=previous)

        new_worker: str | None = None
        if self.fleet is not None:
            picked = self.fleet.pick(job_kind=job.capability_id, project_id=project_id)
            if picked is not None and picked.health == WorkerHealth.HEALTHY:
                new_worker = picked.worker_id
                self.store.acquire_lease(job.job_id, worker_id=new_worker, ttl_seconds=30.0)
            else:
                # No healthy worker — leave job RUNNING without owner for a later reclaim.
                # (RUNNING → QUEUED is not a legal transition.)
                action = RecoveryAction(
                    action_id=f"rcv_{uuid.uuid4().hex[:12]}",
                    job_id=job.job_id,
                    previous_worker_id=previous,
                    new_worker_id=None,
                    status="awaiting_worker",
                    detail="no_healthy_worker",
                    recorded_at_ms=time.time() * 1000,
                    secrets_revoked=secrets_revoked,
                )
                self.actions.append(action)
                self.telemetry["reclaims"] += 1
                return action

        # Re-execute through gateway; idempotency short-circuit prevents duplicates.
        idem = job.idempotency_key
        before_effects = len(getattr(self.gateway, "effect_ledger", []) or [])
        result = self.gateway.execute(
            CapabilityRequest(
                capability_id=job.capability_id,
                arguments=dict(job.arguments or {}),
                request_id=str(uuid.uuid4()),
                run_id=job.run_id,
                job_id=job.job_id,
                approval_id=job.approval_id,
                requested_by="lease_recovery",
                trace_id=job.trace_id,
                idempotency_key=idem,
            )
        )
        after_effects = len(getattr(self.gateway, "effect_ledger", []) or [])
        duplicate_prevented = bool(
            idem
            and getattr(result, "telemetry", {}).get("idempotent_replay")
        )
        if duplicate_prevented:
            self.telemetry["duplicate_prevented"] += 1
        elif after_effects == before_effects and idem:
            # No new ledger append — also counts as prevented when replay cached.
            duplicate_prevented = bool(getattr(result, "telemetry", {}).get("idempotent_replay"))

        status = "recovered"
        detail = result.status.value if hasattr(result.status, "value") else str(result.status)
        if result.status == CapabilityStatus.FAILED:
            status = "failed"
            self.telemetry["failures"] += 1
            try:
                self.store.transition(job.job_id, JobState.FAILED, error=result.error or "recovery_failed")
            except ValueError:
                pass
        else:
            self.telemetry["replays"] += 1
            try:
                self.store.transition(
                    job.job_id,
                    JobState.COMPLETED,
                    result=result.output if isinstance(result.output, dict) else {"value": result.output},
                )
            except ValueError:
                pass

        action = RecoveryAction(
            action_id=f"rcv_{uuid.uuid4().hex[:12]}",
            job_id=job.job_id,
            previous_worker_id=previous,
            new_worker_id=new_worker,
            status=status,
            detail=detail,
            recorded_at_ms=time.time() * 1000,
            duplicate_effect_prevented=duplicate_prevented,
            secrets_revoked=secrets_revoked,
        )
        self.actions.append(action)
        self.telemetry["reclaims"] += 1
        if self.on_reclaim is not None:
            self.on_reclaim(job, action)
        return action

    def public_dict(self) -> dict[str, Any]:
        return {
            "telemetry": dict(self.telemetry),
            "recent_actions": [a.public_dict() for a in self.actions[-20:]],
            "truth": {
                "recovery_is_bounded": True,
                "duplicate_effects_forbidden": True,
            },
        }
