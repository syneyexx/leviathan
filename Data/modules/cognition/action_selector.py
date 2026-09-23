"""Action selection — choose next orchestration action."""

from __future__ import annotations

import uuid
from typing import Any

from .belief_state import BeliefState
from .capability_broker import CapabilityBroker
from .meta_controller import MetaDecision
from .task_model import TaskModel
from .types import (
    CognitiveAction,
    CognitiveActionKind,
    CognitiveObservation,
    CognitivePlan,
    ReasoningStrategy,
    RiskClass,
)
from .working_memory import WorkingMemory


class ActionSelector:
    def __init__(self, broker: CapabilityBroker | None = None) -> None:
        self.broker = broker or CapabilityBroker()

    def select(
        self,
        *,
        task: TaskModel,
        decision: MetaDecision,
        plan: CognitivePlan | None,
        beliefs: BeliefState,
        working_memory: WorkingMemory,
        observations: list[CognitiveObservation],
        budgets_remaining: dict[str, int],
        cancel_requested: bool = False,
    ) -> CognitiveAction:
        if cancel_requested:
            return CognitiveAction(
                kind=CognitiveActionKind.FAIL,
                action_id=str(uuid.uuid4()),
                rationale="cancellation requested",
                arguments={"status": "CANCELLED"},
            )

        if budgets_remaining.get("iterations", 1) <= 0:
            return CognitiveAction(
                kind=CognitiveActionKind.COMPLETE,
                action_id=str(uuid.uuid4()),
                rationale="iteration budget exhausted — finalize partial",
                arguments={"status": "RESOURCE_EXHAUSTED"},
            )

        # Ambiguity ask-user when high risk.
        if task.ambiguities and task.risk_class in {RiskClass.HIGH, RiskClass.CRITICAL} and not observations:
            return CognitiveAction(
                kind=CognitiveActionKind.ASK_USER,
                action_id=str(uuid.uuid4()),
                rationale="material ambiguity on high-risk task",
                arguments={"questions": list(task.ambiguities)},
                risk_class=task.risk_class,
            )

        strategy = decision.strategy
        value = decision.value_scores

        # Retrieval first when valuable and unused.
        if (
            budgets_remaining.get("retrieval_rounds", 0) > 0
            and value.get("retrieve", 0) >= 0.35
            and not any(o.kind.value == "RETRIEVAL_RESULT" for o in observations)
            and strategy
            in {
                ReasoningStrategy.RETRIEVE_THEN_ANSWER,
                ReasoningStrategy.RESEARCH_SYNTHESIS,
                ReasoningStrategy.HYPOTHESIS_TEST,
                ReasoningStrategy.CODING_REPAIR,
                ReasoningStrategy.DEBUG_LOOP,
            }
        ):
            return CognitiveAction(
                kind=CognitiveActionKind.RETRIEVE,
                action_id=str(uuid.uuid4()),
                rationale="value-of-information favors retrieval",
                arguments={"query": task.goal},
                expected_observation="perception snapshot",
            )

        # Capability search for tool-driven / when side effects expected.
        if (
            strategy in {ReasoningStrategy.TOOL_DRIVEN, ReasoningStrategy.MULTI_AGENT}
            and budgets_remaining.get("tool_calls", 0) > 0
            and not working_memory.list_by_kind("capability")
        ):
            return CognitiveAction(
                kind=CognitiveActionKind.SEARCH_CAPABILITY,
                action_id=str(uuid.uuid4()),
                rationale="shortlist capabilities without schema dump",
                arguments={"query": task.goal, "domain": task.domain},
            )

        # Invoke a shortlisted capability through ExecutionGateway (U123).
        caps = working_memory.list_by_kind("capability")
        if (
            caps
            and budgets_remaining.get("tool_calls", 0) > 0
            and not any(o.kind.value == "TOOL_RESULT" for o in observations)
            and strategy
            in {
                ReasoningStrategy.TOOL_DRIVEN,
                ReasoningStrategy.PLAN_EXECUTE_VERIFY,
                ReasoningStrategy.RETRIEVE_THEN_ANSWER,
            }
        ):
            capability_id = caps[0].content.strip().split()[0]
            return CognitiveAction(
                kind=CognitiveActionKind.INVOKE_CAPABILITY,
                action_id=str(uuid.uuid4()),
                capability_id=capability_id,
                rationale="invoke shortlisted capability via ExecutionGateway",
                arguments={"query": task.goal, "limit": 5},
                expected_observation="tool observation",
                risk_class=task.risk_class,
                requires_approval=task.risk_class in {RiskClass.HIGH, RiskClass.CRITICAL},
            )

        # Delegation when justified.
        if (
            budgets_remaining.get("agent_delegations", 0) > 0
            and value.get("delegate_agent", 0) >= 0.4
            and task.allowed_delegation
            and not any(o.kind.value == "AGENT_RESULT" for o in observations)
        ):
            target = task.allowed_delegation[0]
            return CognitiveAction(
                kind=CognitiveActionKind.DELEGATE_AGENT,
                action_id=str(uuid.uuid4()),
                rationale=f"delegation value justifies {target} specialist",
                arguments={
                    "agent_kind": target,
                    "goal": task.goal,
                    "success_criteria": list(task.success_criteria),
                    "authority_ceiling": task.risk_class.value,
                },
                risk_class=task.risk_class,
                requires_approval=task.risk_class in {RiskClass.HIGH, RiskClass.CRITICAL}
                and bool(task.side_effect_expectations),
            )

        # Hypothesis registration for scientific/debug strategies.
        if strategy in {ReasoningStrategy.HYPOTHESIS_TEST, ReasoningStrategy.DEBUG_LOOP}:
            hyps = [b for b in beliefs.items.values() if b.category.value == "HYPOTHESIS"]
            if not hyps:
                return CognitiveAction(
                    kind=CognitiveActionKind.MODEL_CALL,
                    action_id=str(uuid.uuid4()),
                    rationale="form public hypothesis (structured, not private CoT)",
                    arguments={"role": "planner", "purpose": "hypothesis"},
                    expected_observation="hypothesis proposal",
                )

        # Verify when criteria present and we have observations / low uncertainty.
        if (
            task.success_criteria
            and observations
            and beliefs.uncertainty() <= 0.45
            and strategy
            in {
                ReasoningStrategy.PLAN_EXECUTE_VERIFY,
                ReasoningStrategy.CODING_REPAIR,
                ReasoningStrategy.HIGH_RISK_VERIFY,
                ReasoningStrategy.RESEARCH_SYNTHESIS,
            }
        ):
            return CognitiveAction(
                kind=CognitiveActionKind.VERIFY,
                action_id=str(uuid.uuid4()),
                rationale="acceptance criteria ready for verification",
                arguments={"criteria": list(task.success_criteria)},
                risk_class=task.risk_class,
            )

        # Replan when plan stale.
        if plan is not None and plan.stale and budgets_remaining.get("replans", 0) > 0:
            return CognitiveAction(
                kind=CognitiveActionKind.REPLAN,
                action_id=str(uuid.uuid4()),
                rationale="plan marked stale",
                arguments={"reason": "stale_plan"},
            )

        # Default: model respond / complete for FAST.
        if strategy == ReasoningStrategy.DIRECT or decision.mode.value == "FAST":
            if observations or budgets_remaining.get("model_calls", 0) > 0:
                return CognitiveAction(
                    kind=CognitiveActionKind.RESPOND
                    if budgets_remaining.get("model_calls", 0) > 0
                    else CognitiveActionKind.COMPLETE,
                    action_id=str(uuid.uuid4()),
                    rationale="fast path response",
                    arguments={"role": "responder"},
                )

        if budgets_remaining.get("model_calls", 0) > 0:
            return CognitiveAction(
                kind=CognitiveActionKind.MODEL_CALL,
                action_id=str(uuid.uuid4()),
                rationale="continue reasoning with model via control plane",
                arguments={"role": self._role_for(strategy)},
                expected_observation="model result",
            )

        return CognitiveAction(
            kind=CognitiveActionKind.COMPLETE,
            action_id=str(uuid.uuid4()),
            rationale="no remaining model budget — complete with available state",
            arguments={"status": "PARTIAL"},
        )

    @staticmethod
    def _role_for(strategy: ReasoningStrategy) -> str:
        return {
            ReasoningStrategy.CODING_REPAIR: "coder",
            ReasoningStrategy.DEBUG_LOOP: "coder",
            ReasoningStrategy.RESEARCH_SYNTHESIS: "synthesizer",
            ReasoningStrategy.COMPARE_ALTERNATIVES: "planner",
            ReasoningStrategy.HIGH_RISK_VERIFY: "critic",
            ReasoningStrategy.HYPOTHESIS_TEST: "planner",
        }.get(strategy, "responder")
