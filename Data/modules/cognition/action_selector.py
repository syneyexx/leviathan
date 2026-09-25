"""Action selection — VoI-scored next orchestration action."""

from __future__ import annotations

import uuid
from typing import Any

from .belief_state import BeliefState
from .capability_broker import CapabilityBroker
from .capability_state import AxisState, CapabilityAxis, CapabilityState
from .meta_controller import MetaController, MetaDecision
from .task_model import TaskModel
from .tool_interleaving import interleave_boost, should_interleave_tool_after_native
from .types import (
    BeliefCategory,
    CognitiveAction,
    CognitiveActionKind,
    CognitiveObservation,
    CognitivePlan,
    ReasoningStrategy,
    RiskClass,
)
from .working_memory import WorkingMemory


class ActionSelector:
    def __init__(
        self,
        broker: CapabilityBroker | None = None,
        meta: MetaController | None = None,
    ) -> None:
        self.broker = broker or CapabilityBroker()
        self.meta = meta or MetaController()

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
        capability_state: CapabilityState | None = None,
        actions: list[CognitiveAction] | None = None,
        inference_path: str | None = None,
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

        # Ambiguity ask-user when high risk and no observations yet.
        if task.ambiguities and task.risk_class in {RiskClass.HIGH, RiskClass.CRITICAL} and not observations:
            return CognitiveAction(
                kind=CognitiveActionKind.ASK_USER,
                action_id=str(uuid.uuid4()),
                rationale="material ambiguity on high-risk task",
                arguments={"questions": list(task.ambiguities)},
                risk_class=task.risk_class,
            )

        # Native↔tool interleaving: after a native MODEL_CALL, prefer tool/capability
        # when the capability profile explicitly supports tool interleaving (R16).
        profile = getattr(decision, "capability_profile", None)
        neural = getattr(decision, "neural_budgets", None)
        native_effort = None
        if neural is not None and getattr(neural, "native_effort", None) is not None:
            native_effort = neural.native_effort.value
        path = inference_path
        if path is None and profile is not None and getattr(profile, "supports_native_reasoning", False):
            path = "native"
        interleave = should_interleave_tool_after_native(
            capability_profile=profile,
            inference_path=path,
            native_effort=native_effort,
            actions=actions,
            observations=observations,
            tool_budget_remaining=int(budgets_remaining.get("tool_calls", 0) or 0),
            task_requires_tools=bool(getattr(task, "requires_tools", False)),
            strategy=decision.strategy.value if decision.strategy else None,
        )
        if interleave:
            forced = self._interleave_tool_action(
                task=task,
                decision=decision,
                working_memory=working_memory,
                budgets_remaining=budgets_remaining,
            )
            if forced is not None and (
                capability_state is None
                or self._allowed_by_capability_state((1.0, forced), capability_state)
            ):
                return forced

        candidates = self._candidates(
            task=task,
            decision=decision,
            plan=plan,
            beliefs=beliefs,
            working_memory=working_memory,
            observations=observations,
            budgets_remaining=budgets_remaining,
        )
        boost = interleave_boost(
            capability_profile=profile,
            inference_path=path,
            native_effort=native_effort,
            actions=actions,
            observations=observations,
            tool_budget_remaining=int(budgets_remaining.get("tool_calls", 0) or 0),
            task_requires_tools=bool(getattr(task, "requires_tools", False)),
            strategy=decision.strategy.value if decision.strategy else None,
        )
        if boost > 0:
            boosted: list[tuple[float, CognitiveAction]] = []
            for score, action in candidates:
                if action.kind in {
                    CognitiveActionKind.INVOKE_CAPABILITY,
                    CognitiveActionKind.SEARCH_CAPABILITY,
                }:
                    boosted.append((score + boost, action))
                else:
                    boosted.append((score, action))
            candidates = boosted
        if capability_state is not None:
            candidates = [
                c for c in candidates if self._allowed_by_capability_state(c, capability_state)
            ]
        if not candidates:
            return CognitiveAction(
                kind=CognitiveActionKind.COMPLETE,
                action_id=str(uuid.uuid4()),
                rationale="no viable actions — complete with available state",
                arguments={"status": "PARTIAL"},
            )

        # Prefer plan-ready steps when plan is not stale.
        if plan is not None and not plan.stale:
            ready = self._next_ready_step(plan)
            if ready is not None:
                mapped = self._action_for_step(ready, task, decision, budgets_remaining, working_memory)
                if mapped is not None and (
                    capability_state is None
                    or self._allowed_by_capability_state((0.0, mapped), capability_state)
                ):
                    return mapped

        candidates.sort(key=lambda c: c[0], reverse=True)
        return candidates[0][1]

    def _interleave_tool_action(
        self,
        *,
        task: TaskModel,
        decision: MetaDecision,
        working_memory: WorkingMemory,
        budgets_remaining: dict[str, int],
    ) -> CognitiveAction | None:
        """Build the preferred tool/capability action for an interleave slot."""
        caps = working_memory.list_by_kind("capability")
        if caps and budgets_remaining.get("tool_calls", 0) > 0:
            capability_id = caps[0].content.strip().split()[0]
            return CognitiveAction(
                kind=CognitiveActionKind.INVOKE_CAPABILITY,
                action_id=str(uuid.uuid4()),
                capability_id=capability_id,
                rationale="interleave tool after native reasoning",
                arguments={"query": task.goal, "limit": 5, "tool_interleave": True},
                expected_observation="tool observation",
                risk_class=task.risk_class,
                requires_approval=task.risk_class in {RiskClass.HIGH, RiskClass.CRITICAL},
            )
        if (
            decision.strategy
            in {
                ReasoningStrategy.TOOL_DRIVEN,
                ReasoningStrategy.MULTI_AGENT,
                ReasoningStrategy.PLAN_EXECUTE_VERIFY,
            }
            or getattr(task, "requires_tools", False)
        ) and budgets_remaining.get("tool_calls", 0) > 0:
            return CognitiveAction(
                kind=CognitiveActionKind.SEARCH_CAPABILITY,
                action_id=str(uuid.uuid4()),
                rationale="interleave capability search after native reasoning",
                arguments={
                    "query": task.goal,
                    "domain": task.domain,
                    "tool_interleave": True,
                },
            )
        return None

    @staticmethod
    def _allowed_by_capability_state(
        scored: tuple[float, CognitiveAction],
        capability_state: CapabilityState,
    ) -> bool:
        action = scored[1]
        kind = action.kind
        if kind in {CognitiveActionKind.MODEL_CALL, CognitiveActionKind.RESPOND}:
            return not capability_state.blocks(CapabilityAxis.GENERATE)
        if kind == CognitiveActionKind.INVOKE_CAPABILITY:
            if capability_state.blocks(CapabilityAxis.EXECUTE):
                # REQUIRES_APPROVAL is not blocks() — still selectable (runtime gates).
                if capability_state.axis(CapabilityAxis.EXECUTE) == AxisState.REQUIRES_APPROVAL:
                    return True
                return False
            return True
        if kind == CognitiveActionKind.DELEGATE_AGENT:
            if capability_state.blocks(CapabilityAxis.DELEGATE):
                if capability_state.axis(CapabilityAxis.DELEGATE) == AxisState.REQUIRES_APPROVAL:
                    return True
                return False
            if bool(action.arguments.get("allow_web")) and capability_state.blocks(
                CapabilityAxis.NETWORK
            ):
                return False
            return True
        if kind == CognitiveActionKind.RETRIEVE:
            if bool(action.arguments.get("allow_web")) and capability_state.blocks(
                CapabilityAxis.NETWORK
            ):
                return False
            return True
        return True

    def _candidates(
        self,
        *,
        task: TaskModel,
        decision: MetaDecision,
        plan: CognitivePlan | None,
        beliefs: BeliefState,
        working_memory: WorkingMemory,
        observations: list[CognitiveObservation],
        budgets_remaining: dict[str, int],
    ) -> list[tuple[float, CognitiveAction]]:
        strategy = decision.strategy
        value = decision.value_scores
        out: list[tuple[float, CognitiveAction]] = []

        info_needs = [
            b.next_information_needed
            for b in beliefs.items.values()
            if b.next_information_needed
        ]
        open_hyps = [
            b for b in beliefs.items.values() if b.category == BeliefCategory.HYPOTHESIS
        ]

        # RETRIEVE — only when VoI warrants it (not merely because budget remains).
        retrieval_done = any(o.kind.value == "RETRIEVAL_RESULT" for o in observations)
        retrieve_score = float(value.get("retrieve", 0))
        if info_needs:
            retrieve_score = max(retrieve_score, 0.55)
        if (
            budgets_remaining.get("retrieval_rounds", 0) > 0
            and retrieve_score >= 0.35
            and (not retrieval_done or retrieve_score >= 0.65)
        ):
            query = info_needs[0] if info_needs else task.goal
            score = self.meta.estimate_value_of_action(
                expected_gain=retrieve_score,
                expected_risk_reduction=0.1,
                cost=0.2,
                latency_penalty=0.05,
                duplication_penalty=0.2 if retrieval_done else 0.0,
            )
            out.append(
                (
                    score,
                    CognitiveAction(
                        kind=CognitiveActionKind.RETRIEVE,
                        action_id=str(uuid.uuid4()),
                        rationale="value-of-information favors retrieval",
                        arguments={"query": query},
                        expected_observation="perception snapshot",
                    ),
                )
            )

        # Capability search
        if (
            strategy in {ReasoningStrategy.TOOL_DRIVEN, ReasoningStrategy.MULTI_AGENT}
            or getattr(task, "requires_tools", False)
        ) and budgets_remaining.get("tool_calls", 0) > 0 and not working_memory.list_by_kind("capability"):
            score = self.meta.estimate_value_of_action(
                expected_gain=0.55,
                expected_completion_progress=0.1,
                cost=0.15,
            )
            out.append(
                (
                    score,
                    CognitiveAction(
                        kind=CognitiveActionKind.SEARCH_CAPABILITY,
                        action_id=str(uuid.uuid4()),
                        rationale="shortlist capabilities without schema dump",
                        arguments={"query": task.goal, "domain": task.domain},
                    ),
                )
            )

        # Invoke shortlisted capability
        caps = working_memory.list_by_kind("capability")
        tool_done = any(o.kind.value == "TOOL_RESULT" for o in observations)
        if (
            caps
            and budgets_remaining.get("tool_calls", 0) > 0
            and not tool_done
            and strategy
            in {
                ReasoningStrategy.TOOL_DRIVEN,
                ReasoningStrategy.PLAN_EXECUTE_VERIFY,
                ReasoningStrategy.RETRIEVE_THEN_ANSWER,
            }
        ):
            capability_id = caps[0].content.strip().split()[0]
            score = self.meta.estimate_value_of_action(
                expected_gain=0.6,
                expected_completion_progress=0.2,
                cost=0.25,
                failure_risk=0.1,
            )
            out.append(
                (
                    score,
                    CognitiveAction(
                        kind=CognitiveActionKind.INVOKE_CAPABILITY,
                        action_id=str(uuid.uuid4()),
                        capability_id=capability_id,
                        rationale="invoke shortlisted capability via ExecutionGateway",
                        arguments={"query": task.goal, "limit": 5},
                        expected_observation="tool observation",
                        risk_class=task.risk_class,
                        requires_approval=task.risk_class in {RiskClass.HIGH, RiskClass.CRITICAL},
                    ),
                )
            )

        # Delegation — research/coding specialists when justified
        agent_done = any(o.kind.value == "AGENT_RESULT" for o in observations)
        delegate_score = float(value.get("delegate_agent", 0))
        if (
            budgets_remaining.get("agent_delegations", 0) > 0
            and delegate_score >= 0.4
            and task.allowed_delegation
            and not agent_done
        ):
            target = task.allowed_delegation[0]
            if task.domain == "coding" and "coding" in task.allowed_delegation:
                target = "coding"
            elif (
                task.domain == "research" or getattr(task, "requires_research", False)
            ) and "research" in task.allowed_delegation:
                target = "research"
            score = self.meta.estimate_value_of_action(
                expected_gain=delegate_score,
                expected_completion_progress=0.3 if target == "research" else 0.2,
                cost=0.35,
                latency_penalty=0.2 if target == "research" else 0.15,
            )
            out.append(
                (
                    score,
                    CognitiveAction(
                        kind=CognitiveActionKind.DELEGATE_AGENT,
                        action_id=str(uuid.uuid4()),
                        rationale=f"delegation value justifies {target} specialist",
                        arguments={
                            "agent_kind": target,
                            "goal": task.goal,
                            "success_criteria": list(task.success_criteria),
                            "authority_ceiling": task.risk_class.value,
                            "research_mode": getattr(task, "research_mode", "none"),
                            "allow_web": bool(getattr(task, "requires_current_information", False)),
                            "hard_constraints": list(getattr(task, "hard_constraints", None) or task.constraints),
                        },
                        risk_class=task.risk_class,
                        requires_approval=task.risk_class in {RiskClass.HIGH, RiskClass.CRITICAL}
                        and bool(task.side_effect_expectations),
                    ),
                )
            )

        # Hypothesis formation
        if strategy in {ReasoningStrategy.HYPOTHESIS_TEST, ReasoningStrategy.DEBUG_LOOP} and not open_hyps:
            if budgets_remaining.get("model_calls", 0) > 0:
                score = self.meta.estimate_value_of_action(
                    expected_gain=0.5,
                    expected_risk_reduction=0.15,
                    cost=0.2,
                )
                out.append(
                    (
                        score,
                        CognitiveAction(
                            kind=CognitiveActionKind.MODEL_CALL,
                            action_id=str(uuid.uuid4()),
                            rationale="form public hypothesis (structured, not private CoT)",
                            arguments={"role": "planner", "purpose": "hypothesis"},
                            expected_observation="hypothesis proposal",
                        ),
                    )
                )

        # VERIFY when justified
        verify_score = float(value.get("verify", 0.3))
        if (
            task.success_criteria
            and observations
            and (
                beliefs.uncertainty() <= 0.45
                or task.risk_class in {RiskClass.HIGH, RiskClass.CRITICAL}
                or strategy
                in {
                    ReasoningStrategy.PLAN_EXECUTE_VERIFY,
                    ReasoningStrategy.CODING_REPAIR,
                    ReasoningStrategy.HIGH_RISK_VERIFY,
                    ReasoningStrategy.RESEARCH_SYNTHESIS,
                }
            )
            and not any(o.kind.value == "VERIFICATION_RESULT" for o in observations)
        ):
            score = self.meta.estimate_value_of_action(
                expected_gain=verify_score,
                expected_risk_reduction=0.3,
                expected_completion_progress=0.25,
                cost=0.15,
            )
            out.append(
                (
                    score,
                    CognitiveAction(
                        kind=CognitiveActionKind.VERIFY,
                        action_id=str(uuid.uuid4()),
                        rationale="acceptance criteria ready for verification",
                        arguments={"criteria": list(task.success_criteria)},
                        risk_class=task.risk_class,
                    ),
                )
            )

        # Replan when stale or high VoI
        if plan is not None and plan.stale and budgets_remaining.get("replans", 0) > 0:
            score = max(float(value.get("replan", 0.4)), 0.5)
            out.append(
                (
                    score,
                    CognitiveAction(
                        kind=CognitiveActionKind.REPLAN,
                        action_id=str(uuid.uuid4()),
                        rationale="plan marked stale",
                        arguments={"reason": "stale_plan", "level": 3},
                    ),
                )
            )

        # FAST / DIRECT respond
        if strategy == ReasoningStrategy.DIRECT or decision.mode.value == "FAST":
            if budgets_remaining.get("model_calls", 0) > 0:
                out.append(
                    (
                        0.9 if task.task_type == "simple_chat" else 0.45,
                        CognitiveAction(
                            kind=CognitiveActionKind.RESPOND,
                            action_id=str(uuid.uuid4()),
                            rationale="fast path response",
                            arguments={"role": "responder"},
                        ),
                    )
                )
            else:
                out.append(
                    (
                        0.3,
                        CognitiveAction(
                            kind=CognitiveActionKind.COMPLETE,
                            action_id=str(uuid.uuid4()),
                            rationale="fast path complete without model budget",
                            arguments={"status": "PARTIAL"},
                        ),
                    )
                )

        # Default model continue
        if budgets_remaining.get("model_calls", 0) > 0 and strategy != ReasoningStrategy.DIRECT:
            out.append(
                (
                    0.35,
                    CognitiveAction(
                        kind=CognitiveActionKind.MODEL_CALL,
                        action_id=str(uuid.uuid4()),
                        rationale="continue reasoning with model via control plane",
                        arguments={"role": self._role_for(strategy)},
                        expected_observation="model result",
                    ),
                )
            )

        # Complete fallback
        if observations and beliefs.uncertainty() <= 0.35:
            out.append(
                (
                    0.4,
                    CognitiveAction(
                        kind=CognitiveActionKind.COMPLETE,
                        action_id=str(uuid.uuid4()),
                        rationale="uncertainty low — complete with available state",
                        arguments={"status": "COMPLETED"},
                    ),
                )
            )

        return out

    def _next_ready_step(self, plan: CognitivePlan) -> Any | None:
        done = {s.step_id for s in plan.steps if s.status in {"DONE", "COMPLETED", "SKIPPED"}}
        for step in plan.steps:
            if step.status not in {"PENDING", "READY", ""}:
                continue
            deps = set(step.dependencies or ())
            if deps <= done:
                return step
        return None

    def _action_for_step(
        self,
        step: Any,
        task: TaskModel,
        decision: MetaDecision,
        budgets_remaining: dict[str, int],
        working_memory: WorkingMemory,
    ) -> CognitiveAction | None:
        objective = (step.objective or "").lower()
        if "retriev" in objective or "search" in objective or "knowledge" in objective:
            if budgets_remaining.get("retrieval_rounds", 0) > 0:
                return CognitiveAction(
                    kind=CognitiveActionKind.RETRIEVE,
                    action_id=str(uuid.uuid4()),
                    rationale=f"plan step: {step.objective}",
                    arguments={"query": task.goal, "step_id": step.step_id},
                )
        if "delegat" in objective or "research" in objective or "specialist" in objective:
            if budgets_remaining.get("agent_delegations", 0) > 0 and task.allowed_delegation:
                target = "research" if "research" in task.allowed_delegation else task.allowed_delegation[0]
                return CognitiveAction(
                    kind=CognitiveActionKind.DELEGATE_AGENT,
                    action_id=str(uuid.uuid4()),
                    rationale=f"plan step: {step.objective}",
                    arguments={
                        "agent_kind": target,
                        "goal": task.goal,
                        "step_id": step.step_id,
                        "allow_web": bool(getattr(task, "requires_current_information", False)),
                        "research_mode": getattr(task, "research_mode", "none"),
                        "hard_constraints": list(getattr(task, "hard_constraints", None) or task.constraints),
                    },
                )
        if "verif" in objective:
            return CognitiveAction(
                kind=CognitiveActionKind.VERIFY,
                action_id=str(uuid.uuid4()),
                rationale=f"plan step: {step.objective}",
                arguments={"criteria": list(task.success_criteria), "step_id": step.step_id},
            )
        if "tool" in objective or "capability" in objective:
            caps = working_memory.list_by_kind("capability")
            if caps and budgets_remaining.get("tool_calls", 0) > 0:
                return CognitiveAction(
                    kind=CognitiveActionKind.INVOKE_CAPABILITY,
                    action_id=str(uuid.uuid4()),
                    capability_id=caps[0].content.strip().split()[0],
                    rationale=f"plan step: {step.objective}",
                    arguments={"step_id": step.step_id},
                )
        if budgets_remaining.get("model_calls", 0) > 0:
            return CognitiveAction(
                kind=CognitiveActionKind.MODEL_CALL,
                action_id=str(uuid.uuid4()),
                rationale=f"plan step: {step.objective}",
                arguments={"role": self._role_for(decision.strategy), "step_id": step.step_id},
            )
        return None

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
