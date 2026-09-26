"""Reconstruct live CognitiveRunState from durable CognitionStore rows (U122)."""

from __future__ import annotations

from typing import Any

from .belief_state import BeliefItem, BeliefState
from .meta_controller import MetaDecision
from .task_model import AcceptanceCriterion, TaskModel, acceptance_criterion_from_mapping, coerce_acceptance_criteria
from .types import (
    BeliefCategory,
    BeliefStatus,
    BudgetUsage,
    CognitiveAction,
    CognitiveActionKind,
    CognitiveBudgets,
    CognitiveObservation,
    CognitiveObservationKind,
    CognitivePlan,
    CognitiveRunStatus,
    EpistemicType,
    PlanStep,
    ReasoningMode,
    ReasoningStrategy,
    RiskClass,
)
from .working_memory import WorkingMemory, WorkingMemoryItem


def task_from_dict(data: dict[str, Any] | None, *, run_id: str | None = None) -> TaskModel:
    raw = dict(data or {})
    risk = raw.get("risk_class") or RiskClass.LOW.value
    try:
        risk_class = RiskClass(risk)
    except ValueError:
        risk_class = RiskClass.LOW
    preferences = list(raw.get("preferences") or [])
    legacy_criteria = list(raw.get("success_criteria") or [])
    typed_raw = raw.get("acceptance_criteria")
    if typed_raw:
        acceptance = coerce_acceptance_criteria(typed_raw)
    else:
        acceptance = coerce_acceptance_criteria(None, legacy_strings=legacy_criteria)
    return TaskModel(
        task_id=str(raw.get("task_id") or "unknown"),
        run_id=run_id or raw.get("run_id"),
        raw_request=str(raw.get("raw_request") or raw.get("goal") or ""),
        goal=str(raw.get("goal") or ""),
        domain=str(raw.get("domain") or "general"),
        task_type=str(raw.get("task_type") or "general"),
        requested_outputs=list(raw.get("requested_outputs") or []),
        constraints=list(raw.get("constraints") or []),
        success_criteria=legacy_criteria,
        acceptance_criteria=acceptance,
        risk_class=risk_class,
        side_effect_expectations=list(raw.get("side_effect_expectations") or []),
        required_evidence=list(raw.get("required_evidence") or []),
        known_facts=list(raw.get("known_facts") or []),
        unknowns=list(raw.get("unknowns") or []),
        ambiguities=list(raw.get("ambiguities") or []),
        dependencies=list(raw.get("dependencies") or []),
        requires_current_information=bool(raw.get("requires_current_information")),
        requires_external_information=bool(raw.get("requires_external_information")),
        requires_personal_context=bool(raw.get("requires_personal_context")),
        requires_files=bool(raw.get("requires_files")),
        requires_tools=bool(raw.get("requires_tools")),
        requires_actions=bool(raw.get("requires_actions")),
        requires_research=bool(raw.get("requires_research")),
        requires_coding=bool(raw.get("requires_coding")),
        needs_brain_retrieval=bool(raw.get("needs_brain_retrieval")),
        needs_memory=bool(raw.get("needs_memory")),
        needs_browser=bool(raw.get("needs_browser")),
        needs_code_execution=bool(raw.get("needs_code_execution")),
        needs_calculation=bool(raw.get("needs_calculation")),
        needs_specialists=bool(raw.get("needs_specialists")),
        needs_verification=bool(raw.get("needs_verification")),
        requires_side_effect=bool(raw.get("requires_side_effect")),
        freshness_requirement=str(raw.get("freshness_requirement") or "none"),
        complexity=str(raw.get("complexity") or "low"),
        expected_answer_type=str(raw.get("expected_answer_type") or "prose"),
        verification_mode=str(raw.get("verification_mode") or "NONE"),
        execution_class=str(raw.get("execution_class") or "DIRECT"),
        candidate_specialists=list(raw.get("candidate_specialists") or []),
        time_sensitivity=str(raw.get("time_sensitivity") or "normal"),
        resource_expectation=str(raw.get("resource_expectation") or "light"),
        privacy_class=str(raw.get("privacy_class") or "standard"),
        initial_uncertainty=float(raw.get("initial_uncertainty") or 0.5),
        preferred_execution_mode=str(raw.get("preferred_execution_mode") or "in_process"),
        allowed_delegation=list(raw.get("allowed_delegation") or []),
        research_mode=str(raw.get("research_mode") or "none"),
        metadata=dict(raw.get("metadata") or {}),
        legacy_plan=None,
    )


