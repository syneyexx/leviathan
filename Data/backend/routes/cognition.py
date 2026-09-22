"""FastAPI routes for the Cognitive Runtime operator surface."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from Data.modules.cognition import CognitionError, CognitiveRuntime


class CognitionSubmitRequest(BaseModel):
    message: str = Field(..., min_length=1)
    conversation_id: str | None = None
    history: list[dict[str, str]] = Field(default_factory=list)
    has_knowledge: bool = False
    shadow: bool | None = None
    constraints: list[str] = Field(default_factory=list)
    run: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class CognitionSteerRequest(BaseModel):
    instruction: str = Field(..., min_length=1)


def build_cognition_router(runtime: CognitiveRuntime) -> APIRouter:
    router = APIRouter(tags=["cognition"])

    def _raise(exc: Exception) -> None:
        if isinstance(exc, CognitionError):
            raise HTTPException(status_code=exc.http_status, detail=exc.public_dict()) from exc
        if isinstance(exc, KeyError):
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": str(exc)}) from exc
        raise

    @router.get("/api/cognition/health")
    def cognition_health() -> dict:
        return {"cognition": runtime.health()}

    @router.post("/api/cognition/submit")
    def cognition_submit(payload: CognitionSubmitRequest) -> dict:
        try:
            return runtime.submit(
                payload.message,
                conversation_id=payload.conversation_id,
                history=payload.history,
                has_knowledge=payload.has_knowledge,
                shadow=payload.shadow,
                constraints=payload.constraints,
                metadata=payload.metadata,
                run=payload.run,
            )
        except Exception as exc:  # noqa: BLE001
            _raise(exc)
            raise

    @router.get("/api/cognition/runs/{run_id}")
    def cognition_status(run_id: str) -> dict:
        try:
            return runtime.status(run_id)
        except Exception as exc:  # noqa: BLE001
            _raise(exc)
            raise

    @router.get("/api/cognition/runs/{run_id}/events")
    def cognition_events(run_id: str) -> dict:
        try:
            return {"run_id": run_id, "events": runtime.events(run_id)}
        except Exception as exc:  # noqa: BLE001
            _raise(exc)
            raise

    @router.post("/api/cognition/runs/{run_id}/cancel")
    def cognition_cancel(run_id: str) -> dict:
        try:
            return runtime.cancel(run_id)
        except Exception as exc:  # noqa: BLE001
            _raise(exc)
            raise

    @router.post("/api/cognition/runs/{run_id}/steer")
    def cognition_steer(run_id: str, payload: CognitionSteerRequest) -> dict:
        try:
            return runtime.steer(run_id, payload.instruction)
        except Exception as exc:  # noqa: BLE001
            _raise(exc)
            raise

    @router.post("/api/cognition/runs/{run_id}/resume")
    def cognition_resume(run_id: str) -> dict:
        try:
            return runtime.resume(run_id)
        except Exception as exc:  # noqa: BLE001
            _raise(exc)
            raise

    return router
