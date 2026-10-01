"""Canonical Chat cancellation — adapts over RunStore / CognitiveRuntime / TEAM."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class CancelReason(str, Enum):
    USER_CANCEL = "user_cancel"
    CLIENT_DISCONNECT = "client_disconnect"
    TIMEOUT = "timeout"
    PROVIDER_FAILURE = "provider_failure"
    BACKEND_FAILURE = "backend_failure"
    PROTOCOL_FAILURE = "protocol_failure"


@dataclass
class ChatCancelResult:
    turn_id: str | None
    chat_run_id: str | None
    run_state: str
    cancelled: bool
    already_terminal: bool
    reason: str
    cognition_cancel: dict[str, Any] | None = None
    team_cancel: dict[str, Any] | None = None
    truth: dict[str, bool] | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "chat_run_id": self.chat_run_id,
            "run_state": self.run_state,
            "cancelled": self.cancelled,
            "already_terminal": self.already_terminal,
            "reason": self.reason,
            "cognition_cancel": self.cognition_cancel,
            "team_cancel": self.team_cancel,
            "truth": self.truth
            or {
                "cancelled_is_not_failed": True,
                "idempotent_cancel": True,
            },
        }


def cancel_chat_turn(
    *,
    turn_store: Any,
    run_store: Any,
    cognition_runtime: Any | None = None,
    team_orchestrator: Any | None = None,
    turn_id: str | None = None,
    chat_run_id: str | None = None,
    reason: CancelReason | str = CancelReason.USER_CANCEL,
    activity_emit: Callable[..., None] | None = None,
) -> ChatCancelResult:
    """Cancel logical Chat execution. Idempotent — repeated cancel does not corrupt state."""
    from Data.modules.run import RunState
    from Data.modules.chat.types import (
        ChatTurnRunState,
        FailureClassification,
        InvalidTurnTransition,
    )

    reason_value = reason.value if isinstance(reason, CancelReason) else str(reason)
    turn = None
    if turn_id and turn_store is not None:
        turn = turn_store.get(turn_id)
    if turn is None and chat_run_id and turn_store is not None:
        turn = turn_store.get_by_chat_run(chat_run_id)
    if turn is not None:
        turn_id = turn.turn_id
        chat_run_id = chat_run_id or turn.chat_run_id

    if turn is not None and turn.run_state in {
        ChatTurnRunState.COMPLETED.value,
        ChatTurnRunState.FAILED.value,
        ChatTurnRunState.CANCELLED.value,
    }:
        return ChatCancelResult(
            turn_id=turn.turn_id,
            chat_run_id=turn.chat_run_id,
            run_state=turn.run_state,
            cancelled=turn.run_state == ChatTurnRunState.CANCELLED.value,
            already_terminal=True,
            reason=reason_value,
        )

    cognition_result = None
    team_result = None

    if activity_emit is not None:
        try:
            activity_emit(stage="requested", reason=reason_value)
        except Exception:  # noqa: BLE001
            pass

    # Propagate to cognition child when present.
    cog_id = turn.cognition_run_id if turn else None
    if cog_id and cognition_runtime is not None and hasattr(cognition_runtime, "cancel"):
        try:
            if activity_emit is not None:
                activity_emit(stage="propagating", reason=reason_value, target="cognition")
            cognition_result = cognition_runtime.cancel(cog_id)
        except Exception as exc:  # noqa: BLE001
            cognition_result = {"error": f"{type(exc).__name__}: {exc}"}

    team_id = turn.team_run_id if turn else None
    if team_id and team_orchestrator is not None and hasattr(team_orchestrator, "cancel"):
        try:
            if activity_emit is not None:
                activity_emit(stage="propagating", reason=reason_value, target="team")
            team_state = team_orchestrator.cancel(team_id)
            team_result = (
                team_state.public_dict() if hasattr(team_state, "public_dict") else dict(team_state)
            )
        except Exception as exc:  # noqa: BLE001
            team_result = {"error": f"{type(exc).__name__}: {exc}"}

    run_state_value = ChatTurnRunState.CANCELLED.value
    if chat_run_id and run_store is not None:
        try:
            run = run_store.get_run(chat_run_id)
            if run is not None:
                current = run.state if hasattr(run.state, "value") else RunState(str(run.state))
                if current in {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}:
                    # Run already terminal — align turn, do not force illegal transition.
                    if current == RunState.CANCELLED:
                        run_state_value = ChatTurnRunState.CANCELLED.value
                    elif current == RunState.COMPLETED:
                        run_state_value = ChatTurnRunState.COMPLETED.value
                    else:
                        run_state_value = ChatTurnRunState.FAILED.value
                else:
                    run_store.transition(chat_run_id, RunState.CANCELLED, error=reason_value)
                    run_state_value = ChatTurnRunState.CANCELLED.value
        except Exception:  # noqa: BLE001
            try:
                run_store.transition(chat_run_id, RunState.CANCELLED, error=reason_value)
            except Exception:  # noqa: BLE001
                pass

    if turn is not None and turn_store is not None:
        try:
            if run_state_value == ChatTurnRunState.CANCELLED.value:
                turn_store.transition(
                    turn.turn_id,
                    ChatTurnRunState.CANCELLED,
                    failure_classification=(
                        FailureClassification.USER_CANCEL.value
                        if reason_value == CancelReason.USER_CANCEL.value
                        else FailureClassification.CLIENT_DISCONNECT.value
                        if reason_value == CancelReason.CLIENT_DISCONNECT.value
                        else FailureClassification.UNKNOWN.value
                    ),
                    error_summary=reason_value,
                )
            elif run_state_value == ChatTurnRunState.COMPLETED.value:
                # Cancel raced completion — keep COMPLETED (authoritative).
                pass
            else:
                turn_store.transition(
                    turn.turn_id,
                    ChatTurnRunState.FAILED,
                    failure_classification=FailureClassification.BACKEND_FAILURE.value,
                    error_summary=reason_value,
                )
        except InvalidTurnTransition:
            pass
        turn = turn_store.get(turn.turn_id)
        if turn is not None:
            run_state_value = turn.run_state

    if activity_emit is not None:
        try:
            activity_emit(stage="cancelled", reason=reason_value)
        except Exception:  # noqa: BLE001
            pass

    return ChatCancelResult(
        turn_id=turn_id,
        chat_run_id=chat_run_id,
        run_state=run_state_value,
        cancelled=run_state_value == ChatTurnRunState.CANCELLED.value,
        already_terminal=False,
        reason=reason_value,
        cognition_cancel=cognition_result if isinstance(cognition_result, dict) else None,
        team_cancel=team_result if isinstance(team_result, dict) else None,
    )