def plan_from_dict(data: dict[str, Any] | None) -> CognitivePlan | None:
    if not data:
        return None
    try:
        strategy = ReasoningStrategy(str(data.get("strategy") or ReasoningStrategy.DIRECT.value))
    except ValueError:
        strategy = ReasoningStrategy.DIRECT
    steps: list[PlanStep] = []
    for raw in data.get("steps") or []:
        try:
            risk = RiskClass(str(raw.get("risk_class") or RiskClass.LOW.value))
        except ValueError:
            risk = RiskClass.LOW
        steps.append(
            PlanStep(
                step_id=str(raw.get("step_id") or "s?"),
                objective=str(raw.get("objective") or ""),
                dependencies=tuple(raw.get("dependencies") or ()),
                expected_observation=raw.get("expected_observation"),
                acceptance_condition=raw.get("acceptance_condition"),
                likely_capabilities=tuple(raw.get("likely_capabilities") or ()),
                risk_class=risk,
                status=str(raw.get("status") or "PENDING"),
                resource_estimate=dict(raw.get("resource_estimate") or {}),
                completion_criteria=tuple(raw.get("completion_criteria") or ()),
            )
        )
    return CognitivePlan(
        plan_id=str(data.get("plan_id") or "plan"),
        strategy=strategy,
        steps=steps,
        assumptions=list(data.get("assumptions") or []),
        stale=bool(data.get("stale")),
        revision=int(data.get("revision") or 0),
    )


def beliefs_from_dict(data: dict[str, Any] | None) -> BeliefState:
    state = BeliefState()
    if not data:
        return state
    for raw in data.get("items") or []:
        try:
            category = BeliefCategory(str(raw.get("category") or BeliefCategory.HYPOTHESIS.value))
        except ValueError:
            category = BeliefCategory.HYPOTHESIS
        try:
            status = BeliefStatus(str(raw.get("status") or BeliefStatus.UNVERIFIED.value))
        except ValueError:
            status = BeliefStatus.UNVERIFIED
        try:
            source = EpistemicType(str(raw.get("source_type") or EpistemicType.HYPOTHESIS.value))
        except ValueError:
            source = EpistemicType.HYPOTHESIS
        item = BeliefItem(
            belief_id=str(raw.get("belief_id") or ""),
            proposition=str(raw.get("proposition") or ""),
            category=category,
            confidence=float(raw.get("confidence") or 0.5),
            support_refs=list(raw.get("support_refs") or []),
            contradiction_refs=list(raw.get("contradiction_refs") or []),
            source_type=source,
            status=status,
            created_at=str(raw.get("created_at") or ""),
            updated_at=str(raw.get("updated_at") or ""),
            next_information_needed=raw.get("next_information_needed"),
            metadata=dict(raw.get("metadata") or {}),
        )
        if item.belief_id:
            state.items[item.belief_id] = item
    for pair in data.get("contradiction_pairs") or []:
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            state.contradiction_pairs.append((str(pair[0]), str(pair[1])))
    return state


def working_memory_from_dict(data: dict[str, Any] | None) -> WorkingMemory:
    capacity = int((data or {}).get("capacity") or 32)
    wm = WorkingMemory(capacity=max(4, capacity))
    for raw in (data or {}).get("items") or []:
        try:
            source = EpistemicType(str(raw.get("source_type") or EpistemicType.SYSTEM_STATE.value))
        except ValueError:
            source = EpistemicType.SYSTEM_STATE
        item_id = str(raw.get("item_id") or "")
        kind = str(raw.get("kind") or "fact")
        wm.upsert(
            kind,
            str(raw.get("content") or ""),
            priority=float(raw.get("priority") or 0.5),
            source_type=source,
            provenance=dict(raw.get("provenance") or {}),
            verified=bool(raw.get("verified")),
            item_id=item_id or None,
        )
    return wm


