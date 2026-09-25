"""Typed CommitIntent / CommitReceipt contracts."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from Data.modules.common.sqlite_policy import WriteClass

COMMIT_INTENT_SCHEMA_VERSION = 1


class CommitPriority(str, Enum):
    P0_SYSTEM = "P0_SYSTEM"
    P1_INTERACTIVE = "P1_INTERACTIVE"
    P2_DOMAIN = "P2_DOMAIN"
    P3_BULK = "P3_BULK"
    P4_MAINTENANCE = "P4_MAINTENANCE"


PRIORITY_RANK: dict[CommitPriority, int] = {
    CommitPriority.P0_SYSTEM: 0,
    CommitPriority.P1_INTERACTIVE: 1,
    CommitPriority.P2_DOMAIN: 2,
    CommitPriority.P3_BULK: 3,
    CommitPriority.P4_MAINTENANCE: 4,
}


class CommitReceiptStatus(str, Enum):
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class AckStatus(str, Enum):
    ACCEPTED_TO_WRITER = "ACCEPTED_TO_WRITER"
    ACCEPTED_TO_SPOOL = "ACCEPTED_TO_SPOOL"
    ALREADY_APPLIED = "ALREADY_APPLIED"
    REJECTED = "REJECTED"
    BACKPRESSURE = "BACKPRESSURE"
    SPOOL_UNAVAILABLE = "SPOOL_UNAVAILABLE"


class CommitHealth(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    BACKPRESSURED = "BACKPRESSURED"
    FAILED = "FAILED"


class FailureKind(str, Enum):
    RETRYABLE = "RETRYABLE"
    TERMINAL = "TERMINAL"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class CommitIntent:
    """Allowlisted commit request. Payload lives in payload_ref, not inline."""

    commit_id: str
    idempotency_key: str
    operation: str
    domain: str
    entity_type: str = ""
    entity_id: str = ""
    payload_ref: str = ""
    payload_hash: str = ""
    write_class: str = WriteClass.COMMIT_WRITE.value
    priority: str = CommitPriority.P2_DOMAIN.value
    record_count_hint: int = 0
    estimated_bytes: int = 0
    created_at: str = ""
    producer_pid: int = 0
    producer_worker_id: str = ""
    source_job_id: str = ""
    trace_id: str = ""
    sequence_key: str = ""
    sequence_number: int = 0
    schema_version: int = COMMIT_INTENT_SCHEMA_VERSION
    safe_human_title: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    batch_index: int = 0
    batch_count: int = 1
    batch_hash: str = ""

    @classmethod
    def create(
        cls,
        *,
        operation: str,
        domain: str,
        idempotency_key: str | None = None,
        entity_type: str = "",
        entity_id: str = "",
        payload_ref: str = "",
        payload_hash: str = "",
        priority: CommitPriority | str = CommitPriority.P2_DOMAIN,
        record_count_hint: int = 0,
        estimated_bytes: int = 0,
        producer_worker_id: str = "",
        source_job_id: str = "",
        trace_id: str = "",
        sequence_key: str = "",
        sequence_number: int = 0,
        safe_human_title: str = "",
        metadata: dict[str, Any] | None = None,
        batch_index: int = 0,
        batch_count: int = 1,
        batch_hash: str = "",
        commit_id: str | None = None,
    ) -> CommitIntent:
        pri = priority.value if isinstance(priority, CommitPriority) else str(priority)
        return cls(
            commit_id=commit_id or str(uuid.uuid4()),
            idempotency_key=idempotency_key or str(uuid.uuid4()),
            operation=str(operation),
            domain=str(domain),
            entity_type=str(entity_type or ""),
            entity_id=str(entity_id or ""),
            payload_ref=str(payload_ref or ""),
            payload_hash=str(payload_hash or ""),
            priority=pri,
            record_count_hint=int(record_count_hint or 0),
            estimated_bytes=int(estimated_bytes or 0),
            created_at=utc_now(),
            producer_pid=os.getpid(),
            producer_worker_id=str(producer_worker_id or ""),
            source_job_id=str(source_job_id or ""),
            trace_id=str(trace_id or ""),
            sequence_key=str(sequence_key or ""),
            sequence_number=int(sequence_number or 0),
            safe_human_title=str(safe_human_title or "")[:120],
            metadata=dict(metadata or {}),
            batch_index=int(batch_index or 0),
            batch_count=max(1, int(batch_count or 1)),
            batch_hash=str(batch_hash or ""),
        )

    def priority_enum(self) -> CommitPriority:
        try:
            return CommitPriority(self.priority)
        except ValueError:
            return CommitPriority.P2_DOMAIN

    def priority_rank(self) -> int:
        return PRIORITY_RANK.get(self.priority_enum(), 2)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommitIntent:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in dict(data or {}).items() if k in known}
        if "metadata" in filtered and not isinstance(filtered["metadata"], dict):
            filtered["metadata"] = {}
        return cls(**filtered)

    @classmethod
    def from_json(cls, text: str) -> CommitIntent:
        return cls.from_dict(json.loads(text))


@dataclass
class CommitReceipt:
    commit_id: str
    idempotency_key: str
    domain: str
    operation: str
    status: str = CommitReceiptStatus.APPLIED.value
    entity_type: str = ""
    entity_id: str = ""
    payload_hash: str = ""
    applied_at: str = ""
    record_count: int = 0
    result_ref: str = ""
    producer_job_id: str = ""
    trace_id: str = ""
    batch_index: int = 0
    batch_count: int = 1
    result: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommitReceipt:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in dict(data or {}).items() if k in known}
        if "result" in filtered and not isinstance(filtered["result"], dict):
            filtered["result"] = {}
        return cls(**filtered)


@dataclass
class WriterAck:
    status: str
    commit_id: str
    message: str = ""
    receipt: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "commit_id": self.commit_id,
            "message": self.message,
            "receipt": self.receipt,
        }
