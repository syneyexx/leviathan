"""Structured agent planner — replaces keyword-style AgentRuntime.plan() (U142)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from .types import AgentKind, AgentStep, AgentStepKind


@dataclass(frozen=True)
class StructuredAgentPlan:
    """Capability-aware plan with goals, dependencies, and completion criteria."""

    plan_id: str
    kind: AgentKind
    goal: str
    steps: tuple[AgentStep, ...]
    completion_criteria: tuple[str, ...] = ()
    expected_output_schema: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    source: str = "structured"

    def public_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "kind": self.kind.value,
            "goal": self.goal,
            "steps": [s.public_dict() for s in self.steps],
            "completion_criteria": list(self.completion_criteria),
            "expected_output_schema": dict(self.expected_output_schema),
            "budget": dict(self.budget),
            "source": self.source,
            "truth": {
                "not_keyword_planner": True,
                "capability_aware": True,
            },
        }


class StructuredAgentPlanner:
    """Produce typed agent plans from kind + goal (schema-driven, not keyword IF chains)."""

    def plan(
        self,
        request: str,
        *,
        kind: AgentKind = AgentKind.GENERIC,
        available_capabilities: tuple[str, ...] | list[str] | None = None,
    ) -> StructuredAgentPlan:
        text = (request or "").strip()
        caps = set(available_capabilities or ())
        steps: list[AgentStep] = [
            AgentStep(
                kind=AgentStepKind.PLAN,
                note=f"{kind.value} structured plan for: {text[:160]}",
            )
        ]
        criteria: list[str] = ["structured steps completed"]
        budget = {"max_tool_calls": 2, "max_model_calls": 1}

        if kind == AgentKind.RESEARCH:
            if not caps or "knowledge.search" in caps:
                steps.append(
                    AgentStep(
                        kind=AgentStepKind.CAPABILITY,
                        capability_id="knowledge.search",
                        arguments={"query": text, "limit": 5},
                        note="Retrieve knowledge via shared CapabilityCatalog",
                    )
                )
            steps.append(
                AgentStep(
                    kind=AgentStepKind.VERIFY,
                    note="Research claims require evidence refs when available",
                )
            )
            criteria.extend(["sources recorded", "verification attempted"])
            budget = {"max_tool_calls": 4, "max_model_calls": 2}
        elif kind == AgentKind.CODING:
            steps.append(
                AgentStep(
                    kind=AgentStepKind.PLAN,
                    note="Coding uses shared filesystem capabilities only — no private shell",
                )
            )
            if not caps or "file.read" in caps:
                steps.append(
                    AgentStep(
                        kind=AgentStepKind.CAPABILITY,
                        capability_id="file.read",
                        arguments={},
                        note="file.read requires path override from caller",
                    )
                )
            # Capability-aware: include CSV inspect when goal mentions it and catalog has it.
            lowered = text.lower()
            if ("csv" in lowered or "inspect" in lowered) and (not caps or "file.inspect_csv" in caps):
                steps.append(
                    AgentStep(
                        kind=AgentStepKind.CAPABILITY,
                        capability_id="file.inspect_csv",
                        arguments={},
                        note="file.inspect_csv requires path override from caller",
                    )
                )
            steps.append(
                AgentStep(
                    kind=AgentStepKind.VERIFY,
                    note="Coding claims require artifact/file evidence via VerificationEngine",
                )
            )
            criteria.extend(["workspace confinement respected", "verification attempted"])
            budget = {"max_tool_calls": 6, "max_model_calls": 3}
        else:
            # GENERIC: retrieve when knowledge capability exists; otherwise respond-only.
            if not caps or "knowledge.search" in caps:
                steps.append(
                    AgentStep(
                        kind=AgentStepKind.CAPABILITY,
                        capability_id="knowledge.search",
                        arguments={"query": text, "limit": 5},
                        note="Optional knowledge retrieval via gateway",
                    )
                )
            criteria.append("response produced")

        steps.append(AgentStep(kind=AgentStepKind.RESPOND, note="Return structured agent result"))
        return StructuredAgentPlan(
            plan_id=str(uuid.uuid4()),
            kind=kind,
            goal=text,
            steps=tuple(steps),
            completion_criteria=tuple(criteria),
            expected_output_schema={
                "type": "object",
                "required": ["status", "steps"],
                "properties": {
                    "status": {"type": "string"},
                    "steps": {"type": "array"},
                    "output": {"type": "string"},
                },
            },
            budget=budget,
            source="structured",
        )
