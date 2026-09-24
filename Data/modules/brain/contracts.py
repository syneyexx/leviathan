"""One-Brain typed access contracts — shared intelligence request/response.

Brain does not own storage. These types describe bounded, provenance-aware
views assembled from Knowledge / Memory / Evidence / Experience / Run owners.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BrainSourceRef:
    """Provenance pointer into an authoritative store."""

    kind: str
    ref_id: str
    label: str = ""
    score: float | None = None
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "refId": self.ref_id,
            "label": self.label,
            "score": self.score,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


@dataclass
class BrainKnowledgeRef:
    ref_id: str
    title: str = ""
    excerpt: str = ""
    source: str = ""
    score: float | None = None
    trust: str = "knowledge"
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "refId": self.ref_id,
            "title": self.title,
            "excerpt": self.excerpt,
            "source": self.source,
            "score": self.score,
            "trust": self.trust,
            "metadata": dict(self.metadata),
        }


@dataclass
class BrainMemoryRef:
    ref_id: str
    content: str = ""
    kind: str = ""
    scope: str = ""
    score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "refId": self.ref_id,
            "content": self.content,
            "kind": self.kind,
            "scope": self.scope,
            "score": self.score,
            "metadata": dict(self.metadata),
        }


@dataclass
class BrainEvidenceRef:
    ref_id: str
    kind: str = ""
    summary: str = ""
    status: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "refId": self.ref_id,
            "kind": self.kind,
            "summary": self.summary,
            "status": self.status,
            "metadata": dict(self.metadata),
        }


@dataclass
class BrainExperienceRef:
    ref_id: str
    statement: str = ""
    domain: str = ""
    admitted: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "refId": self.ref_id,
            "statement": self.statement,
            "domain": self.domain,
            "admitted": self.admitted,
            "metadata": dict(self.metadata),
        }


@dataclass
class DomainContext:
    domain: str
    role: str = "general"
    goal: str = ""
    task_semantics: dict[str, Any] = field(default_factory=dict)
    symbols: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "role": self.role,
            "goal": self.goal,
            "taskSemantics": dict(self.task_semantics),
            "symbols": list(self.symbols),
            "entities": list(self.entities),
            "files": list(self.files),
        }


@dataclass
class RoleContext:
    role: str
    objective: str = ""
    allowed_capabilities: list[str] = field(default_factory=list)
    authority_ceiling: str = "MEDIUM"
    view_hints: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "objective": self.objective,
            "allowedCapabilities": list(self.allowed_capabilities),
            "authorityCeiling": self.authority_ceiling,
            "viewHints": list(self.view_hints),
        }


@dataclass
class BrainContextRequest:
    """Typed request for bounded One-Brain context assembly."""

    goal: str
    domain: str = "general"
    role: str = "general"
    run_id: str | None = None
    trace_id: str | None = None
    conversation_id: str | None = None
    project_id: str | None = None
    workspace_root: str | None = None
    queries: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    knowledge_scopes: list[str] = field(default_factory=list)
    memory_scopes: list[str] = field(default_factory=list)
    include_evidence: bool = True
    include_experience: bool = True
    include_capabilities: bool = False
    freshness: str = "any"
    token_budget: int = 1200
    result_limits: dict[str, int] = field(default_factory=dict)
    authority_ceiling: str = "MEDIUM"
    provenance_required: bool = True
    task_semantics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "domain": self.domain,
            "role": self.role,
            "runId": self.run_id,
            "traceId": self.trace_id,
            "conversationId": self.conversation_id,
            "projectId": self.project_id,
            "workspaceRoot": self.workspace_root,
            "queries": list(self.queries),
            "entities": list(self.entities),
            "symbols": list(self.symbols),
            "files": list(self.files),
            "knowledgeScopes": list(self.knowledge_scopes),
            "memoryScopes": list(self.memory_scopes),
            "includeEvidence": self.include_evidence,
            "includeExperience": self.include_experience,
            "includeCapabilities": self.include_capabilities,
            "freshness": self.freshness,
            "tokenBudget": self.token_budget,
            "resultLimits": dict(self.result_limits),
            "authorityCeiling": self.authority_ceiling,
            "provenanceRequired": self.provenance_required,
            "taskSemantics": dict(self.task_semantics),
            "metadata": dict(self.metadata),
        }


@dataclass
class BrainContext:
    """Bounded, provenance-aware One-Brain context response."""

    request: BrainContextRequest
    knowledge: list[BrainKnowledgeRef] = field(default_factory=list)
    memory: list[BrainMemoryRef] = field(default_factory=list)
    evidence: list[BrainEvidenceRef] = field(default_factory=list)
    experience: list[BrainExperienceRef] = field(default_factory=list)
    capabilities: list[dict[str, Any]] = field(default_factory=list)
    project_context: dict[str, Any] = field(default_factory=dict)
    active_task_state: dict[str, Any] = field(default_factory=dict)
    provenance: list[BrainSourceRef] = field(default_factory=list)
    token_estimate: int = 0
    dropped: list[str] = field(default_factory=list)
    selection_trace: dict[str, Any] = field(default_factory=dict)

    def knowledge_dicts(self) -> list[dict[str, Any]]:
        """Shape suitable for ContextBuilder.knowledge=."""
        out: list[dict[str, Any]] = []
        for item in self.knowledge:
            out.append(
                {
                    "id": item.ref_id,
                    "title": item.title,
                    "content": item.excerpt,
                    "text": item.excerpt,
                    "source": item.source,
                    "score": item.score,
                    "trust": item.trust,
                    **dict(item.metadata),
                }
            )
        return out

    def memory_dicts(self) -> list[dict[str, Any]]:
        return [
            {
                "id": item.ref_id,
                "content": item.content,
                "text": item.content,
                "kind": item.kind,
                "scope": item.scope,
                "score": item.score,
                **dict(item.metadata),
            }
            for item in self.memory
        ]

    def evidence_dicts(self) -> list[dict[str, Any]]:
        return [
            {
                "id": item.ref_id,
                "kind": item.kind,
                "summary": item.summary,
                "content": item.summary,
                "status": item.status,
                **dict(item.metadata),
            }
            for item in self.evidence
        ]

    def public_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.public_dict(),
            "knowledge": [k.public_dict() for k in self.knowledge],
            "memory": [m.public_dict() for m in self.memory],
            "evidence": [e.public_dict() for e in self.evidence],
            "experience": [x.public_dict() for x in self.experience],
            "capabilities": list(self.capabilities),
            "projectContext": dict(self.project_context),
            "activeTaskState": dict(self.active_task_state),
            "provenance": [p.public_dict() for p in self.provenance],
            "tokenEstimate": self.token_estimate,
            "dropped": list(self.dropped),
            "selectionTrace": dict(self.selection_trace),
            "truth": {
                "brain_is_access_facade": True,
                "not_canonical_storage": True,
                "bounded": True,
                "provenance_aware": True,
            },
        }
