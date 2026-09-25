"""Delivery lifecycle helpers — ACK, retry backoff, dead-letter transitions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .envelope import AgentSignal, AgentSignalDeadLetter, AgentSignalDelivery, utc_now
from .types import DEFAULT_RETRY_ATTEMPTS, DeliveryState, SignalStatus
from .store import SignalStore

if TYPE_CHECKING:
    pass


def backoff_seconds(attempt: int, *, base: float = 2.0, cap: float = 300.0) -> float:
    """Exponential backoff with cap. attempt is 1-based post-failure count."""
    n = max(1, int(attempt))
    return min(cap, base ** n)


class DeliveryManager:
    def __init__(self, store: SignalStore, *, max_attempts: int = DEFAULT_RETRY_ATTEMPTS) -> None:
        self.store = store
        self.max_attempts = max_attempts

    def mark_delivered(self, delivery: AgentSignalDelivery) -> AgentSignalDelivery:
        delivery.state = DeliveryState.DELIVERED
        delivery.delivered_at = utc_now()
        delivery.claimed_by = None
        delivery.lease_expires_at = None
        return self.store.update_delivery(delivery)

    def record_failure(
        self,
        delivery: AgentSignalDelivery,
        signal: AgentSignal,
        *,
        error: str,
        retryable: bool = True,
    ) -> AgentSignalDelivery | AgentSignalDeadLetter:
        delivery.last_error = error[:500]
        limit = int(delivery.max_attempts or self.max_attempts)
        if (not retryable) or delivery.attempt_count >= limit:
            return self.dead_letter(delivery, signal, reason="retry_exhausted", error=error)
        delay = backoff_seconds(delivery.attempt_count)
        updated = self.store.schedule_retry(delivery.delivery_id, delay_seconds=delay, error=error)
        return updated or delivery

    def dead_letter(
        self,
        delivery: AgentSignalDelivery,
        signal: AgentSignal,
        *,
        reason: str,
        error: str,
        retryable: bool = True,
    ) -> AgentSignalDeadLetter:
        now = utc_now()
        dead = AgentSignalDeadLetter(
            dead_letter_id=SignalStore.new_id("sdl"),
            signal_id=signal.signal_id,
            delivery_id=delivery.delivery_id,
            recipient_type=delivery.recipient_type.value,
            recipient_id=delivery.recipient_id,
            attempt_count=delivery.attempt_count,
            last_error=error[:500],
            first_failure_at=delivery.metadata.get("first_failure_at") or now,
            last_failure_at=now,
            reason=reason,
            retryable=retryable,
            signal_snapshot=signal.public_dict(),
            created_at=now,
        )
        return self.store.move_dead_letter(dead)

    def retry_dead_letter(self, dead_letter_id: str) -> AgentSignalDelivery | None:
        dead = self.store.get_dead_letter(dead_letter_id)
        if dead is None or not dead.retryable:
            return None
        signal = self.store.get_signal(dead.signal_id)
        if signal is None:
            return None
        now = utc_now()
        delivery = AgentSignalDelivery(
            delivery_id=SignalStore.new_id("sdel"),
            signal_id=signal.signal_id,
            recipient_type=signal.recipient_type,
            recipient_id=signal.recipient_id,
            resolved_agent_id=dead.recipient_id if dead.recipient_type == "AGENT" else None,
            state=DeliveryState.PENDING,
            attempt_count=0,
            max_attempts=self.max_attempts,
            created_at=now,
            updated_at=now,
            metadata={"retried_from": dead_letter_id, "manual_retry": True},
        )
        self.store.create_delivery(delivery)
        self.store.update_signal_status(signal.signal_id, SignalStatus.ROUTED)
        self.store.mark_dead_letter_retried(dead_letter_id)
        return delivery
