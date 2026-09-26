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
    RELATION = "RELATION"
    SUMMARY = "SUMMARY"
    RESIDUE = "RESIDUE"
    # Wave 4 taxonomy extensions (U082)
    COMMITMENT = "COMMITMENT"
    CORRECTION = "CORRECTION"
    PROJECT = "PROJECT"


class MemoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class MemoryScope(str, Enum):
    """Retrieval scopes — cross-scope leakage must be filtered (U085 / exit gate)."""

    GLOBAL = "GLOBAL"
    USER = "USER"
    WORKSPACE = "WORKSPACE"
    PROJECT = "PROJECT"
    CONVERSATION = "CONVERSATION"
    AGENT_PRIVATE = "AGENT_PRIVATE"
    # W9: explicit shared scope for orchestrator-coordinated multi-agent memory.
    ORCHESTRATOR_SHARED = "ORCHESTRATOR_SHARED"


class MemoryTrustState(str, Enum):
    """Explicit memory trust — LLM confidence never becomes truth (W8)."""

    AGENT_PROPOSED = "AGENT_PROPOSED"
    USER_STATED = "USER_STATED"
    SOURCE_DERIVED = "SOURCE_DERIVED"
    VERIFIED = "VERIFIED"
    CONFLICTED = "CONFLICTED"
    REVOKED = "REVOKED"


# Map legacy trust strings → MemoryTrustState.
LEGACY_TRUST_MAP: dict[str, MemoryTrustState] = {
    "explicit": MemoryTrustState.USER_STATED,
    "imported": MemoryTrustState.SOURCE_DERIVED,
    "derived": MemoryTrustState.SOURCE_DERIVED,
    "model_output": MemoryTrustState.AGENT_PROPOSED,
    "agent": MemoryTrustState.AGENT_PROPOSED,
    "verified": MemoryTrustState.VERIFIED,
}


def normalize_trust_state(raw: str | MemoryTrustState | None) -> MemoryTrustState:
    if isinstance(raw, MemoryTrustState):
        return raw
    text = str(raw or "AGENT_PROPOSED").strip()
    try:
        return MemoryTrustState(text)
    except ValueError:
        return LEGACY_TRUST_MAP.get(text.lower(), MemoryTrustState.AGENT_PROPOSED)


# Higher = keep longer under budget pressure.
MEMORY_KIND_PRIORITY: dict[MemoryKind, float] = {
    MemoryKind.DECISION: 1.0,
    MemoryKind.COMMITMENT: 0.98,
    MemoryKind.CORRECTION: 0.97,
    MemoryKind.PREFERENCE: 0.95,
    MemoryKind.FACT: 0.85,
    MemoryKind.PROCEDURE: 0.8,
    MemoryKind.PROJECT: 0.78,
    MemoryKind.EPISODIC: 0.7,
    MemoryKind.RELATION: 0.65,
    MemoryKind.SUMMARY: 0.55,
    MemoryKind.NOTE: 0.4,
    MemoryKind.RESIDUE: 0.25,
}


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
    priority: float = 0.5
    # Wave 4 scoping / provenance (U083–U087)
    scope: MemoryScope = MemoryScope.CONVERSATION
    workspace_id: str | None = None
    project_id: str | None = None
    user_id: str | None = None
    confidence: float = 0.5
    valid_from: str | None = None
    valid_until: str | None = None
    supersedes_id: str | None = None
    source_refs: tuple[str, ...] = ()

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
            "priority": self.priority,
            "scope": self.scope.value,
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "user_id": self.user_id,
            "confidence": self.confidence,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "supersedes_id": self.supersedes_id,
            "source_refs": list(self.source_refs),
            "truth": {
                "model_output_is_not_automatic_memory": True,
                "memory_is_not_knowledge": True,
                "model_generated_memory_is_not_evidence": True,
                "scope_filter_required_for_retrieval": True,
            },
        }

    def as_context_item(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "content": f"[{self.kind.value}/{self.trust}/{self.scope.value}] {self.content}",
            "status": self.status.value,
            "kind": self.kind.value,
            "priority": self.priority,
            "scope": self.scope.value,
            "conversation_id": self.conversation_id,
            "project_id": self.project_id,
        }
