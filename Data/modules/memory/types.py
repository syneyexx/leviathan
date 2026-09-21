from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MemoryKind(str, Enum):
    NOTE = "NOTE"
    PREFERENCE = "PREFERENCE"
    FACT = "FACT"
    PROCEDURE = "PROCEDURE"
    EPISODIC = "EPISODIC"
    DECISION = "DECISION"


class MemoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    REVOKED = "REVOKED"


@dataclass(frozen=True)
class MemoryRecord:
    """Controlled durable memory — never automatic model-output truth."""

    memory_id: str
    kind: MemoryKind
    status: MemoryStatus
    content: str
    created_at: str
    updated_at: str
    source: str = "manual"
    trust: str = "explicit"  # explicit | imported | derived
    run_id: str | None = None
    conversation_id: str | None = None
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "kind": self.kind.value,
            "status": self.status.value,
            "content": self.content,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source": self.source,
            "trust": self.trust,
            "run_id": self.run_id,
            "conversation_id": self.conversation_id,
            "tags": list(self.tags),
            "metadata": self.metadata,
            "truth": {
                "model_output_is_not_automatic_memory": True,
                "memory_is_not_knowledge": True,
            },
        }

    def as_context_item(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "content": f"[{self.kind.value}/{self.trust}] {self.content}",
            "status": self.status.value,
            "kind": self.kind.value,
        }
