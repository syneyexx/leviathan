"""Chat turn status + cancellation HTTP adapters over canonical owners."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from Data.modules.chat import CancelReason, cancel_chat_turn


class ChatCancelRequest(BaseModel):
    turn_id: str | None = None
    chat_run_id: str | None = None
    run_id: str | None = None  # alias
    reason: str = Field(default=CancelReason.USER_CANCEL.value)


def build_chat_control_router(
    *,
    chat_turn_store: Any,
    runs: Any,
    cognition_runtime: Any | None = None,
    team_orchestrator: Any | None = None,
) -> APIRouter:
    router = APIRouter(tags=["chat"])

    @router.get("/api/chat/turns/{turn_id}")
    def get_chat_turn(turn_id: str) -> dict:
        turn = chat_turn_store.get(turn_id)
        if turn is None:
            raise HTTPException(status_code=404, detail="Chat turn not found")
        return {"turn": turn.public_dict()}

    @router.get("/api/chat/runs/{run_id}")
    def get_chat_run_status(run_id: str) -> dict:
        """Reconcile Chat turn + RunStore status after reload / ambiguous network."""
        turn = chat_turn_store.get_by_chat_run(run_id)
        run = runs.get_run(run_id) if hasattr(runs, "get_run") else None
        if turn is None and run is None:
            raise HTTPException(status_code=404, detail="Chat run not found")
        run_public = None
        if run is not None:
            run_public = {
                "run_id": run.run_id,
                "state": run.state.value if hasattr(run.state, "value") else str(run.state),
                "conversation_id": getattr(run, "conversation_id", None),
                "error": getattr(run, "error", None),
            }
        return {
            "chat_run_id": run_id,
            "run": run_public,
            "turn": turn.public_dict() if turn else None,
            "truth": {
                "run_store_is_lifecycle_authority": True,
                "chat_turn_is_metadata_authority": True,
            },
        }

    @router.post("/api/chat/cancel")
    def cancel_chat(payload: ChatCancelRequest) -> dict:
        chat_run_id = payload.chat_run_id or payload.run_id
        if not payload.turn_id and not chat_run_id:
            raise HTTPException(
                status_code=422,
                detail="turn_id or chat_run_id required",
            )
        reason = payload.reason or CancelReason.USER_CANCEL.value
        try:
            CancelReason(reason)
        except ValueError:
            # Accept unknown reasons as backend_failure classification path, still cancel.
            pass
        result = cancel_chat_turn(
            turn_store=chat_turn_store,
            run_store=runs,
            cognition_runtime=cognition_runtime,
            team_orchestrator=team_orchestrator,
            turn_id=payload.turn_id,
            chat_run_id=chat_run_id,
            reason=reason,
        )
        return result.public_dict()

    return router
