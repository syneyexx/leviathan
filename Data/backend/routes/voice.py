"""Voice capability HTTP routes — Control Plane authorize/enqueue only.

Heavy ASR/TTS/preprocess/postprocess execute on the singleton ``voice`` worker.
Cheap status reads may remain inline (cached readiness only).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

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
    "PREPROCESS": "voice.preprocess",
    "POSTPROCESS": "voice.postprocess",
}


def build_voice_router(
    *,
    settings: Any,
    voice_stub: Any,
    execution_gateway: Any,
    observability: Any,
    job_runtime: Any | None = None,
) -> APIRouter:
    router = APIRouter(tags=["voice"])

    @router.get("/api/voice/status")
    def voice_status() -> dict:
        """Cheap cached readiness — must not run ASR/TTS inference."""
        # Control-plane projection only; real backend probe is worker-owned.
        return {
            "voice_worker_pool": "voice",
            "execution_class": "EXTERNAL_REQUIRED",
            "multimodal_realtime": bool(getattr(settings.features, "multimodal_realtime", False)),
            "asr_backend": "NOT_CONFIGURED",
            "tts_backend": "NOT_CONFIGURED",
            "realtime_streaming": "UNSUPPORTED",
            "barge_in": "MEASURED",
            "production_capable": False,
            "truth": {
                "status_does_not_run_inference": True,
                "fixture_is_not_production": True,
                "requires_voice_worker": True,
                "no_parallel_voice_memory": True,
            },
        }

    @router.post("/api/voice/request")
    def voice_request(payload: VoiceRequest, response: Response) -> dict:
        """Enqueue voice work on the voice worker — never inline ASR/TTS."""
        try:
            action = VoiceAction(payload.action.upper())
        except ValueError:
            # Allow PREPROCESS/POSTPROCESS which are not on the legacy enum.
            upper = payload.action.upper()
            if upper not in _VOICE_ACTION_TO_CAPABILITY:
                raise HTTPException(
                    status_code=422, detail=f"Invalid voice action: {payload.action}"
                ) from None
            action_key = upper
        else:
            action_key = action.value

        if not settings.features.multimodal_realtime:
            # Feature-off honesty path — stub only, no fabricated production claim.
            try:
                enum_action = VoiceAction(action_key)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"Invalid voice action: {payload.action}") from exc
            job = voice_stub.request(action=enum_action, text=payload.text)
            status = 501 if job.status.value == "UNSUPPORTED" else (422 if job.status.value == "REJECTED" else 200)
            if status != 200:
                raise HTTPException(status_code=status, detail=job.public_dict())
            return {"job": job.public_dict(), "truth": {"multimodal_realtime_disabled": True}}

        capability_id = _VOICE_ACTION_TO_CAPABILITY.get(action_key)
        if capability_id is None:
            raise HTTPException(status_code=422, detail=f"No capability mapping for action {action_key}")

        if job_runtime is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "error_code": "VOICE_WORKER_UNAVAILABLE",
                    "detail": "JobRuntime not bound — voice work requires voice worker",
                    "truth": {"no_inline_asr_tts_fallback": True},
                },
            )

        arguments: dict = {}
        for key in ("text", "session_id", "audio_ref", "path", "hint", "conversation_id", "sync_id", "persona"):
            value = getattr(payload, key)
            if value is not None:
                arguments[key] = value
        if payload.run_id is not None:
            arguments["run_id"] = payload.run_id

        try:
            job = job_runtime.enqueue(
                capability_id=capability_id,
                arguments=arguments,
                requested_by="api.voice",
                approval_id=payload.approval_id,
                run_id=payload.run_id,
                trace_id=payload.trace_id,
                domain="voice",
                domain_entity_type="voice_session",
                domain_entity_id=str(payload.session_id or payload.conversation_id or "new"),
                worker_pool="voice",
                resource_class="CPU_LIGHT" if capability_id in {"voice.start_session", "voice.barge_in", "voice.postprocess"} else "CPU_HEAVY",
                latency_class="interactive",
                idempotency_key=f"voice:{capability_id}:{uuid.uuid4().hex[:10]}",
                metadata={"execution_class": "EXTERNAL_REQUIRED", "action": action_key},
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=503,
                detail={
                    "error_code": "VOICE_WORKER_UNAVAILABLE",
                    "detail": str(exc)[:300],
                    "truth": {"no_inline_asr_tts_fallback": True},
                },
            ) from exc

        observability.emit(
            "voice",
            "enqueue",
            payload={
                "capability_id": capability_id,
                "job_id": job.job_id,
                "run_id": payload.run_id,
            },
            level="info",
        )
        response.status_code = 202
        return {
            "queued": True,
            "job": job.public_dict(),
            "job_id": job.job_id,
            "capability_id": capability_id,
            "truth": {
                "executed_via": "voice_worker",
                "requires_capability_gateway": True,
                "no_parallel_voice_memory": True,
                "no_inline_asr_tts": True,
                "fixture_is_not_whisper_or_tts": True,
                "no_job_per_audio_frame": True,
            },
        }

    return router
