"""Voice capability HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from Data.modules.execution import CapabilityRequest, CapabilityStatus
from Data.modules.voice import VoiceAction


class VoiceRequest(BaseModel):
    action: str = Field(min_length=1, max_length=40)
    text: str | None = None
    session_id: str | None = None
    audio_ref: str | None = None
    path: str | None = None
    hint: str | None = None
    conversation_id: str | None = None
    sync_id: str | None = None
    persona: dict | None = None
    approval_id: str | None = None
    run_id: str | None = None
    trace_id: str | None = None


_VOICE_ACTION_TO_CAPABILITY = {
    "START_SESSION": "voice.start_session",
    "TRANSCRIBE": "voice.transcribe",
    "STREAM_ASR": "voice.transcribe",
    "SYNTHESIZE": "voice.synthesize",
    "STREAM_TTS": "voice.synthesize",
    "BARGE_IN": "voice.barge_in",
}


def build_voice_router(
    *,
    settings: Any,
    voice_stub: Any,
    execution_gateway: Any,
    observability: Any,
) -> APIRouter:
    router = APIRouter(tags=["voice"])

    @router.post("/api/voice/request")
    def voice_request(payload: VoiceRequest) -> dict:
        """Voice actions go through ExecutionGateway when multimodal_realtime is on."""
        try:
            action = VoiceAction(payload.action.upper())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid voice action: {payload.action}") from exc

        if not settings.features.multimodal_realtime:
            job = voice_stub.request(action=action, text=payload.text)
            status = 501 if job.status.value == "UNSUPPORTED" else (422 if job.status.value == "REJECTED" else 200)
            if status != 200:
                raise HTTPException(status_code=status, detail=job.public_dict())
            return {"job": job.public_dict(), "truth": {"multimodal_realtime_disabled": True}}

        capability_id = _VOICE_ACTION_TO_CAPABILITY.get(action.value)
        if capability_id is None:
            raise HTTPException(status_code=422, detail=f"No capability mapping for action {action.value}")

        arguments: dict = {}
        for key in ("text", "session_id", "audio_ref", "path", "hint", "conversation_id", "sync_id", "persona"):
            value = getattr(payload, key)
            if value is not None:
                arguments[key] = value
        if payload.run_id is not None:
            arguments["run_id"] = payload.run_id

        result = execution_gateway.execute(
            CapabilityRequest(
                capability_id=capability_id,
                arguments=arguments,
                approval_id=payload.approval_id,
                run_id=payload.run_id,
                requested_by="api.voice",
                trace_id=payload.trace_id,
            )
        )
        observability.emit(
            "voice",
            "request",
            payload={
                "capability_id": capability_id,
                "status": result.status.value,
                "request_id": result.request_id,
                "run_id": payload.run_id,
            },
            level="info" if result.status.value == "COMPLETED" else "warn",
        )
        status_code = 200
        if result.status == CapabilityStatus.REJECTED:
            reason = (result.telemetry or {}).get("reason")
            status_code = 403 if reason in {"approval_required", "approval_denied"} else 422
        elif result.status == CapabilityStatus.FAILED:
            status_code = 500
        if status_code != 200:
            raise HTTPException(status_code=status_code, detail=result.public_dict())
        return {
            "result": result.public_dict(),
            "capability_id": capability_id,
            "truth": {
                "requires_capability_gateway": True,
                "no_parallel_voice_memory": True,
                "fixture_is_not_whisper_or_tts": True,
            },
        }

    return router
