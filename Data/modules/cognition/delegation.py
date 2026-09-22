"""Agent delegation contracts — parent Cognitive Runtime remains authority."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class DelegateRequest:
    delegation_id: str
    goal: str
    task_ref: str | None
    provided_context_refs: list[str] = field(default_factory=list)
    authority_ceiling: str = "MEDIUM"
    allowed_capabilities: list[str] = field(default_factory=list)
    forbidden_capabilities: list[str] = field(default_factory=list)
    budget: dict[str, Any] = field(default_factory=dict)
    expected_output: str | None = None
    success_criteria: list[str] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    timeout_seconds: float = 120.0
    parent_trace_id: str | None = None
    agent_kind: str = "generic"
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "delegation_id": self.delegation_id,
            "goal": self.goal,
            "task_ref": self.task_ref,
            "provided_context_refs": list(self.provided_context_refs),
            "authority_ceiling": self.authority_ceiling,
            "allowed_capabilities": list(self.allowed_capabilities),
            "forbidden_capabilities": list(self.forbidden_capabilities),
            "budget": dict(self.budget),
            "expected_output": self.expected_output,
            "success_criteria": list(self.success_criteria),
            "required_evidence": list(self.required_evidence),
            "timeout_seconds": self.timeout_seconds,
            "parent_trace_id": self.parent_trace_id,
            "agent_kind": self.agent_kind,
            "metadata": self.metadata,
            "truth": {
                "parent_runtime_remains_authority": True,
                "agents_have_no_private_gateway": True,
            },
        }


@dataclass
class DelegateResult:
    delegation_id: str
    status: str
    summary: str
    observations: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    unresolved_issues: list[str] = field(default_factory=list)
    resource_use: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "delegation_id": self.delegation_id,
            "status": self.status,
            "summary": self.summary,
            "observations": list(self.observations),
            "evidence_refs": list(self.evidence_refs),
            "artifact_refs": list(self.artifact_refs),
            "unresolved_issues": list(self.unresolved_issues),
            "resource_use": dict(self.resource_use),
            "error": self.error,
            "metadata": self.metadata,
        }


DelegateHandler = Callable[[DelegateRequest], DelegateResult]


class DelegationService:
    """Route bounded DelegateRequests to specialist runtimes when registered."""

    def __init__(self) -> None:
        self._handlers: dict[str, DelegateHandler] = {}

    def register(self, agent_kind: str, handler: DelegateHandler) -> None:
        self._handlers[agent_kind.strip().lower()] = handler

    def available(self) -> list[str]:
        return sorted(self._handlers)

    def delegate(self, request: DelegateRequest) -> DelegateResult:
        kind = request.agent_kind.strip().lower()
        handler = self._handlers.get(kind)
        if handler is None:
            return DelegateResult(
                delegation_id=request.delegation_id,
                status="UNAVAILABLE",
                summary=f"No handler registered for agent_kind={kind}",
                unresolved_issues=[f"missing_handler:{kind}"],
                error="COGNITION_DELEGATION_FAILED",
            )
        try:
            result = handler(request)
            # Enforce authority ceiling metadata honesty.
            result.metadata.setdefault("authority_ceiling", request.authority_ceiling)
            result.metadata.setdefault("parent_trace_id", request.parent_trace_id)
            return result
        except Exception as exc:  # noqa: BLE001
            return DelegateResult(
                delegation_id=request.delegation_id,
                status="FAILED",
                summary="delegate handler raised",
                error=f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def build_request(
        *,
        goal: str,
        agent_kind: str,
        task_ref: str | None = None,
        success_criteria: list[str] | None = None,
        authority_ceiling: str = "MEDIUM",
        budget: dict[str, Any] | None = None,
        parent_trace_id: str | None = None,
        required_evidence: list[str] | None = None,
        timeout_seconds: float = 120.0,
    ) -> DelegateRequest:
        return DelegateRequest(
            delegation_id=str(uuid.uuid4()),
            goal=goal,
            task_ref=task_ref,
            agent_kind=agent_kind,
            success_criteria=list(success_criteria or []),
            authority_ceiling=authority_ceiling,
            budget=dict(budget or {}),
            parent_trace_id=parent_trace_id,
            required_evidence=list(required_evidence or []),
            timeout_seconds=timeout_seconds,
        )