def budgets_from_dict(data: dict[str, Any] | None) -> CognitiveBudgets:
    raw = data or {}
    return CognitiveBudgets(
        max_wall_time_seconds=float(raw.get("max_wall_time_seconds") or 120.0),
        max_model_calls=int(raw.get("max_model_calls") or 4),
        max_model_tokens=int(raw.get("max_model_tokens") or 8000),
        max_tool_calls=int(raw.get("max_tool_calls") or 8),
        max_agent_delegations=int(raw.get("max_agent_delegations") or 2),
        max_replans=int(raw.get("max_replans") or 3),
        max_retries=int(raw.get("max_retries") or 3),
        max_retrieval_rounds=int(raw.get("max_retrieval_rounds") or 3),
        max_parallel_workers=int(raw.get("max_parallel_workers") or 2),
        max_context_tokens=int(raw.get("max_context_tokens") or 6000),
        max_critic_passes=int(raw.get("max_critic_passes") or 2),
        max_iterations=int(raw.get("max_iterations") or 8),
    )


def usage_from_dict(data: dict[str, Any] | None) -> BudgetUsage:
    raw = data or {}
    return BudgetUsage(
        model_calls=int(raw.get("model_calls") or 0),
        model_tokens=int(raw.get("model_tokens") or 0),
        input_tokens=int(raw.get("input_tokens") or 0),
        output_tokens=int(raw.get("output_tokens") or 0),
        tool_calls=int(raw.get("tool_calls") or 0),
        agent_delegations=int(raw.get("agent_delegations") or 0),
        replans=int(raw.get("replans") or 0),
        retries=int(raw.get("retries") or 0),
        retrieval_rounds=int(raw.get("retrieval_rounds") or 0),
        critic_passes=int(raw.get("critic_passes") or 0),
        iterations=int(raw.get("iterations") or 0),
        started_monotonic=float(raw.get("started_monotonic") or 0.0),
        token_usage_source=str(raw.get("token_usage_source") or "unavailable"),
    )


def decision_from_parts(
    *,
    mode: str | None,
    strategy: str | None,
    budgets: dict[str, Any] | None,
    decision_blob: dict[str, Any] | None = None,
) -> MetaDecision | None:
    blob = decision_blob or {}
    mode_s = blob.get("mode") or mode
    strategy_s = blob.get("strategy") or strategy
    if not mode_s or not strategy_s:
        return None
    try:
        mode_e = ReasoningMode(str(mode_s))
    except ValueError:
        mode_e = ReasoningMode.STANDARD
    try:
        strategy_e = ReasoningStrategy(str(strategy_s))
    except ValueError:
        strategy_e = ReasoningStrategy.DIRECT
    return MetaDecision(
        mode=mode_e,
        strategy=strategy_e,
        budgets=budgets_from_dict(blob.get("budgets") or budgets),
        value_scores=dict(blob.get("value_scores") or {}),
        notes=tuple(blob.get("notes") or ()),
    )


def observation_from_dict(data: dict[str, Any]) -> CognitiveObservation:
    try:
        kind = CognitiveObservationKind(str(data.get("kind") or CognitiveObservationKind.SYSTEM_STATE.value))
    except ValueError:
        kind = CognitiveObservationKind.SYSTEM_STATE
    try:
        source = EpistemicType(str(data.get("source_type") or EpistemicType.SYSTEM_STATE.value))
    except ValueError:
        source = EpistemicType.SYSTEM_STATE
    return CognitiveObservation(
        kind=kind,
        observation_id=str(data.get("observation_id") or ""),
        summary=str(data.get("summary") or ""),
        source_type=source,
        payload=dict(data.get("payload") or {}),
        evidence_refs=tuple(data.get("evidence_refs") or ()),
        artifact_refs=tuple(data.get("artifact_refs") or ()),
        success=data.get("success"),
        error=data.get("error"),
    )


def action_from_dict(data: dict[str, Any]) -> CognitiveAction:
    try:
        kind = CognitiveActionKind(str(data.get("kind") or CognitiveActionKind.WAIT.value))
    except ValueError:
        kind = CognitiveActionKind.WAIT
    try:
        risk = RiskClass(str(data.get("risk_class") or RiskClass.LOW.value))
    except ValueError:
        risk = RiskClass.LOW
    return CognitiveAction(
        kind=kind,
        action_id=str(data.get("action_id") or ""),
        arguments=dict(data.get("arguments") or {}),
        capability_id=data.get("capability_id"),
        rationale=data.get("rationale"),
        expected_observation=data.get("expected_observation"),
        risk_class=risk,
        requires_approval=bool(data.get("requires_approval")),
    )


def status_from_value(value: str | None) -> CognitiveRunStatus:
    try:
        return CognitiveRunStatus(str(value or CognitiveRunStatus.CREATED.value))
    except ValueError:
        return CognitiveRunStatus.FAILED
