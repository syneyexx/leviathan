"""Chat-turn activity instrumentation helpers.

Emits structured ActivityEvents from real chat/run transitions. Telemetry only —
never an execution authority. Keeps main.py thinner while preserving one Run owner.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .activity import (
    ActivityCategory,
    ActivityEmitter,
    ActivityLifecycle,
    ActivityPhase,
    ActorType,
    ConfigTriple,
    ProgressMeasurement,
    activity_from_cognition_operational_event,
    activity_from_team_event,
    legacy_step_title,
)


def create_chat_activity_emitter(
    *,
    run_id: str,
    trace_id: str | None = None,
    run_store: Any | None = None,
    observability: Any | None = None,
) -> ActivityEmitter:
    return ActivityEmitter(
        operation_id=run_id,
        trace_id=trace_id or run_id,
        run_store=run_store,
        observability=observability,
        persist=True,
        emit_to_hub=True,
        actor_default=ActorType.LEVIATHAN,
        actor_id_default="leviathan",
    )


def emit_request_received(emitter: ActivityEmitter) -> None:
    emitter.emit(
        category=ActivityCategory.REQUEST,
        phase=ActivityPhase.REQUEST_RECEIVED,
        lifecycle=ActivityLifecycle.COMPLETED,
        title="Request received",
        summary="The user request has been accepted for execution.",
        stable_id=f"{emitter.operation_id}:request_received",
        progress=ProgressMeasurement.indeterminate(basis="request_accepted"),
    )


def emit_request_understood(
    emitter: ActivityEmitter,
    *,
    intent: str,
    complexity: str,
    retrieval_reason: str = "",
) -> None:
    emitter.emit(
        category=ActivityCategory.REQUEST,
        phase=ActivityPhase.REQUEST_UNDERSTOOD,
        lifecycle=ActivityLifecycle.COMPLETED,
        title="Request interpreted",
        summary=(
            f"Intent classified as {intent} with planner complexity {complexity}."
            + (f" Retrieval gate: {retrieval_reason}." if retrieval_reason else "")
        ),
        stable_id=f"{emitter.operation_id}:request_understood",
        payload={"intent": intent, "complexity": complexity, "retrieval_reason": retrieval_reason},
        progress=ProgressMeasurement.indeterminate(basis="intent_classification"),
    )


def emit_plan_created(
    emitter: ActivityEmitter,
    *,
    steps: Sequence[str],
    reasoning_mode: Mapping[str, Any] | None = None,
) -> None:
    mode = dict(reasoning_mode or {})
    step_titles = [legacy_step_title(s) for s in steps if str(s).strip()]
    emitter.emit(
        category=ActivityCategory.PLANNING,
        phase=ActivityPhase.PLANNING,
        lifecycle=ActivityLifecycle.COMPLETED,
        title="Execution plan created",
        summary=(
            f"Planned {len(step_titles)} step(s)."
            if step_titles
            else "Execution plan established."
        ),
        stable_id=f"{emitter.operation_id}:plan_created",
        result_count=len(step_titles) if step_titles else None,
        config=ConfigTriple(
            requested={"reasoning_mode": mode.get("requested")},
            effective={"reasoning_mode": mode.get("effective"), "source": mode.get("source")},
            measured={"reasoning_mode": mode.get("effective")},
        )
        if mode
        else None,
        payload={"planned_steps": list(steps), "planned_step_titles": step_titles},
        progress=ProgressMeasurement.indeterminate(basis="plan_established"),
    )
    # Mark planned leaf steps as queued (compatibility with legacy step ids).
    for step in steps:
        sid = str(step).strip()
        if not sid:
            continue
        phase = _phase_for_step(sid)
        emitter.emit(
            category=_category_for_phase(phase),
            phase=phase,
            lifecycle=ActivityLifecycle.QUEUED,
            title=legacy_step_title(sid),
            summary="Planned step — awaiting runtime confirmation.",
            stable_id=f"{emitter.operation_id}:step:{sid}",
            parent_event_id=f"{emitter.operation_id}:plan_created",
            payload={"legacy_step_id": sid, "planned": True},
            progress=ProgressMeasurement.indeterminate(basis="plan_step"),
        )


def emit_knowledge_retrieval_started(emitter: ActivityEmitter, *, mode: str = "knowledge") -> None:
    emitter.emit(
        category=ActivityCategory.KNOWLEDGE,
        phase=ActivityPhase.KNOWLEDGE_RETRIEVAL,
        lifecycle=ActivityLifecycle.RUNNING,
        title="Knowledge retrieval",
        summary="Retrieving relevant material from Leviathan's knowledge system.",
        stable_id=f"{emitter.operation_id}:knowledge_retrieval",
        payload={"retrieval_mode": mode},
        progress=ProgressMeasurement.indeterminate(basis="retrieval_running"),
    )
    emitter.emit(
        category=ActivityCategory.KNOWLEDGE,
        phase=ActivityPhase.KNOWLEDGE_RETRIEVAL,
        lifecycle=ActivityLifecycle.RUNNING,
        title=legacy_step_title("retrieve_relevant_knowledge"),
        stable_id=f"{emitter.operation_id}:step:retrieve_relevant_knowledge",
        parent_event_id=f"{emitter.operation_id}:plan_created",
        progress=ProgressMeasurement.indeterminate(basis="retrieval_running"),
    )


def emit_knowledge_retrieval_completed(
    emitter: ActivityEmitter,
    *,
    knowledge_count: int | None = None,
    memory_count: int | None = None,
    atlas_count: int | None = None,
    source: str = "brain",
) -> None:
    count = knowledge_count
    summary = None
    if knowledge_count is not None:
        summary = f"{knowledge_count} relevant source(s) identified."
    emitter.emit(
        category=ActivityCategory.KNOWLEDGE,
        phase=ActivityPhase.KNOWLEDGE_RETRIEVAL,
        lifecycle=ActivityLifecycle.COMPLETED,
        title="Knowledge retrieved",
        summary=summary,
        stable_id=f"{emitter.operation_id}:knowledge_retrieval",
        result_count=count,
        payload={
            "knowledge_count": knowledge_count,
            "memory_count": memory_count,
            "atlas_count": atlas_count,
            "source": source,
        },
        progress=(
            ProgressMeasurement.measured(
                numerator=float(knowledge_count),
                denominator=float(knowledge_count),
                unit="sources",
                basis="retrieval_hit_count",
            )
            if knowledge_count is not None and knowledge_count >= 0
            else ProgressMeasurement.indeterminate(basis="retrieval_completed")
        ),
    )
    emitter.emit(
        category=ActivityCategory.KNOWLEDGE,
        phase=ActivityPhase.KNOWLEDGE_RETRIEVAL,
        lifecycle=ActivityLifecycle.COMPLETED,
        title=legacy_step_title("retrieve_relevant_knowledge"),
        summary=summary,
        stable_id=f"{emitter.operation_id}:step:retrieve_relevant_knowledge",
        parent_event_id=f"{emitter.operation_id}:plan_created",
        result_count=count,
    )
    # Mark understand_request completed if still queued.
    emitter.emit(
        category=ActivityCategory.REQUEST,
        phase=ActivityPhase.REQUEST_UNDERSTOOD,
        lifecycle=ActivityLifecycle.COMPLETED,
        title=legacy_step_title("understand_request"),
        stable_id=f"{emitter.operation_id}:step:understand_request",
        parent_event_id=f"{emitter.operation_id}:plan_created",
    )


def emit_memory_retrieval(
    emitter: ActivityEmitter,
    *,
    lifecycle: ActivityLifecycle,
    count: int | None = None,
) -> None:
    emitter.emit(
        category=ActivityCategory.MEMORY,
        phase=ActivityPhase.MEMORY_RETRIEVAL,
        lifecycle=lifecycle,
        title="Memory retrieval" if lifecycle != ActivityLifecycle.COMPLETED else "Memory retrieved",
        summary=(f"{count} memory hit(s)." if count is not None and lifecycle == ActivityLifecycle.COMPLETED else None),
        stable_id=f"{emitter.operation_id}:memory_retrieval",
        result_count=count if lifecycle == ActivityLifecycle.COMPLETED else None,
        progress=ProgressMeasurement.indeterminate(basis="memory_retrieval"),
    )


def emit_model_invocation(
    emitter: ActivityEmitter,
    *,
    lifecycle: ActivityLifecycle,
    requested_model: str | None = None,
    effective_model: str | None = None,
    fallback: bool | None = None,
    error: Mapping[str, Any] | None = None,
) -> None:
    title = {
        ActivityLifecycle.STARTING: "Model invocation starting",
        ActivityLifecycle.RUNNING: "Model invocation",
        ActivityLifecycle.COMPLETED: "Model invocation completed",
        ActivityLifecycle.FAILED: "Model invocation failed",
        ActivityLifecycle.CANCELLED: "Model invocation cancelled",
        ActivityLifecycle.DEGRADED: "Model invocation degraded",
    }.get(lifecycle, "Model invocation")
    emitter.emit(
        category=ActivityCategory.MODEL,
        phase=ActivityPhase.MODEL_INVOCATION,
        lifecycle=lifecycle,
        title=title,
        stable_id=f"{emitter.operation_id}:model",
        model_ref=effective_model or requested_model,
        config=ConfigTriple(
            requested={"model": requested_model},
            effective={"model": effective_model, "fallback": fallback},
            measured={"model": effective_model},
        ),
        error=error,
        progress=ProgressMeasurement.indeterminate(basis="model_invocation"),
    )
    if lifecycle in {
        ActivityLifecycle.RUNNING,
        ActivityLifecycle.STARTING,
        ActivityLifecycle.COMPLETED,
    }:
        emitter.emit(
            category=ActivityCategory.SYNTHESIS,
            phase=ActivityPhase.ANSWER_SYNTHESIS,
            lifecycle=(
                ActivityLifecycle.COMPLETED
                if lifecycle == ActivityLifecycle.COMPLETED
                else ActivityLifecycle.RUNNING
            ),
            title=legacy_step_title("generate_answer"),
            stable_id=f"{emitter.operation_id}:step:generate_answer",
            parent_event_id=f"{emitter.operation_id}:plan_created",
            model_ref=effective_model or requested_model,
        )


def emit_synthesis(
    emitter: ActivityEmitter,
    *,
    lifecycle: ActivityLifecycle,
) -> None:
    emitter.emit(
        category=ActivityCategory.SYNTHESIS,
        phase=ActivityPhase.ANSWER_SYNTHESIS,
        lifecycle=lifecycle,
        title="Answer synthesis",
        stable_id=f"{emitter.operation_id}:synthesis",
        progress=ProgressMeasurement.indeterminate(basis="answer_synthesis"),
    )


def emit_verification(
    emitter: ActivityEmitter,
    *,
    lifecycle: ActivityLifecycle,
    passed: bool | None = None,
    mode: str | None = None,
) -> None:
    summary = None
    if lifecycle == ActivityLifecycle.COMPLETED and passed is True:
        summary = f"Verification passed ({mode})." if mode else "Verification passed."
    elif lifecycle == ActivityLifecycle.COMPLETED and passed is False:
        summary = f"Verification failed ({mode})." if mode else "Verification failed."
    elif lifecycle == ActivityLifecycle.SKIPPED:
        summary = "Verification not required for this turn."
    emitter.emit(
        category=ActivityCategory.VERIFICATION,
        phase=ActivityPhase.RESULT_VERIFICATION,
        lifecycle=lifecycle,
        title="Verification",
        summary=summary,
        stable_id=f"{emitter.operation_id}:verification",
        payload={"passed": passed, "mode": mode},
        progress=ProgressMeasurement.indeterminate(basis="verification"),
    )


def emit_operation_terminal(
    emitter: ActivityEmitter,
    *,
    lifecycle: ActivityLifecycle,
    summary: str | None = None,
    error: Mapping[str, Any] | None = None,
) -> None:
    phase = {
        ActivityLifecycle.COMPLETED: ActivityPhase.COMPLETED,
        ActivityLifecycle.FAILED: ActivityPhase.FAILED,
        ActivityLifecycle.CANCELLED: ActivityPhase.CANCELLED,
        ActivityLifecycle.DEGRADED: ActivityPhase.DEGRADED,
    }.get(lifecycle, ActivityPhase.COMPLETED)
    title = {
        ActivityLifecycle.COMPLETED: "Operation completed",
        ActivityLifecycle.FAILED: "Operation failed",
        ActivityLifecycle.CANCELLED: "Operation cancelled",
        ActivityLifecycle.DEGRADED: "Operation degraded",
    }.get(lifecycle, "Operation finished")
    emitter.emit(
        category=ActivityCategory.SYSTEM,
        phase=phase,
        lifecycle=lifecycle,
        title=title,
        summary=summary,
        stable_id=f"{emitter.operation_id}:terminal",
        error=error,
        progress=ProgressMeasurement.indeterminate(basis="terminal"),
    )


def emit_cancellation(
    emitter: ActivityEmitter,
    *,
    stage: str,
    reason: str | None = None,
) -> None:
    """stage: requested | propagating | cancelled"""
    lifecycle = {
        "requested": ActivityLifecycle.WAITING,
        "propagating": ActivityLifecycle.WAITING,
        "cancelled": ActivityLifecycle.CANCELLED,
    }.get(stage, ActivityLifecycle.WAITING)
    title = {
        "requested": "Cancellation requested",
        "propagating": "Cancellation propagating",
        "cancelled": "Operation cancelled",
    }.get(stage, "Cancellation")
    emitter.emit(
        category=ActivityCategory.SYSTEM,
        phase=ActivityPhase.CANCELLED,
        lifecycle=lifecycle,
        title=title,
        summary=reason,
        stable_id=f"{emitter.operation_id}:cancellation",
        payload={"stage": stage, "reason": reason},
        progress=ProgressMeasurement.indeterminate(basis="cancellation"),
    )


def ingest_cognition_operational_events(
    emitter: ActivityEmitter,
    events: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Map cognition public operational events into activity stream (no private CoT)."""
    published: list[dict[str, Any]] = []
    for raw in list(events or [])[:48]:
        et = str(raw.get("event_type") or "")
        payload = raw.get("payload") if isinstance(raw.get("payload"), Mapping) else {}
        mapped = activity_from_cognition_operational_event(
            et,
            payload,
            operation_id=emitter.operation_id,
            trace_id=emitter.trace_id,
            sequence=emitter.next_sequence(),
        )
        if mapped is None:
            continue
        # Re-emit through emitter for stable-id merge + persistence.
        event = emitter.emit(
            category=mapped.category,
            phase=mapped.phase,
            lifecycle=mapped.lifecycle,
            title=mapped.title,
            summary=mapped.summary,
            stable_id=mapped.event_id,
            actor_type=mapped.actor_type,
            actor_id=mapped.actor_id,
            progress=mapped.progress,
            result_count=mapped.result_count,
            capability_ref=mapped.capability_ref,
            worker_ref=mapped.worker_ref,
            artifact_refs=mapped.artifact_refs,
            evidence_refs=mapped.evidence_refs,
            source_refs=mapped.source_refs,
            error=mapped.error,
            payload=mapped.payload,
        )
        pub = event.public_dict(for_user=True)
        if pub is not None:
            published.append(pub)
    return published


