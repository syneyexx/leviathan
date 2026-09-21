from __future__ import annotations

import hashlib
import json
from typing import Any

from Data.modules.function_runtime.types import SideEffect

from .policy import PolicyEngine
from .store import ApprovalStore
from .types import ApprovalRecord, ApprovalStatus, PolicyDecision


class ApprovalService:
    """Request / decide / verify approvals for gated capabilities."""

    def __init__(self, store: ApprovalStore, policy: PolicyEngine | None = None) -> None:
        self.store = store
        self.policy = policy or PolicyEngine()

    def evaluate_policy(self, side_effects: tuple[SideEffect, ...]) -> PolicyDecision:
        return self.policy.evaluate(side_effects)

    def request(
        self,
        *,
        capability_id: str,
        side_effects: tuple[SideEffect, ...] | list[SideEffect] | tuple[str, ...] | list[str],
        requested_by: str = "api",
        reason: str | None = None,
        run_id: str | None = None,
        expires_at: str | None = None,
        single_use: bool = True,
        arguments: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalRecord:
        normalized = tuple(
            item.value if isinstance(item, SideEffect) else str(item) for item in side_effects
        )
        digest = None
        if arguments is not None:
            digest = hashlib.sha256(
                json.dumps(arguments, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
        return self.store.create(
            capability_id=capability_id,
            side_effects=normalized,
            requested_by=requested_by,
            reason=reason,
            run_id=run_id,
            expires_at=expires_at,
            single_use=single_use,
            arguments_digest=digest,
            metadata=metadata,
        )

    def approve(
        self,
        approval_id: str,
        *,
        decided_by: str = "operator",
        reason: str | None = None,
    ) -> ApprovalRecord:
        record = self.store.set_status(
            approval_id,
            ApprovalStatus.APPROVED,
            decided_by=decided_by,
            reason=reason,
        )
        if record is None:
            raise KeyError(f"Unknown approval: {approval_id}")
        return record

    def deny(
        self,
        approval_id: str,
        *,
        decided_by: str = "operator",
        reason: str | None = None,
    ) -> ApprovalRecord:
        record = self.store.set_status(
            approval_id,
            ApprovalStatus.DENIED,
            decided_by=decided_by,
            reason=reason,
        )
        if record is None:
            raise KeyError(f"Unknown approval: {approval_id}")
        return record

    def get(self, approval_id: str) -> ApprovalRecord | None:
        record = self.store.get(approval_id)
        if record is None:
            return None
        return self._expire_if_needed(record)

    def list(
        self,
        *,
        status: ApprovalStatus | None = None,
        capability_id: str | None = None,
        limit: int = 100,
    ) -> list[ApprovalRecord]:
        return [
            self._expire_if_needed(item) or item
            for item in self.store.list(status=status, capability_id=capability_id, limit=limit)
        ]

    def is_approved(
        self,
        approval_id: str,
        *,
        capability_id: str,
        side_effects: tuple[SideEffect, ...],
    ) -> bool:
        record = self.get(approval_id)
        if record is None:
            return False
        if record.status != ApprovalStatus.APPROVED:
            return False
        if record.capability_id != capability_id:
            return False
        required = {e.value for e in side_effects if e.value != SideEffect.READ.value}
        granted = set(record.side_effects)
        # Approval must cover every gated effect on the capability.
        if required and not required.issubset(granted | {SideEffect.READ.value}):
            # Allow approvals that list the gated effects explicitly, or that
            # were issued for the same capability with a superset of effects.
            if not required.issubset(granted):
                return False
        return True

    def consume_if_single_use(self, approval_id: str) -> ApprovalRecord | None:
        return self.store.consume(approval_id)

    def _expire_if_needed(self, record: ApprovalRecord) -> ApprovalRecord:
        if record.status not in {ApprovalStatus.PENDING, ApprovalStatus.APPROVED}:
            return record
        if not record.expires_at:
            return record
        from .store import utc_now

        if record.expires_at <= utc_now():
            updated = self.store.set_status(
                record.approval_id,
                ApprovalStatus.EXPIRED,
                decided_by="system",
                reason="expired",
            )
            return updated or record
        return record
