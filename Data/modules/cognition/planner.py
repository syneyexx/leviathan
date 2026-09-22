"""Structured planner — public plan steps with acceptance conditions."""

from __future__ import annotations

import uuid
from typing import Any

from .meta_controller import MetaDecision
from .task_model import TaskModel
from .types import CognitivePlan, PlanStep, ReasoningStrategy, RiskClass


class CognitivePlanner:
    """Produce bounded structured plans. Domain planners may specialize later."""

    def plan(self, task: TaskModel, decision: MetaDecision) -> CognitivePlan:
        strategy = decision.strategy
        steps = self._steps_for(task, strategy)
        assumptions = list(task.ambiguities)
        if task.unknowns:
            assumptions.extend(f"unknown:{u}" for u in task.unknowns[:3])
        return CognitivePlan(
            plan_id=str(uuid.uuid4()),
            strategy=strategy,
            steps=steps,
            assumptions=assumptions,
            stale=False,
            revision=0,
        )

    def replan(
        self,
        task: TaskModel,
        decision: MetaDecision,
        *,
        previous: CognitivePlan | None,
        reason: str,
    ) -> CognitivePlan:
        plan = self.plan(task, decision)
        plan.revision = (previous.revision + 1) if previous else 1
        plan.assumptions.append(f"replan_reason:{reason}")
        return plan

    def mark_stale(self, plan: CognitivePlan, *, reason: str) -> CognitivePlan:
        plan.stale = True
        plan.assumptions.append(f"stale:{reason}")
        return plan

    def _steps_for(self, task: TaskModel, strategy: ReasoningStrategy) -> list[PlanStep]:
        risk = task.risk_class
        if strategy == ReasoningStrategy.DIRECT:
            return [
                PlanStep(
                    step_id="s1",
                    objective="Answer the request directly",
                    expected_observation="model text reply",
                    acceptance_condition=task.success_criteria[0] if task.success_criteria else "reply produced",
                    risk_class=risk,
                )
            ]
        if strategy == ReasoningStrategy.RETRIEVE_THEN_ANSWER:
            return [
                PlanStep(
                    step_id="s1",
                    objective="Retrieve relevant knowledge/memory/evidence",
                    expected_observation="perception snapshot with sources",
                    acceptance_condition="at least one relevant source or honest empty",
                    likely_capabilities=("knowledge.search",),
                    risk_class=RiskClass.LOW,
                ),
                PlanStep(
                    step_id="s2",
                    objective="Produce grounded answer",
                    dependencies=("s1",),
                    expected_observation="model reply citing retrieved refs when present",
                    acceptance_condition="goal addressed without fabricated tool use",
                    risk_class=risk,
                ),
            ]
        if strategy == ReasoningStrategy.CODING_REPAIR:
            return [
                PlanStep(
                    step_id="s1",
                    objective="Inspect relevant workspace / reproduce failure",
                    expected_observation="file or test observation",
                    acceptance_condition="failure context recorded",
                    likely_capabilities=("coding.session",),
                    risk_class=RiskClass.MEDIUM,
                ),
                PlanStep(
                    step_id="s2",
                    objective="Form hypothesis and propose minimal patch",
                    dependencies=("s1",),
                    expected_observation="edit plan or patch proposal",
                    acceptance_condition="hypothesis linked to observation",
                    risk_class=RiskClass.HIGH if risk == RiskClass.CRITICAL else RiskClass.MEDIUM,
                ),
                PlanStep(
                    step_id="s3",
                    objective="Apply authorized changes and run tests",
                    dependencies=("s2",),
                    expected_observation="test/observation receipt",
                    acceptance_condition="tests observed; approval respected",
                    likely_capabilities=("coding.session",),
                    risk_class=RiskClass.HIGH,
                ),
                PlanStep(
                    step_id="s4",
                    objective="Verify against acceptance criteria",
                    dependencies=("s3",),
                    expected_observation="verification report",
                    acceptance_condition="criteria met or PARTIAL honest",
                    risk_class=risk,
                ),
            ]
        if strategy == ReasoningStrategy.DEBUG_LOOP:
            return [
                PlanStep(
                    step_id="s1",
                    objective="Collect failure signals and form hypothesis",
                    expected_observation="hypothesis belief",
                    acceptance_condition="hypothesis recorded with next info needed",
                    risk_class=RiskClass.MEDIUM,
                ),
                PlanStep(
                    step_id="s2",
                    objective="Run bounded diagnostic action",
                    dependencies=("s1",),
                    expected_observation="observation supporting or contradicting hypothesis",
                    acceptance_condition="belief updated from observation",
                    risk_class=risk,
                ),
                PlanStep(
                    step_id="s3",
                    objective="Conclude or replan",
                    dependencies=("s2",),
                    expected_observation="updated plan or answer",
                    acceptance_condition="no ineffective action loop",
                    risk_class=risk,
                ),
            ]
        if strategy == ReasoningStrategy.RESEARCH_SYNTHESIS:
            return [
                PlanStep(
                    step_id="s1",
                    objective="Acquire sources and extract claims",
                    expected_observation="research evidence/claims",
                    acceptance_condition="sources recorded",
                    likely_capabilities=("research.run",),
                    risk_class=RiskClass.MEDIUM,
                ),
                PlanStep(
                    step_id="s2",
                    objective="Surface conflicts without fake certainty",
                    dependencies=("s1",),
                    expected_observation="conflict ledger / belief contradictions",
                    acceptance_condition="conflicts explicit when present",
                    risk_class=RiskClass.MEDIUM,
                ),
                PlanStep(
                    step_id="s3",
                    objective="Synthesize evidence-backed answer",
                    dependencies=("s2",),
                    expected_observation="synthesis with evidence refs",
                    acceptance_condition="claims linked to evidence",
                    risk_class=risk,
                ),
            ]
        if strategy == ReasoningStrategy.HIGH_RISK_VERIFY:
            return [
                PlanStep(
                    step_id="s1",
                    objective="Clarify constraints and required approvals",
                    expected_observation="constraints + approval gate",
                    acceptance_condition="risk acknowledged",
                    risk_class=RiskClass.HIGH,
                ),
                PlanStep(
                    step_id="s2",
                    objective="Execute only authorized actions",
                    dependencies=("s1",),
                    expected_observation="effect receipts",
                    acceptance_condition="no unauthorized side effects",
                    risk_class=RiskClass.CRITICAL,
                ),
                PlanStep(
                    step_id="s3",
                    objective="Verify postconditions",
                    dependencies=("s2",),
                    expected_observation="verification report",
                    acceptance_condition="verification passed or failed honestly",
                    risk_class=RiskClass.HIGH,
                ),
            ]
        if strategy == ReasoningStrategy.PLAN_EXECUTE_VERIFY:
            return [
                PlanStep(
                    step_id="s1",
                    objective="Plan minimal steps toward goal",
                    expected_observation="structured plan",
                    acceptance_condition="steps have acceptance conditions",
                    risk_class=RiskClass.LOW,
                ),
                PlanStep(
                    step_id="s2",
                    objective="Execute next authorized action",
                    dependencies=("s1",),
                    expected_observation="action observation",
                    acceptance_condition="observation recorded",
                    risk_class=risk,
                ),
                PlanStep(
                    step_id="s3",
                    objective="Verify progress against criteria",
                    dependencies=("s2",),
                    expected_observation="criteria progress",
                    acceptance_condition="progress or honest blocker",
                    risk_class=risk,
                ),
            ]
        if strategy == ReasoningStrategy.TOOL_DRIVEN:
            return [
                PlanStep(
                    step_id="s1",
                    objective="Search and shortlist relevant capabilities",
                    expected_observation="capability shortlist",
                    acceptance_condition="shortlist without schema dump",
                    risk_class=RiskClass.LOW,
                ),
                PlanStep(
                    step_id="s2",
                    objective="Invoke authorized capability via ExecutionGateway",
                    dependencies=("s1",),
                    expected_observation="tool observation",
                    acceptance_condition="gateway path used",
                    risk_class=risk,
                ),
                PlanStep(
                    step_id="s3",
                    objective="Integrate observation into answer",
                    dependencies=("s2",),
                    expected_observation="final reply",
                    acceptance_condition="tool data treated as untrusted content",
                    risk_class=risk,
                ),
            ]
        if strategy == ReasoningStrategy.COMPARE_ALTERNATIVES:
            return [
                PlanStep(
                    step_id="s1",
                    objective="Generate 2–3 bounded candidate approaches",
                    expected_observation="candidate list",
                    acceptance_condition="candidates scored",
                    risk_class=RiskClass.LOW,
                ),
                PlanStep(
                    step_id="s2",
                    objective="Select best candidate and execute",
                    dependencies=("s1",),
                    expected_observation="selected plan execution",
                    acceptance_condition="selection rationale public",
                    risk_class=risk,
                ),
            ]
        if strategy == ReasoningStrategy.MULTI_AGENT:
            return [
                PlanStep(
                    step_id="s1",
                    objective="Delegate only if value justifies cost",
                    expected_observation="delegate request/result",
                    acceptance_condition="bounded authority envelope",
                    risk_class=risk,
                ),
                PlanStep(
                    step_id="s2",
                    objective="Integrate specialist results and verify",
                    dependencies=("s1",),
                    expected_observation="integrated outcome",
                    acceptance_condition="parent runtime remains authority",
                    risk_class=risk,
                ),
            ]
        # HYPOTHESIS_TEST default-ish
        return [
            PlanStep(
                step_id="s1",
                objective="State hypothesis and predicted observation",
                expected_observation="hypothesis belief",
                acceptance_condition="hypothesis recorded",
                risk_class=RiskClass.LOW,
            ),
            PlanStep(
                step_id="s2",
                objective="Gather observation to test hypothesis",
                dependencies=("s1",),
                expected_observation="supporting or contradicting observation",
                acceptance_condition="belief updated",
                risk_class=risk,
            ),
            PlanStep(
                step_id="s3",
                objective="Answer with calibrated confidence",
                dependencies=("s2",),
                expected_observation="final reply",
                acceptance_condition="uncertainty reflected",
                risk_class=risk,
            ),
        ]

    def score_candidates(
        self,
        candidates: list[CognitivePlan],
        *,
        task: TaskModel,
        evidence_coverage: float = 0.0,
    ) -> list[tuple[float, CognitivePlan]]:
        scored: list[tuple[float, CognitivePlan]] = []
        for plan in candidates[:4]:
            score = 0.4
            if plan.strategy.value.lower() in task.domain:
                score += 0.2
            if any(s.risk_class.value == task.risk_class.value for s in plan.steps):
                score += 0.1
            if evidence_coverage < 0.3 and plan.strategy in {
                ReasoningStrategy.RETRIEVE_THEN_ANSWER,
                ReasoningStrategy.RESEARCH_SYNTHESIS,
            }:
                score += 0.2
            if len(plan.steps) > 6:
                score -= 0.15
            scored.append((round(score, 3), plan))
        scored.sort(key=lambda p: -p[0])
        return scored
