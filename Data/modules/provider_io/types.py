"""Provider execution request/result/stream contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from Data.modules.common.secrets import redact_secrets


class StreamEventType(str, Enum):
    STARTED = "started"
    DELTA = "delta"
    REASONING_DELTA = "reasoning_delta"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    USAGE = "usage"
    WARNING = "warning"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class IdempotencyClass(str, Enum):
    READ = "READ"
    IDEMPOTENT_WRITE = "IDEMPOTENT_WRITE"
    NON_IDEMPOTENT_WRITE = "NON_IDEMPOTENT_WRITE"


@dataclass
class ProviderRequest:
    """Logical outbound provider request (secrets resolved in-worker, never in payload)."""

    provider: str
    capability: str
    """Capability within provider: chat.complete | chat.stream | http | embeddings | market.fetch | hf.list"""

    model: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    """Bounded request body / references — never include raw API keys."""

    streaming: bool = False
    deadline_seconds: float | None = None
    correlation_id: str | None = None
    job_id: str | None = None
    principal_ref: str | None = None
    idempotency_class: IdempotencyClass = IdempotencyClass.READ
    idempotency_key: str | None = None
    credential_ref: str | None = None
    """Logical credential id resolved by the worker (e.g. 'openai', 'web_search')."""

    allow_private_hosts: bool = False
    """Only for explicitly trusted local OpenAI-compatible endpoints."""

    def public_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "capability": self.capability,
            "model": self.model,
            "streaming": self.streaming,
            "deadline_seconds": self.deadline_seconds,
            "correlation_id": self.correlation_id,
            "job_id": self.job_id,
            "principal_ref": self.principal_ref,
            "idempotency_class": self.idempotency_class.value,
            "idempotency_key": self.idempotency_key,
            "credential_ref": self.credential_ref,
            "allow_private_hosts": self.allow_private_hosts,
            "payload_keys": sorted(self.payload.keys()),
        }


@dataclass
class ProviderExecutionResult:
    status: str
    """succeeded | failed | cancelled"""

    content: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    structured: dict[str, Any] | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    provider: str | None = None
    model: str | None = None
    provider_request_id: str | None = None
    timing: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    worker_pid: int | None = None

    def public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "content": self.content,
            "tool_calls": list(self.tool_calls),
            "structured": self.structured,
            "finish_reason": self.finish_reason,
            "usage": dict(self.usage),
            "provider": self.provider,
            "model": self.model,
            "provider_request_id": self.provider_request_id,
            "timing": dict(self.timing),
            "error": self.error,
            "metadata": {
                k: redact_secrets(str(v)) if isinstance(v, str) else v
                for k, v in self.metadata.items()
            },
            "worker_pid": self.worker_pid,
        }
        return payload


@dataclass(frozen=True)
class StreamEvent:
    job_id: str
    sequence: int
    event_type: StreamEventType
    timestamp: str
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "payload": dict(self.payload),
        }
