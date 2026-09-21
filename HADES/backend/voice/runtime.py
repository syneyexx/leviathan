"""Voice session coordination: dedupe, generations, tab exclusivity, metrics."""

from __future__ import annotations

import base64
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from voice.events import AudioSegment, AudioSegmentQueue, VoiceEvent
from voice.errors import VoiceProviderError
from voice.speakable import assistant_to_speakable, split_speakable_segments
from voice.wake_word import WakeWordDetector


def new_session_id() -> str:
    return f"vses_{uuid.uuid4().hex[:16]}"


def new_turn_id() -> str:
    return f"vturn_{uuid.uuid4().hex[:12]}"


@dataclass
class VoiceSession:
    session_id: str
    conversation_id: str | None
    client_tab_id: str
    created_at: float = field(default_factory=time.time)
    last_activity_at: float = field(default_factory=time.time)
    idle_timeout_seconds: int = 120
    status: str = "idle"
    mic_muted: bool = False
    output_muted: bool = False
    generation: int = 1
    sequence: int = 0
    active_turn_id: str | None = None
    last_transcript_final_id: str | None = None
    completed_turn_ids: set[str] = field(default_factory=set)
    spoken_response_ids: set[str] = field(default_factory=set)
    queue: AudioSegmentQueue = field(default_factory=AudioSegmentQueue)
    metrics: dict[str, Any] = field(default_factory=dict)
    keep_audio: bool = False
    temp_files: list[str] = field(default_factory=list)
    subscribers: list[Callable[[dict[str, Any]], None]] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def touch(self) -> None:
        self.last_activity_at = time.time()

    def emit(self, event_type: str, payload: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        with self.lock:
            self.sequence += 1
            self.last_activity_at = time.time()
            event = VoiceEvent(
                type=event_type,  # type: ignore[arg-type]
                session_id=self.session_id,
                sequence=self.sequence,
                payload=payload or {},
                turn_id=kwargs.get("turn_id", self.active_turn_id),
                response_id=kwargs.get("response_id"),
                generation=kwargs.get("generation", self.generation),
            )
            data = event.to_dict()
            for sub in list(self.subscribers):
                try:
                    sub(data)
                except Exception:
                    pass
            return data

    def interrupt(self, *, reason: str = "user") -> dict[str, Any]:
        with self.lock:
            self.generation += 1
            gen = self.queue.bump_generation()
            self.generation = gen
            started = time.time()
            payload = self.emit(
                "interrupted",
                {
                    "reason": reason,
                    "generation": gen,
                    "audio_stop_requested_at": started,
                    "target_stop_ms": 250,
                },
            )
            self.status = "interrupted"
            return payload

    def note_metric(self, key: str, value: Any) -> None:
        self.metrics[key] = value


class VoiceSessionManager:
    """Process-local session registry with single-active-tab guard."""

    def __init__(self):
        self._sessions: dict[str, VoiceSession] = {}
        self._tab_owner: dict[str, str] = {}
        self._lock = threading.RLock()
        self._reaper_stop = threading.Event()
        self._reaper: threading.Thread | None = None

    def start(
        self,
        *,
        conversation_id: str | None,
        client_tab_id: str,
        keep_audio: bool = False,
        force: bool = False,
        idle_timeout_seconds: int = 120,
    ) -> VoiceSession:
        client_tab_id = (client_tab_id or "").strip() or f"tab_{uuid.uuid4().hex[:8]}"
        idle = max(0, int(idle_timeout_seconds or 0))
        with self._lock:
            existing_sid = self._tab_owner.get(client_tab_id)
            if existing_sid and existing_sid in self._sessions and not force:
                # Reconnect same tab: return existing without enabling mic silently —
                # client must re-assert capture after reconnect.
                session = self._sessions[existing_sid]
                session.idle_timeout_seconds = idle or session.idle_timeout_seconds
                session.touch()
                session.emit("status", {"status": "reconnect_resume", "mic_must_reenable": True})
                self._ensure_reaper()
                return session
            # Another tab already owns a live session?
            for sid, session in list(self._sessions.items()):
                if session.client_tab_id != client_tab_id and session.status not in {"stopped"}:
                    if not force:
                        raise VoiceProviderError(
                            "session_elsewhere",
                            "Er is al een spraaksessie in een ander tabblad.",
                            recovery="Sluit de andere sessie of forceer overname.",
                            details={"other_session_id": sid},
                        )
                    self.stop(sid, reason="taken_over")
            session = VoiceSession(
                session_id=new_session_id(),
                conversation_id=conversation_id,
                client_tab_id=client_tab_id,
                keep_audio=keep_audio,
                idle_timeout_seconds=idle,
                status="starting",
            )
            self._sessions[session.session_id] = session
            self._tab_owner[client_tab_id] = session.session_id
            session.emit(
                "session_started",
                {
                    "conversation_id": conversation_id,
                    "client_tab_id": client_tab_id,
                    "status": "Luistert" if not session.mic_muted else "Microfoon gedempt",
                    "idle_timeout_seconds": idle,
                },
            )
            session.status = "listening"
            self._ensure_reaper()
            return session

    def get(self, session_id: str) -> VoiceSession | None:
        return self._sessions.get(session_id)

    def touch(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session:
            session.touch()

    def reap_idle(self, now: float | None = None) -> list[str]:
        """Stop sessions that exceeded their idle timeout. Returns stopped session ids."""
        now = time.time() if now is None else now
        to_stop: list[str] = []
        with self._lock:
            for sid, session in list(self._sessions.items()):
                timeout = int(session.idle_timeout_seconds or 0)
                if timeout <= 0:
                    continue
                if (now - session.last_activity_at) >= timeout:
                    to_stop.append(sid)
        stopped: list[str] = []
        for sid in to_stop:
            if self.stop(sid, reason="idle"):
                stopped.append(sid)
        return stopped

    def _ensure_reaper(self) -> None:
        if self._reaper and self._reaper.is_alive():
            return

        def _loop() -> None:
            while not self._reaper_stop.wait(5.0):
                try:
                    self.reap_idle()
                except Exception:
                    pass

        self._reaper = threading.Thread(target=_loop, name="hades-voice-idle-reaper", daemon=True)
        self._reaper.start()

    def stop(self, session_id: str, *, reason: str = "user") -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if not session:
                return None
            if self._tab_owner.get(session.client_tab_id) == session_id:
                self._tab_owner.pop(session.client_tab_id, None)
            session.queue.clear()
            session.status = "stopped"
            # Cleanup temp files only when the user did not opt into keep recordings.
            from pathlib import Path

            if not session.keep_audio:
                for path in list(session.temp_files):
                    try:
                        Path(path).unlink(missing_ok=True)
                    except Exception:
                        pass
                session.temp_files.clear()
            return session.emit("session_stopped", {"reason": reason, "kept_audio": bool(session.keep_audio and session.temp_files)})

    def register_final_transcript(self, session: VoiceSession, turn_id: str, text: str) -> bool:
        """Return False if this final turn was already accepted (dedupe / reconnect)."""
        with session.lock:
            if turn_id in session.completed_turn_ids:
                return False
            if not (text or "").strip():
                return False
            session.completed_turn_ids.add(turn_id)
            session.last_transcript_final_id = turn_id
            session.active_turn_id = turn_id
            return True

    def mark_response_spoken(self, session: VoiceSession, response_id: str) -> bool:
        with session.lock:
            if response_id in session.spoken_response_ids:
                return False
            session.spoken_response_ids.add(response_id)
            return True

    def unmark_response_spoken(self, session: VoiceSession, response_id: str) -> None:
        with session.lock:
            session.spoken_response_ids.discard(response_id)


# Process singleton
_SESSION_MANAGER: VoiceSessionManager | None = None


def get_session_manager() -> VoiceSessionManager:
    global _SESSION_MANAGER
    if _SESSION_MANAGER is None:
        _SESSION_MANAGER = VoiceSessionManager()
    return _SESSION_MANAGER


def synthesize_response_segments(
    *,
    runtime: Any,
    session: VoiceSession,
    response_id: str,
    text: str,
    settings: dict[str, Any],
    force_replay: bool = False,
) -> list[dict[str, Any]]:
    """Convert final assistant text into ordered TTS segments (never provisional deltas)."""
    spoken_key = f"{response_id}:{session.generation}"
    manager = get_session_manager()
    if not force_replay and not manager.mark_response_spoken(session, spoken_key):
        return []
    if force_replay:
        manager.mark_response_spoken(session, spoken_key)
    style = str(settings.get("voice_speak_style") or "compact")
    language = str(settings.get("voice_language") or "nl")
    speakable = assistant_to_speakable(text, style=style, language=language)  # type: ignore[arg-type]
    parts = split_speakable_segments(speakable)
    session.emit("response_started", {"response_id": response_id, "segment_count": len(parts), "speakable_chars": len(speakable)}, response_id=response_id)
    events: list[dict[str, Any]] = []
    from voice.providers import resolve_tts_provider_id

    tts_settings = dict(settings)
    selected = resolve_tts_provider_id(tts_settings)
    tts_settings["voice_tts_provider"] = selected
    if selected == "voicestudio":
        tts_settings["tts_provider"] = "voicestudio"
    tts = runtime.tts_provider(tts_settings)
    gen = session.generation
    produced = 0
    try:
        for order, part in enumerate(parts):
            if session.generation != gen:
                break
            result = tts.synthesize(
                part,
                voice_id=settings.get("voice_tts_voice") or settings.get("tts_voice_id") or None,
                language=language,
                speed=float(settings.get("voice_tts_speed") or settings.get("tts_speed") or 1.0),
                cancel_check=lambda: session.generation != gen,
            )
            b64 = base64.b64encode(result.audio).decode("ascii")
            segment = AudioSegment(
                session_id=session.session_id,
                turn_id=session.active_turn_id or "",
                response_id=response_id,
                order=order,
                generation=gen,
                mime_type=result.mime_type,
                sample_rate=result.sample_rate,
                audio_b64=b64,
                text=part,
            )
            session.queue.push(segment)
            event = session.emit(
                "speech_segment_ready",
                {
                    "order": order,
                    "mime_type": result.mime_type,
                    "sample_rate": result.sample_rate,
                    "audio_base64": b64,
                    "text": part,
                    "voice_id": result.voice_id,
                    "provider": result.provider,
                },
                response_id=response_id,
                generation=gen,
            )
            events.append(event)
            produced += 1
    except Exception:
        # Allow retry / re-read when synthesis failed before any audio was produced.
        if produced == 0:
            manager.unmark_response_spoken(session, spoken_key)
        raise
    if produced == 0:
        manager.unmark_response_spoken(session, spoken_key)
    return events

class VoiceRuntime:
    """Shared ASR/TTS instances keyed by settings fingerprint."""

    _instance: "VoiceRuntime | None" = None

    def __init__(self) -> None:
        self._asr = None
        self._asr_key: str | None = None
        self._tts = None
        self._tts_key: str | None = None
        self._lock = threading.RLock()
        self.sessions = get_session_manager()

    @classmethod
    def instance(cls) -> "VoiceRuntime":
        if cls._instance is None:
            cls._instance = VoiceRuntime()
        return cls._instance

    def asr_provider(self, settings: dict[str, Any] | None = None):
        from voice.providers import build_asr_provider

        values = settings or {}
        key = f"{values.get('voice_asr_provider')}:{values.get('voice_asr_model')}:{values.get('voice_asr_device')}:{values.get('voice_asr_compute_type')}"
        with self._lock:
            if self._asr is None or self._asr_key != key:
                self._asr = build_asr_provider(values)
                self._asr_key = key
            return self._asr

    def tts_provider(self, settings: dict[str, Any] | None = None):
        from voice.providers import build_tts_provider

        values = settings or {}
        key = f"{values.get('voice_tts_provider')}:{values.get('voice_tts_voice')}"
        with self._lock:
            if self._tts is None or self._tts_key != key:
                self._tts = build_tts_provider(values)
                self._tts_key = key
            return self._tts

    def wake_detector(self, settings: dict[str, Any] | None = None) -> WakeWordDetector:
        values = settings or {}
        return WakeWordDetector(self.asr_provider(values), enabled=bool(values.get("voice_wake_word_enabled")))
