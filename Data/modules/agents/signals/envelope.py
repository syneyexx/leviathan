"""Canonical durable AgentSignal envelope + delivery / dead-letter records."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .types import (
    ACK_REQUIRED_TYPES,
    DeliveryState,
    RecipientType,
    SenderType,
    SignalPriority,
    SignalStatus,
    SignalType,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


@dataclass
class AgentSignal:
    """Durable coordination envelope. Never stores raw Python objects."""

    signal_id: str
    signal_type: SignalType
    sender_type: SenderType
    sender_id: str
    recipient_type: RecipientType
    recipient_id: str
    mission_id: str | None = None
    run_id: str | None = None
    trace_id: str | None = None
    parent_signal_id: str | None = None
    correlation_id: str | None = None
    priority: SignalPriority = SignalPriority.NORMAL
    subject: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    artifact_refs: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    confidence: float | None = None
    requires_ack: bool = False
    expires_at: str | None = None
    idempotency_key: str | None = None
    hop_count: int = 0
    max_hops: int = 8
    status: SignalStatus = SignalStatus.CREATED
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.signal_type, str):
            self.signal_type = SignalType(self.signal_type)
        if isinstance(self.sender_type, str):
            self.sender_type = SenderType(self.sender_type)
        if isinstance(self.recipient_type, str):
            self.recipient_type = RecipientType(self.recipient_type)
        if isinstance(self.priority, str):
            self.priority = SignalPriority(self.priority)
        if isinstance(self.status, str):
            self.status = SignalStatus(self.status)
        if self.signal_type in ACK_REQUIRED_TYPES:
            self.requires_ack = True
        if not self.created_at:
            self.created_at = utc_now()
        if not self.updated_at:
            self.updated_at = self.created_at

    def public_dict(self) -> dict[str, Any]:
        return {
            "signalId": self.signal_id,
            "signalType": self.signal_type.value,
            "senderType": self.sender_type.value,
            "senderId": self.sender_id,
            "recipientType": self.recipient_type.value,
            "recipientId": self.recipient_id,
            "missionId": self.mission_id,
            "runId": self.run_id,
            "traceId": self.trace_id,
            "parentSignalId": self.parent_signal_id,
            "correlationId": self.correlation_id,
            "priority": self.priority.value,
            "subject": self.subject,
            "payload": dict(self.payload),
            "artifactRefs": list(self.artifact_refs),
            "evidenceRefs": list(self.evidence_refs),
            "confidence": self.confidence,
            "requiresAck": self.requires_ack,
            "expiresAt": self.expires_at,
            "idempotencyKey": self.idempotency_key,
            "hopCount": self.hop_count,
            "maxHops": self.max_hops,
            "status": self.status.value,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "metadata": dict(self.metadata),
            "truth": {
                "signal_is_not_authority": True,
                "signal_is_not_chat": True,
                "side_effects_via_gateway_only": True,
            },
        }

    @classmethod
    def from_row(cls, row: Any) -> AgentSignal:
        return cls(
            signal_id=row["signal_id"],
            signal_type=SignalType(row["signal_type"]),
            sender_type=SenderType(row["sender_type"]),
            sender_id=row["sender_id"],
            recipient_type=RecipientType(row["recipient_type"]),
            recipient_id=row["recipient_id"],
            mission_id=row["mission_id"],
            run_id=row["run_id"],
            trace_id=row["trace_id"],
            parent_signal_id=row["parent_signal_id"],
            correlation_id=row["correlation_id"],
            priority=SignalPriority(row["priority"] or "NORMAL"),
            subject=row["subject"] or "",
            payload=dict(_loads(row["payload_json"], {})),
            artifact_refs=list(_loads(row["artifact_refs_json"], [])),
            evidence_refs=list(_loads(row["evidence_refs_json"], [])),
            confidence=row["confidence"],
            requires_ack=bool(row["requires_ack"]),
            expires_at=row["expires_at"],
            idempotency_key=row["idempotency_key"],
            hop_count=int(row["hop_count"] or 0),
            max_hops=int(row["max_hops"] or 8),
            status=SignalStatus(row["status"] or "CREATED"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=dict(_loads(row["metadata_json"], {})),
        )


@dataclass
class AgentSignalDelivery:
    delivery_id: str
    signal_id: str
    recipient_type: RecipientType
    recipient_id: str
    resolved_agent_id: str | None = None
    state: DeliveryState = DeliveryState.PENDING
    attempt_count: int = 0
    max_attempts: int = 5
    next_attempt_at: str | None = None
    claimed_by: str | None = None
    claimed_at: str | None = None
    lease_expires_at: str | None = None
    delivered_at: str | None = None
    acknowledged_at: str | None = None
    consumed_at: str | None = None
    ack_consumer: str | None = None
    last_error: str | None = None
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.recipient_type, str):
            self.recipient_type = RecipientType(self.recipient_type)
        if isinstance(self.state, str):
            self.state = DeliveryState(self.state)
        if not self.created_at:
            self.created_at = utc_now()
        if not self.updated_at:
            self.updated_at = self.created_at

    def public_dict(self) -> dict[str, Any]:
        return {
            "deliveryId": self.delivery_id,
            "signalId": self.signal_id,
            "recipientType": self.recipient_type.value,
            "recipientId": self.recipient_id,
            "resolvedAgentId": self.resolved_agent_id,
            "state": self.state.value,
            "attemptCount": self.attempt_count,
            "maxAttempts": self.max_attempts,
            "nextAttemptAt": self.next_attempt_at,
            "claimedBy": self.claimed_by,
            "claimedAt": self.claimed_at,
            "leaseExpiresAt": self.lease_expires_at,
            "deliveredAt": self.delivered_at,
            "acknowledgedAt": self.acknowledged_at,
            "consumedAt": self.consumed_at,
            "ackConsumer": self.ack_consumer,
            "lastError": self.last_error,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_row(cls, row: Any) -> AgentSignalDelivery:
        return cls(
            delivery_id=row["delivery_id"],
            signal_id=row["signal_id"],
            recipient_type=RecipientType(row["recipient_type"]),
            recipient_id=row["recipient_id"],
            resolved_agent_id=row["resolved_agent_id"],
            state=DeliveryState(row["state"]),
            attempt_count=int(row["attempt_count"] or 0),
            max_attempts=int(row["max_attempts"] or 5),
            next_attempt_at=row["next_attempt_at"],
            claimed_by=row["claimed_by"],
            claimed_at=row["claimed_at"],
            lease_expires_at=row["lease_expires_at"],
            delivered_at=row["delivered_at"],
            acknowledged_at=row["acknowledged_at"],
            consumed_at=row["consumed_at"],
            ack_consumer=row["ack_consumer"],
            last_error=row["last_error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=dict(_loads(row["metadata_json"], {})),
        )


@dataclass
class AgentSignalDeadLetter:
    dead_letter_id: str
    signal_id: str
    delivery_id: str | None = None
    recipient_type: str | None = None
    recipient_id: str | None = None
    attempt_count: int = 0
    last_error: str | None = None
    first_failure_at: str | None = None
    last_failure_at: str | None = None
    reason: str = ""
    retryable: bool = True
    signal_snapshot: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    retried_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "deadLetterId": self.dead_letter_id,
            "signalId": self.signal_id,
            "deliveryId": self.delivery_id,
            "recipientType": self.recipient_type,
            "recipientId": self.recipient_id,
            "attemptCount": self.attempt_count,
            "lastError": self.last_error,
            "firstFailureAt": self.first_failure_at,
            "lastFailureAt": self.last_failure_at,
            "reason": self.reason,
            "retryable": self.retryable,
            "signalSnapshot": dict(self.signal_snapshot),
            "createdAt": self.created_at,
            "retriedAt": self.retried_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_row(cls, row: Any) -> AgentSignalDeadLetter:
        return cls(
            dead_letter_id=row["dead_letter_id"],
            signal_id=row["signal_id"],
            delivery_id=row["delivery_id"],
            recipient_type=row["recipient_type"],
            recipient_id=row["recipient_id"],
            attempt_count=int(row["attempt_count"] or 0),
            last_error=row["last_error"],
            first_failure_at=row["first_failure_at"],
            last_failure_at=row["last_failure_at"],
            reason=row["reason"] or "",
            retryable=bool(row["retryable"]),
            signal_snapshot=dict(_loads(row["signal_snapshot_json"], {})),
            created_at=row["created_at"],
            retried_at=row["retried_at"],
            metadata=dict(_loads(row["metadata_json"], {})),
        )


@dataclass
class AgentSignalSubscription:
    subscription_id: str
    subscriber_type: str
    subscriber_id: str
    signal_type: str | None = None
    role: str | None = None
    capability: str | None = None
    mission_id: str | None = None
    enabled: bool = True
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "subscriptionId": self.subscription_id,
            "subscriberType": self.subscriber_type,
            "subscriberId": self.subscriber_id,
            "signalType": self.signal_type,
            "role": self.role,
            "capability": self.capability,
            "missionId": self.mission_id,
            "enabled": self.enabled,
            "createdAt": self.created_at,
            "metadata": dict(self.metadata),
        }