def ingest_team_activity(
    emitter: ActivityEmitter,
    team_events: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    published: list[dict[str, Any]] = []
    for raw in list(team_events or [])[:48]:
        mapped = activity_from_team_event(
            raw,
            operation_id=emitter.operation_id,
            trace_id=emitter.trace_id,
        )
        if mapped is None:
            continue
        event = emitter.emit(
            category=mapped.category,
            phase=mapped.phase,
            lifecycle=mapped.lifecycle,
            title=mapped.title,
            summary=mapped.summary,
            stable_id=mapped.event_id,
            actor_type=mapped.actor_type,
            actor_id=mapped.actor_id,
            agent_ref=mapped.agent_ref,
            progress=mapped.progress,
            payload=mapped.payload,
        )
        pub = event.public_dict(for_user=True)
        if pub is not None:
            published.append(pub)
    return published


def activity_snapshot(emitter: ActivityEmitter) -> dict[str, Any]:
    projection = emitter.projection()
    return {
        "activity": projection.public_dict(for_user=True),
        "events": emitter.public_events(for_user=True),
    }


def _phase_for_step(step_id: str) -> ActivityPhase:
    mapping = {
        "understand_request": ActivityPhase.REQUEST_UNDERSTOOD,
        "retrieve_atlas_context": ActivityPhase.CONTEXT_RETRIEVAL,
        "deep_recall_hydrate": ActivityPhase.KNOWLEDGE_RETRIEVAL,
        "retrieve_relevant_knowledge": ActivityPhase.KNOWLEDGE_RETRIEVAL,
        "structure_response": ActivityPhase.PLANNING,
        "generate_answer": ActivityPhase.ANSWER_SYNTHESIS,
    }
    return mapping.get(step_id, ActivityPhase.PLANNING)


def _category_for_phase(phase: ActivityPhase) -> ActivityCategory:
    if phase in {ActivityPhase.REQUEST_RECEIVED, ActivityPhase.REQUEST_UNDERSTOOD}:
        return ActivityCategory.REQUEST
    if phase in {
        ActivityPhase.KNOWLEDGE_RETRIEVAL,
        ActivityPhase.CONTEXT_RETRIEVAL,
        ActivityPhase.SOURCE_VALIDATION,
    }:
        return ActivityCategory.KNOWLEDGE
    if phase == ActivityPhase.MEMORY_RETRIEVAL:
        return ActivityCategory.MEMORY
    if phase == ActivityPhase.ANSWER_SYNTHESIS:
        return ActivityCategory.SYNTHESIS
    if phase == ActivityPhase.MODEL_INVOCATION:
        return ActivityCategory.MODEL
    return ActivityCategory.PLANNING
