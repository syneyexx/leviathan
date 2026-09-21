"""HTTP + WebSocket routes for HADES local voice mode."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, Field

from voice import get_voice_runtime
from voice.install import doctor, run_install
from voice.errors import VoiceProviderError
from voice.runtime import new_turn_id, synthesize_response_segments
from voice.speakable import assistant_to_speakable, is_speakable_payload, split_speakable_segments

router = APIRouter(tags=["voice"])


class TranscribeInput(BaseModel):
    audio_base64: str = Field(min_length=8)
    mime_type: str = Field(default="audio/wav", max_length=80)
    language: str | None = Field(default=None, max_length=16)
    session_id: str | None = None
    turn_id: str | None = None
    is_final: bool = True


class SpeakInput(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    voice_id: str | None = None
    language: str | None = None
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    style: Literal["compact", "full"] = "compact"
    already_speakable: bool = False
    message_id: str | None = None
    session_id: str | None = None


class SpeakableInput(BaseModel):
    text: str = Field(min_length=0, max_length=100_000)
    style: Literal["compact", "full"] = "compact"
    language: str = Field(default="nl", max_length=16)


class SessionStartInput(BaseModel):
    conversation_id: str | None = None
    client_tab_id: str = Field(min_length=1, max_length=80)
    keep_audio: bool = False
    force: bool = False
    idle_timeout_seconds: int | None = Field(default=None, ge=0, le=86_400)


class SessionActionInput(BaseModel):
    reason: str = Field(default="user", max_length=80)


class SpeakResponseInput(BaseModel):
    session_id: str
    response_id: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=100_000)
    force_replay: bool = False


class InstallInput(BaseModel):
    steps: list[str] = Field(default_factory=lambda: ["deps", "whisper", "piper_voice"])
    voice_asr_model: str | None = None
    voice_tts_voice: str | None = None
    approved_network: bool = False
    approved_subprocess: bool = False


class WakeProbeInput(BaseModel):
    audio_base64: str = Field(min_length=8)
    mime_type: str = Field(default="audio/wav", max_length=80)
    language: str = Field(default="nl", max_length=16)


def _settings(ctx: dict[str, Any]) -> dict[str, Any]:
    getter = ctx.get("runtime_values")
    if callable(getter):
        try:
            return dict(getter())
        except Exception:
            return {}
    database = ctx.get("database")
    if database is not None:
        try:
            return dict(database.get_settings())
        except Exception:
            return {}
    return {}


def _err(exc: VoiceProviderError) -> HTTPException:
    return HTTPException(status_code=400, detail=exc.to_dict())


def _enforce_install_policy(settings: dict[str, Any], name: str, approved: bool, action: str) -> None:
    current = str(settings.get(name) or "ask").strip().lower()
    if current not in {"allow", "ask", "block"}:
        current = "ask"
    if current == "block":
        raise HTTPException(status_code=403, detail=f"{action} is geblokkeerd door {name}.")
    if current == "ask" and not approved:
        raise HTTPException(status_code=409, detail=f"Expliciete toestemming vereist voor {action} ({name}=ask).")


def mount_voice_routes(ctx: dict[str, Any]) -> APIRouter:
    @router.get("/voice/status")
    async def voice_status() -> dict[str, Any]:
        settings = _settings(ctx)
        report = doctor(settings)
        report["settings"] = {
            "voice_enabled": bool(settings.get("voice_enabled", True)),
            "voice_asr_provider": settings.get("voice_asr_provider", "faster_whisper"),
            "voice_tts_provider": settings.get("voice_tts_provider", "piper"),
            "voice_language": settings.get("voice_language", "nl"),
            "voice_spoken_answers_default": bool(settings.get("voice_spoken_answers_default", False)),
            "voice_wake_word_enabled": bool(settings.get("voice_wake_word_enabled", False)),
            "voice_turn_mode": settings.get("voice_turn_mode", "manual"),
        }
        return report

    @router.post("/voice/doctor")
    async def voice_doctor() -> dict[str, Any]:
        return doctor(_settings(ctx))

    @router.post("/voice/install")
    async def voice_install(values: InstallInput) -> dict[str, Any]:
        settings = _settings(ctx)
        wanted = {str(step).strip() for step in values.steps if str(step).strip()}
        if "deps" in wanted:
            _enforce_install_policy(
                settings,
                "subprocess_policy",
                values.approved_subprocess,
                "voice dependency-installer starten",
            )
            _enforce_install_policy(
                settings,
                "network_policy",
                values.approved_network,
                "voice dependencies ophalen",
            )
        if wanted.intersection({"whisper", "piper_voice"}):
            _enforce_install_policy(
                settings,
                "network_policy",
                values.approved_network,
                "voice modelbestanden ophalen",
            )
        if values.voice_asr_model:
            settings = {**settings, "voice_asr_model": values.voice_asr_model}
        if values.voice_tts_voice:
            settings = {**settings, "voice_tts_voice": values.voice_tts_voice}

        def _run() -> dict[str, Any]:
            return run_install(values.steps, settings=settings)

        return await asyncio.to_thread(_run)

    @router.post("/voice/transcribe")
    async def voice_transcribe(values: TranscribeInput) -> dict[str, Any]:
        settings = _settings(ctx)
        runtime = get_voice_runtime()
        try:
            audio = base64.b64decode(values.audio_base64)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Ongeldige audio_base64.") from exc
        language = values.language or settings.get("voice_language") or "nl"
        started = time.time()
        asr = runtime.asr_provider(settings)

        def _run():
            return asr.transcribe(audio, language=language, mime_type=values.mime_type)

        try:
            result = await asyncio.to_thread(_run)
        except VoiceProviderError as exc:
            raise _err(exc) from exc
        elapsed_ms = int((time.time() - started) * 1000)
        text = (result.text or "").strip()
        silence = bool(result.metadata.get("silence")) or not text
        turn_id = values.turn_id or new_turn_id()
        payload = {
            "turn_id": turn_id,
            "text": text,
            "is_partial": not values.is_final,
            "is_final": bool(values.is_final) and not silence,
            "silence": silence,
            "language": result.language,
            "confidence": result.confidence,
            "provider": result.provider,
            "model": result.model,
            "duration_seconds": result.duration_seconds,
            "elapsed_ms": elapsed_ms,
            "metadata": result.metadata,
            "should_send": bool(values.is_final) and not silence and bool(text),
        }
        if values.session_id:
            session = runtime.sessions.get(values.session_id)
            if session:
                if session.keep_audio and not silence:
                    try:
                        from pathlib import Path
                        from voice import VOICE_DATA_DIR
                        from voice.audio_utils import ensure_wav_mono16

                        keep_dir = VOICE_DATA_DIR / "recordings" / session.session_id
                        keep_dir.mkdir(parents=True, exist_ok=True)
                        wav_bytes, _rate = ensure_wav_mono16(audio, values.mime_type)
                        path = keep_dir / f"{turn_id}.wav"
                        path.write_bytes(wav_bytes)
                        session.temp_files.append(str(path))
                        payload["kept_audio_path"] = str(path)
                    except Exception as exc:
                        payload["keep_audio_error"] = str(exc)[:200]
                if silence or not values.is_final:
                    session.emit("transcript_partial" if not values.is_final else "status", {"text": text, "silence": silence}, turn_id=turn_id)
                else:
                    accepted = runtime.sessions.register_final_transcript(session, turn_id, text)
                    payload["accepted"] = accepted
                    if accepted:
                        session.emit("transcript_final", {"text": text, "language": result.language}, turn_id=turn_id)
                    else:
                        payload["should_send"] = False
                        payload["deduped"] = True
        return payload

    @router.post("/voice/transcribe-upload")
    async def voice_transcribe_upload(
        file: UploadFile = File(...),
        language: str | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
    ) -> dict[str, Any]:
        data = await file.read()
        encoded = base64.b64encode(data).decode("ascii")
        return await voice_transcribe(
            TranscribeInput(
                audio_base64=encoded,
                mime_type=file.content_type or "application/octet-stream",
                language=language,
                session_id=session_id,
                turn_id=turn_id,
                is_final=True,
            )
        )

    @router.post("/voice/speakable")
    async def voice_speakable(values: SpeakableInput) -> dict[str, Any]:
        speakable = assistant_to_speakable(values.text, style=values.style, language=values.language)
        segments = split_speakable_segments(speakable)
        return {
            "speakable_text": speakable,
            "segments": segments,
            "style": values.style,
            "language": values.language,
            "speakable_contract": {
                "provisional_stream_delta": False,
                "requires_speakable_flag_or_final_answer": True,
                "helper": "is_speakable_payload",
            },
        }

    @router.post("/voice/speakable/check")
    async def voice_speakable_check(payload: dict[str, Any]) -> dict[str, Any]:
        return {"speakable": is_speakable_payload(payload), "payload": payload}

    @router.post("/voice/speak")
    async def voice_speak(values: SpeakInput) -> Response:
        settings = _settings(ctx)
        runtime = get_voice_runtime()
        language = values.language or settings.get("voice_language") or "nl"
        style = values.style or settings.get("voice_speak_style") or "compact"
        text = values.text if values.already_speakable else assistant_to_speakable(values.text, style=style, language=language)
        if not text.strip():
            raise HTTPException(status_code=400, detail="Geen spreekbare tekst.")
        tts = runtime.tts_provider(settings)
        voice_id = values.voice_id or settings.get("voice_tts_voice") or settings.get("tts_voice_id") or None
        speed = values.speed if values.speed else float(settings.get("voice_tts_speed") or settings.get("tts_speed") or 1.0)

        def _run():
            return tts.synthesize(text, voice_id=voice_id, language=language, speed=speed)

        try:
            result = await asyncio.to_thread(_run)
        except VoiceProviderError as exc:
            raise _err(exc) from exc
        headers = {
            "X-HADES-Voice-Provider": result.provider,
            "X-HADES-Voice-Id": result.voice_id,
            "X-HADES-Sample-Rate": str(result.sample_rate),
            "X-HADES-Speakable-Chars": str(len(text)),
        }
        if values.message_id:
            headers["X-HADES-Message-Id"] = values.message_id
        return Response(content=result.audio, media_type=result.mime_type, headers=headers)

    @router.get("/voice/voices")
    async def voice_voices(language: str | None = None) -> dict[str, Any]:
        settings = _settings(ctx)
        runtime = get_voice_runtime()
        tts = runtime.tts_provider(settings)
        voices = [v.__dict__ for v in tts.list_voices(language)]
        return {"voices": voices, "provider": getattr(tts, "id", ""), "availability": tts.availability()}

    @router.post("/voice/session/start")
    async def voice_session_start(values: SessionStartInput) -> dict[str, Any]:
        settings = _settings(ctx)
        runtime = get_voice_runtime()
        idle = values.idle_timeout_seconds
        if idle is None:
            idle = int(settings.get("voice_session_idle_seconds") or 120)
        try:
            session = runtime.sessions.start(
                conversation_id=values.conversation_id,
                client_tab_id=values.client_tab_id,
                keep_audio=values.keep_audio,
                force=values.force,
                idle_timeout_seconds=idle,
            )
        except VoiceProviderError as exc:
            raise _err(exc) from exc
        return {
            "session_id": session.session_id,
            "conversation_id": session.conversation_id,
            "client_tab_id": session.client_tab_id,
            "status": session.status,
            "generation": session.generation,
            "mic_must_reenable": True,
            "idle_timeout_seconds": session.idle_timeout_seconds,
        }

    @router.post("/voice/session/{session_id}/stop")
    async def voice_session_stop(session_id: str, values: SessionActionInput | None = None) -> dict[str, Any]:
        runtime = get_voice_runtime()
        event = runtime.sessions.stop(session_id, reason=(values.reason if values else "user"))
        if not event:
            raise HTTPException(status_code=404, detail="Sessie niet gevonden.")
        return {"stopped": True, "event": event}

    @router.post("/voice/session/{session_id}/interrupt")
    async def voice_session_interrupt(session_id: str, values: SessionActionInput | None = None) -> dict[str, Any]:
        runtime = get_voice_runtime()
        session = runtime.sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Sessie niet gevonden.")
        started = time.time()
        event = session.interrupt(reason=(values.reason if values else "user"))
        runtime.sessions.touch(session_id)
        # Measure interrupt path latency on server (audio stop itself is client-side).
        event["payload"]["interrupt_handler_ms"] = int((time.time() - started) * 1000)
        return {"ok": True, "event": event}

    @router.post("/voice/session/speak-response")
    async def voice_session_speak_response(values: SpeakResponseInput) -> dict[str, Any]:
        settings = _settings(ctx)
        runtime = get_voice_runtime()
        session = runtime.sessions.get(values.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Sessie niet gevonden.")
        runtime.sessions.touch(values.session_id)
        if values.force_replay:
            session.interrupt(reason="replay")
            # New generation for replay segments
            session.generation = session.queue.bump_generation()

        def _run():
            return synthesize_response_segments(
                runtime=runtime,
                session=session,
                response_id=values.response_id,
                text=values.text,
                settings=settings,
                force_replay=bool(values.force_replay),
            )

        try:
            events = await asyncio.to_thread(_run)
        except VoiceProviderError as exc:
            raise _err(exc) from exc
        if events:
            return {"ok": True, "segments": len(events), "events": events}
        spoken_key = f"{values.response_id}:{session.generation}"
        # Idempotent skip leaves the spoken mark set; empty/interrupted synthesis unmarks.
        if spoken_key in session.spoken_response_ids:
            return {
                "ok": True,
                "segments": 0,
                "events": [],
                "skipped": "already_spoken",
            }
        return {
            "ok": False,
            "segments": 0,
            "events": [],
            "error": "no_speech_segments",
        }

    @router.post("/voice/wake/probe")
    async def voice_wake_probe(values: WakeProbeInput) -> dict[str, Any]:
        settings = _settings(ctx)
        if not settings.get("voice_wake_word_enabled"):
            return {"enabled": False, "detected": False, "message": "Activatiewoord staat uit."}
        runtime = get_voice_runtime()
        try:
            audio = base64.b64decode(values.audio_base64)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Ongeldige audio_base64.") from exc
        detector = runtime.wake_detector(settings)
        result = await asyncio.to_thread(lambda: detector.process_audio(audio, mime_type=values.mime_type, language=values.language))
        return result

    @router.get("/voice/recordings")
    async def voice_recordings_list() -> dict[str, Any]:
        """List kept session recordings (only when voice_keep_recordings / keep_audio was used)."""
        from pathlib import Path
        from voice import VOICE_DATA_DIR

        root = VOICE_DATA_DIR / "recordings"
        sessions: list[dict[str, Any]] = []
        if root.exists():
            for session_dir in sorted(root.iterdir()):
                if not session_dir.is_dir():
                    continue
                files = []
                for wav in sorted(session_dir.glob("*.wav")):
                    files.append({"name": wav.name, "bytes": wav.stat().st_size, "path": str(wav)})
                if files:
                    sessions.append({"session_id": session_dir.name, "files": files, "file_count": len(files)})
        return {"sessions": sessions, "root": str(root), "note": "Alleen aanwezig wanneer Opnamen bewaren aan stond."}

    @router.delete("/voice/recordings/{session_id}")
    async def voice_recordings_delete(session_id: str) -> dict[str, Any]:
        import re
        import shutil
        from pathlib import Path
        from voice import VOICE_DATA_DIR

        if not re.fullmatch(r"vses_[a-f0-9]{8,32}", session_id or ""):
            raise HTTPException(status_code=400, detail="Ongeldige session_id.")
        target = VOICE_DATA_DIR / "recordings" / session_id
        if not target.exists():
            raise HTTPException(status_code=404, detail="Geen opnamen voor deze sessie.")
        try:
            shutil.rmtree(target)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Verwijderen mislukt: {exc}") from exc
        if target.exists():
            return {"ok": False, "deleted": None, "error": "recording_still_present", "session_id": session_id}
        return {"ok": True, "deleted": session_id}

    @router.get("/voice/metrics/reference")
    async def voice_metrics_reference() -> dict[str, Any]:
        """Reference environment measurements — unknown until host verification."""
        return {
            "environment": "cloud-agent / CI reference — physical audio unknown",
            "mic_ready_ms": None,
            "first_partial_ms": None,
            "final_transcript_ms": None,
            "first_spoken_response_ms": None,
            "interrupt_to_audio_stop_ms": None,
            "nl_transcript_error_rate": None,
            "false_triggers_silence": None,
            "false_triggers_own_voice": None,
            "cpu_ram_note": "unknown until measured on host",
            "gpu_note": "unknown until measured on host",
            "status": "unknown",
            "transcript_mode": "final_only",
            "note": (
                "Chat Spraak-modus verstuurt complete utterances (final-only); "
                "first_partial_ms blijft N/A tot streaming partials bestaan. "
                "Vul hostmetingen in via docs/voice/HOST_TEST.md."
            ),
        }

    @router.websocket("/voice/session/ws")
    async def voice_session_ws(websocket: WebSocket) -> None:
        """Optional experimental WebSocket for the same final-only session protocol.

        The primary Chat UI uses HTTP (`/voice/transcribe`, `/voice/session/*`).
        This socket accepts complete utterance blobs (`audio_final`), not MediaRecorder chunks.
        """
        from local_api_trust import is_trusted_peer

        peer = websocket.client.host if websocket.client else None
        if not is_trusted_peer(peer):
            await websocket.close(code=1008, reason="Untrusted peer rejected for local voice WS")
            return
        await websocket.accept()
        runtime = get_voice_runtime()
        session = None
        settings = _settings(ctx)

        def push(event: dict[str, Any]) -> None:
            try:
                asyncio.get_event_loop().create_task(websocket.send_json(event))
            except Exception:
                pass

        try:
            while True:
                message = await websocket.receive_json()
                msg_type = str(message.get("type") or "")
                if msg_type == "start":
                    try:
                        idle = message.get("idle_timeout_seconds")
                        if idle is None:
                            idle = int(settings.get("voice_session_idle_seconds") or 120)
                        session = runtime.sessions.start(
                            conversation_id=message.get("conversation_id"),
                            client_tab_id=str(message.get("client_tab_id") or "ws"),
                            keep_audio=bool(message.get("keep_audio")),
                            force=bool(message.get("force")),
                            idle_timeout_seconds=int(idle),
                        )
                        session.subscribers.append(push)
                        await websocket.send_json({"type": "session_started", "session_id": session.session_id, "status": session.status})
                    except VoiceProviderError as exc:
                        await websocket.send_json({"type": "error", "payload": exc.to_dict()})
                elif msg_type == "audio_final" and session:
                    turn_id = str(message.get("turn_id") or new_turn_id())
                    audio_b64 = str(message.get("audio_base64") or "")
                    mime_type = str(message.get("mime_type") or "audio/wav")
                    language = message.get("language") or settings.get("voice_language") or "nl"
                    try:
                        audio = base64.b64decode(audio_b64)
                    except Exception:
                        await websocket.send_json({"type": "error", "payload": {"code": "bad_audio", "message": "Ongeldige audio"}})
                        continue
                    session.emit("speech_started", {}, turn_id=turn_id)
                    asr = runtime.asr_provider(settings)

                    def _run():
                        return asr.transcribe(audio, language=language, mime_type=mime_type)

                    try:
                        result = await asyncio.to_thread(_run)
                    except VoiceProviderError as exc:
                        await websocket.send_json({"type": "error", "payload": exc.to_dict()})
                        continue
                    text = (result.text or "").strip()
                    if not text:
                        session.emit("status", {"status": "Stilte — geen bericht verzonden", "silence": True}, turn_id=turn_id)
                        await websocket.send_json({"type": "transcript_final", "turn_id": turn_id, "text": "", "silence": True, "should_send": False})
                        continue
                    accepted = runtime.sessions.register_final_transcript(session, turn_id, text)
                    await websocket.send_json(
                        {
                            "type": "transcript_final",
                            "turn_id": turn_id,
                            "text": text,
                            "language": result.language,
                            "should_send": accepted,
                            "deduped": not accepted,
                        }
                    )
                elif msg_type == "interrupt" and session:
                    event = session.interrupt(reason=str(message.get("reason") or "user"))
                    await websocket.send_json(event)
                elif msg_type == "stop" and session:
                    event = runtime.sessions.stop(session.session_id, reason="user")
                    await websocket.send_json(event or {"type": "session_stopped"})
                    break
                elif msg_type == "ping":
                    await websocket.send_json({"type": "pong", "t": time.time()})
                else:
                    await websocket.send_json({"type": "error", "payload": {"code": "unknown_type", "message": msg_type}})
        except WebSocketDisconnect:
            if session:
                runtime.sessions.stop(session.session_id, reason="disconnect")
        except Exception as exc:
            try:
                await websocket.send_json({"type": "error", "payload": {"code": "ws_error", "message": str(exc)}})
            except Exception:
                pass
            if session:
                runtime.sessions.stop(session.session_id, reason="error")

    return router
