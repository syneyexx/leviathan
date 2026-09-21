"""HTTP routes for HADES local speech (VoiceStudio TTS/STT provider)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from speech.runtime import get_speech_runtime

router = APIRouter(prefix="/speech", tags=["speech"])


class SpeechStopInput(BaseModel):
    generation_id: str | None = Field(default=None, max_length=80)


class SpeechPlaybackInput(BaseModel):
    active: bool
    echo_guard_ms: int | None = Field(default=None, ge=0, le=10_000)


class SpeechSpeakInput(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)
    message_id: str | None = Field(default=None, max_length=120)
    conversation_id: str | None = Field(default=None, max_length=120)


class SpeechChunkInput(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    generation_id: str = Field(min_length=1, max_length=80)
    chunk_index: int = Field(default=0, ge=0, le=10_000)


def mount_speech_routes(ctx: dict[str, Any]) -> APIRouter:
    def _settings() -> dict[str, Any]:
        database = ctx.get("database")
        # Prefer live main.database so tests/runtime rebinds are visible.
        try:
            import main as hades_main

            database = getattr(hades_main, "database", database)
        except Exception:
            pass
        if database is None:
            raise HTTPException(status_code=500, detail="Database niet beschikbaar voor speech.")
        return database.get_settings()

    @router.get("/status")
    async def speech_status() -> dict[str, Any]:
        runtime = get_speech_runtime()
        return await runtime.status(_settings())

    @router.get("/voices")
    async def speech_voices() -> dict[str, Any]:
        runtime = get_speech_runtime()
        status = await runtime.status(_settings())
        tts = status.get("tts") or {}
        if not tts.get("available"):
            raise HTTPException(
                status_code=503,
                detail={
                    "message": tts.get("error") or "VoiceStudio niet beschikbaar.",
                    "recovery": tts.get("recovery") or [],
                    "provider": tts.get("provider"),
                },
            )
        return {
            "voices": tts.get("voices") or [],
            "engines": tts.get("engines") or [],
            "supported_settings": tts.get("supported_settings") or {},
            "selected_engine": tts.get("selected_engine"),
            "streaming_speech": False,
            "version": tts.get("version"),
            "base_url": tts.get("base_url"),
        }

    @router.post("/begin")
    async def speech_begin() -> dict[str, Any]:
        runtime = get_speech_runtime()
        try:
            return await runtime.begin(_settings(), reason="manual")
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/stop")
    async def speech_stop(values: SpeechStopInput) -> dict[str, Any]:
        runtime = get_speech_runtime()
        return await runtime.stop(generation_id=values.generation_id)

    @router.post("/playback")
    async def speech_playback(values: SpeechPlaybackInput) -> dict[str, Any]:
        runtime = get_speech_runtime()
        cfg = runtime.settings_from(_settings())
        guard_ms = values.echo_guard_ms if values.echo_guard_ms is not None else cfg["stt_echo_guard_ms"]
        return runtime.set_playback(active=values.active, echo_guard_ms=guard_ms)

    @router.get("/echo-guard")
    async def speech_echo_guard() -> dict[str, Any]:
        runtime = get_speech_runtime()
        return runtime.echo_guard_state(runtime.settings_from(_settings()))

    @router.post("/preview")
    async def speech_preview() -> dict[str, Any]:
        runtime = get_speech_runtime()
        try:
            return await runtime.preview(_settings())
        except InterruptedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            status = await runtime.status(_settings())
            raise HTTPException(
                status_code=503,
                detail={
                    "message": str(exc),
                    "recovery": (status.get("tts") or {}).get("recovery") or [],
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/speak")
    async def speech_speak(values: SpeechSpeakInput) -> dict[str, Any]:
        runtime = get_speech_runtime()
        try:
            return await runtime.speak_plan(_settings(), text=values.text)
        except InterruptedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            status = await runtime.status(_settings())
            raise HTTPException(
                status_code=503,
                detail={
                    "message": str(exc),
                    "recovery": (status.get("tts") or {}).get("recovery") or [],
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/chunk")
    async def speech_chunk(values: SpeechChunkInput) -> dict[str, Any]:
        runtime = get_speech_runtime()
        try:
            return await runtime.synthesize_chunk(
                _settings(),
                text=values.text,
                generation_id=values.generation_id,
                chunk_index=values.chunk_index,
            )
        except InterruptedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            status = await runtime.status(_settings())
            raise HTTPException(
                status_code=503,
                detail={
                    "message": str(exc),
                    "recovery": (status.get("tts") or {}).get("recovery") or [],
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/transcribe")
    async def speech_transcribe(file: UploadFile = File(...)) -> dict[str, Any]:
        runtime = get_speech_runtime()
        audio = await file.read()
        if not audio:
            raise HTTPException(status_code=400, detail="Leeg audiobestand.")
        try:
            result = await runtime.transcribe(
                _settings(),
                audio=audio,
                filename=file.filename or "audio.wav",
            )
            text = str(result.get("text") or "").strip() if isinstance(result, dict) else ""
            if not text:
                return {
                    "ok": False,
                    "provider": "voicestudio",
                    "error": "empty_transcript",
                    **(result if isinstance(result, dict) else {"raw": result}),
                }
            return {"ok": True, "provider": "voicestudio", **result}
        except RuntimeError as exc:
            raise HTTPException(status_code=409 if "echo-guard" in str(exc).lower() or "geblokkeerd" in str(exc).lower() else 503, detail=str(exc)) from exc

    return router
