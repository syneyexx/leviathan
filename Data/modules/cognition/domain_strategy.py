"""Domain cognitive strategy extension point under shared CognitiveRuntime.

One CognitiveRuntime authority. Domains specialize reasoning semantics —
they do not create a second runtime, store, gateway, or model client.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .task_model import TaskModel
from .types import CognitiveAction, CognitivePlan, ReasoningStrategy


@dataclass
class DomainUnderstandResult:
    task_type: str
    goal: str
    acceptance_criteria: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    invariants: list[str] = field(default_factory=list)
    risk: str = "LOW"
    ambiguities: list[str] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "taskType": self.task_type,
            "goal": self.goal,
            "acceptanceCriteria": list(self.acceptance_criteria),
            "constraints": list(self.constraints),
            "invariants": list(self.invariants),
            "risk": self.risk,
            "ambiguities": list(self.ambiguities),
            "requiredEvidence": list(self.required_evidence),
            "metadata": dict(self.metadata),
        }


@dataclass
class DomainHypothesis:
    id: str
    statement: str
    supporting: list[str] = field(default_factory=list)
    contradicting: list[str] = field(default_factory=list)
    test_action: str = ""
    status: str = "OPEN"  # OPEN | SUPPORTED | WEAKENED | REJECTED | RESOLVED

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "statement": self.statement,
            "supporting": list(self.supporting),
            "contradicting": list(self.contradicting),
            "testAction": self.test_action,
            "status": self.status,
        }


@runtime_checkable
class DomainCognitiveStrategy(Protocol):
    """Specialized cognition semantics for one domain under One Brain."""

    domain: str

    def understand(self, task: TaskModel, *, text: str | None = None) -> DomainUnderstandResult:
        ...

    def enrich_context_request(self, task: TaskModel, understand: DomainUnderstandResult) -> dict[str, Any]:
        """Return BrainContextRequest field overrides (queries, symbols, etc.)."""
        ...

    def plan(
        self,
        task: TaskModel,
        understand: DomainUnderstandResult,
        *,
        observations: list[dict[str, Any]] | None = None,
        prior_plan: CognitivePlan | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...

    def propose_actions(
        self,
        task: TaskModel,
        understand: DomainUnderstandResult,
        plan: dict[str, Any],
        *,
        phase: str | None = None,
    ) -> list[CognitiveAction] | list[dict[str, Any]]:
        ...

    def observe(self, observation: dict[str, Any], *, state: dict[str, Any]) -> dict[str, Any]:
        ...

    def evaluate(self, *, state: dict[str, Any], understand: DomainUnderstandResult) -> dict[str, Any]:
        ...

    def verify(self, *, state: dict[str, Any], understand: DomainUnderstandResult) -> dict[str, Any]:
        ...

    def completion_requirements(self, understand: DomainUnderstandResult) -> list[str]:
        ...

    def preferred_strategy(self, understand: DomainUnderstandResult) -> ReasoningStrategy | str:
        ...


class StrategyRegistry:
    """Register domain strategies without forking CognitiveRuntime."""

    def __init__(self) -> None:
        self._strategies: dict[str, DomainCognitiveStrategy] = {}

    def register(self, strategy: DomainCognitiveStrategy) -> None:
        self._strategies[str(strategy.domain).strip().lower()] = strategy

    def get(self, domain: str) -> DomainCognitiveStrategy | None:
        return self._strategies.get(str(domain).strip().lower())

    def domains(self) -> list[str]:
        return sorted(self._strategies)

    def public_dict(self) -> dict[str, Any]:
        return {
            "activeDomainStrategies": self.domains(),
            "truth": {
                "one_cognitive_runtime": True,
                "domain_strategy_is_not_second_runtime": True,
            },
        }
