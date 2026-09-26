"""Agent delegation contracts — parent Cognitive Runtime remains authority."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from Data.modules.agents.governance import (
    DelegationGovernor,
    DelegationViolation,
    GovernanceDecision,
)


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
    # W9 governance fields
    parent_run_id: str | None = None
    delegation_depth: int = 0
    max_delegation_depth: int = 3
    remaining_parent_budget: dict[str, Any] = field(default_factory=dict)
    child_budget: dict[str, Any] = field(default_factory=dict)
    lineage: list[str] = field(default_factory=list)
    memory_scope: str = "AGENT_PRIVATE"
    shared_orchestrator_scope: str | None = None

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
            "parent_run_id": self.parent_run_id,
            "delegation_depth": self.delegation_depth,
            "max_delegation_depth": self.max_delegation_depth,
            "remaining_parent_budget": dict(self.remaining_parent_budget),
            "child_budget": dict(self.child_budget),
            "lineage": list(self.lineage),
            "memory_scope": self.memory_scope,
            "shared_orchestrator_scope": self.shared_orchestrator_scope,
            "truth": {
                "parent_runtime_remains_authority": True,
                "agents_have_no_private_gateway": True,
                "child_authority_le_parent": True,
                "child_budget_from_parent": True,
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

    def __init__(self, *, governor: DelegationGovernor | None = None) -> None:
        self._handlers: dict[str, DelegateHandler] = {}
        self.governor = governor or DelegationGovernor()

    def register(self, agent_kind: str, handler: DelegateHandler) -> None:
        self._handlers[agent_kind.strip().lower()] = handler

    def available(self) -> list[str]:
        return sorted(self._handlers)

    def delegate(self, request: DelegateRequest) -> DelegateResult:
        kind = request.agent_kind.strip().lower()
        parent_budget = request.remaining_parent_budget or request.budget
        decision: GovernanceDecision = self.governor.authorize(
            parent_run_id=request.parent_run_id or request.parent_trace_id or request.task_ref or "",
            agent_kind=kind,
            child_id=request.delegation_id,
            parent_authority=request.authority_ceiling,
            requested_authority=str(
                request.metadata.get("requested_authority") or request.authority_ceiling
            ),
            delegation_depth=int(request.delegation_depth or 0),
            max_delegation_depth=int(request.max_delegation_depth or 3),
            remaining_parent_budget=parent_budget,
            lineage=request.lineage,
            conversation_id=str(request.metadata.get("conversation_id") or "") or None,
            memory_scope=request.memory_scope,
            shared_orchestrator_scope=request.shared_orchestrator_scope,
        )
        if not decision.allowed or decision.frame is None:
            violation = decision.violation.value if decision.violation else "REFUSED"
            return DelegateResult(
                delegation_id=request.delegation_id,
                status="REFUSED",
                summary=f"delegation governance refused: {decision.reason}",
                unresolved_issues=[f"governance:{violation}"],
                error=f"DELEGATION_{violation}",
                metadata=decision.public_dict(),
            )
        # Apply governed ceilings onto the request before handler runs.
        frame = decision.frame
        request.authority_ceiling = frame.child_authority
        request.child_budget = dict(frame.child_budget)
        request.budget = dict(frame.child_budget) if frame.child_budget else dict(request.budget)
        request.delegation_depth = frame.delegation_depth
        request.lineage = list(frame.lineage)
        request.metadata["governance"] = frame.public_dict()
        request.metadata["authority_clamped"] = bool(decision.metadata.get("authority_clamped"))

        handler = self._handlers.get(kind)
        if handler is None:
            self.governor.close(request.delegation_id)
            return DelegateResult(
                delegation_id=request.delegation_id,
                status="UNAVAILABLE",
                summary=f"No handler registered for agent_kind={kind}",
                unresolved_issues=[f"missing_handler:{kind}"],
                error="COGNITION_DELEGATION_FAILED",
                metadata={"governance": frame.public_dict()},
            )
        try:
            result = handler(request)
            result.metadata.setdefault("authority_ceiling", request.authority_ceiling)
            result.metadata.setdefault("parent_trace_id", request.parent_trace_id)
            result.metadata.setdefault("parent_run_id", request.parent_run_id)
            result.metadata.setdefault("delegation_depth", request.delegation_depth)
            result.metadata.setdefault("max_delegation_depth", request.max_delegation_depth)
            result.metadata.setdefault("child_budget", dict(request.child_budget))
            result.metadata.setdefault("lineage", list(request.lineage))
            result.metadata.setdefault("governance", frame.public_dict())
            return result
        except Exception as exc:  # noqa: BLE001
            return DelegateResult(
                delegation_id=request.delegation_id,
                status="FAILED",
                summary="delegate handler raised",
                error=f"{type(exc).__name__}: {exc}",
                metadata={"governance": frame.public_dict()},
            )
        finally:
            self.governor.close(request.delegation_id)

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
        parent_run_id: str | None = None,
        delegation_depth: int = 0,
        max_delegation_depth: int = 3,
        remaining_parent_budget: dict[str, Any] | None = None,
        lineage: list[str] | None = None,
        memory_scope: str = "AGENT_PRIVATE",
        shared_orchestrator_scope: str | None = None,
    ) -> DelegateRequest:
        parent_budget = dict(remaining_parent_budget or budget or {})
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
            parent_run_id=parent_run_id,
            delegation_depth=delegation_depth,
            max_delegation_depth=max_delegation_depth,
            remaining_parent_budget=parent_budget,
            lineage=list(lineage or []),
            memory_scope=memory_scope,
            shared_orchestrator_scope=shared_orchestrator_scope,
        )


__all__ = [
    "DelegateHandler",
    "DelegateRequest",
    "DelegateResult",
    "DelegationService",
    "DelegationGovernor",
    "DelegationViolation",
    "GovernanceDecision",
]
