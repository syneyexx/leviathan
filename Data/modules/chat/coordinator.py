"""ChatTurnCoordinator — thin lifecycle helpers around canonical owners.

Does NOT replace CognitiveRuntime, RunStore, Model Control Plane, or ArtifactStore.
Owns: durable turn accept/finalize, response normalization, cancel adapter wiring.
"""

from __future__ import annotations

import json
from typing import Any

from .protocol import measurement_or_none, normalize_chat_response
from .types import (
    ChatTurn,
    ChatTurnRunState,
    ExecutionPath,
    FailureClassification,
    ResponseOwner,
    VerificationTurnState,
)


class ChatTurnCoordinator:
    """Accept / finalize Chat turns against ChatTurnStore + RunStore references."""

    def __init__(self, turn_store: Any) -> None:
        self.turns = turn_store

    def accept(
        self,
        *,
        conversation_id: str,
        user_message_id: int | None,
        chat_run_id: str,
        requested_model: str | None = None,
        requested_reasoning_mode: str | None = None,
        collaboration_strategy: str | None = None,
        idempotency_key: str | None = None,
        behavior_profile_id: str | None = None,
        behavior_version: str | None = None,
        behavior_hash: str | None = None,
        knowledge_available: bool | None = None,
        retrieval_requested: bool | None = None,
    ) -> ChatTurn:
        turn = self.turns.create_turn(
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            chat_run_id=chat_run_id,
            requested_model=requested_model,
            requested_reasoning_mode=requested_reasoning_mode,
            collaboration_strategy=collaboration_strategy,
            idempotency_key=idempotency_key,
            behavior_profile_id=behavior_profile_id,
            behavior_version=behavior_version,
            behavior_hash=behavior_hash,
            knowledge_available=knowledge_available,
            retrieval_requested=retrieval_requested,
            run_state=ChatTurnRunState.ACCEPTED.value,
        )
        # Move to RUNNING immediately after accept.
        if turn.run_state == ChatTurnRunState.ACCEPTED.value:
            try:
                turn = self.turns.transition(turn.turn_id, ChatTurnRunState.RUNNING)
            except Exception:  # noqa: BLE001
                pass
        return turn

    def mark_streaming(self, turn_id: str, *, degraded: bool = False) -> ChatTurn:
        return self.turns.transition(
            turn_id,
            ChatTurnRunState.STREAMING,
            streaming_effective=not degraded,
            streaming_degraded=degraded,
        )

    def complete(
        self,
        turn_id: str,
        *,
        assistant_message_id: int | None,
        effective_model: str | None = None,
        effective_reasoning_mode: str | None = None,
        response_owner: str = ResponseOwner.DIRECT.value,
        execution_path: str = ExecutionPath.DIRECT_CHAT.value,
        cognition_run_id: str | None = None,
        team_run_id: str | None = None,
        provisional: bool = False,
        streaming_effective: bool = False,
        streaming_degraded: bool = False,
        knowledge_hit_count: int | None = None,
        memory_hit_count: int | None = None,
        evidence_hit_count: int | None = None,
        retrieval_coverage: float | None = None,
        knowledge_available: bool | None = None,
        retrieval_requested: bool | None = None,
        verification_mode: str | None = None,
        verification_passed: bool | None = None,
        quality_state: str | None = None,
        tool_receipt_ids: list[str] | None = None,
        artifact_ids: list[str] | None = None,
        source_refs: list[dict] | None = None,
        decision_receipt_ids: list[str] | None = None,
        response_language: str | None = None,
        latency_ms: float | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        context_used: int | None = None,
        context_budget: int | None = None,
        activity_ref: str | None = None,
        metadata: dict | None = None,
    ) -> ChatTurn:
        if verification_passed is True:
            vstate = VerificationTurnState.VERIFIED.value
        elif verification_passed is False:
            vstate = VerificationTurnState.FAILED.value
        elif verification_mode in {None, "", "none", "NOT_REQUIRED"}:
            vstate = (
                VerificationTurnState.NOT_REQUIRED.value
                if verification_mode in {"none", "NOT_REQUIRED"}
                else VerificationTurnState.UNKNOWN.value
            )
        else:
            vstate = VerificationTurnState.UNVERIFIED.value

        return self.turns.transition(
            turn_id,
            ChatTurnRunState.COMPLETED,
            assistant_message_id=assistant_message_id,
            effective_model=effective_model,
            effective_reasoning_mode=effective_reasoning_mode,
            response_owner=response_owner,
            execution_path=execution_path,
            cognition_run_id=cognition_run_id,
            team_run_id=team_run_id,
            provisional=provisional,
            streaming_effective=streaming_effective,
            streaming_degraded=streaming_degraded,
            knowledge_hit_count=knowledge_hit_count,
            memory_hit_count=memory_hit_count,
            evidence_hit_count=evidence_hit_count,
            retrieval_coverage=retrieval_coverage,
            knowledge_available=knowledge_available,
            retrieval_requested=retrieval_requested,
            verification_mode=verification_mode,
            verification_state=vstate,
            quality_state=quality_state,
            tool_receipt_ids_json=json.dumps(tool_receipt_ids or []),
            artifact_ids_json=json.dumps(artifact_ids or []),
            source_refs_json=json.dumps(source_refs or []),
            decision_receipt_ids_json=json.dumps(decision_receipt_ids or []),
            response_language=response_language,
            latency_ms=measurement_or_none(latency_ms),
            input_tokens=measurement_or_none(input_tokens),
            output_tokens=measurement_or_none(output_tokens),
            total_tokens=measurement_or_none(total_tokens),
            context_used=measurement_or_none(context_used),
            context_budget=measurement_or_none(context_budget),
            activity_ref=activity_ref,
            metadata_json=json.dumps(metadata or {}),
            failure_classification=FailureClassification.NONE.value,
        )

    def fail(
        self,
        turn_id: str,
        *,
        classification: str = FailureClassification.BACKEND_FAILURE.value,
        error_summary: str | None = None,
        provisional: bool = False,
        assistant_message_id: int | None = None,
        **fields: Any,
    ) -> ChatTurn:
        return self.turns.transition(
            turn_id,
            ChatTurnRunState.FAILED,
            failure_classification=classification,
            error_summary=error_summary,
            provisional=provisional,
            assistant_message_id=assistant_message_id,
            **fields,
        )

    def attach_response_turn_fields(
        self,
        response: dict[str, Any],
        turn: ChatTurn | None,
    ) -> dict[str, Any]:
        out = normalize_chat_response(response)
        if turn is None:
            return out
        out["turn_id"] = turn.turn_id
        out["chat_turn"] = turn.public_dict()
        out.setdefault("chat_run_id", turn.chat_run_id)
        if turn.cognition_run_id:
            out.setdefault("cognition_run_id", turn.cognition_run_id)
        if turn.team_run_id:
            out.setdefault("team_run_id", turn.team_run_id)
        return out
