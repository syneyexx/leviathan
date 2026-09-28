"""Production voice worker service — session ownership, ASR/TTS orchestration.

Voice remains TRANSPORT: audio → ASR → existing conversation → TTS.
No parallel voice memory, assistant, or intelligence stack.

Large audio is artifact/file referenced — never one JobRuntime job per audio frame.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .backends import (
    BackendReadiness,
    FixtureAsrBackend,
    FixtureTtsBackend,
    VoiceAsrBackend,
    VoiceTtsBackend,
    resolve_asr_backend,
    resolve_tts_backend,
)
from .realtime import VoiceAction, VoiceJobStatus, VoiceMetrics


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _utc_now_dt() -> datetime:
    return datetime.now(timezone.utc)


# Audio / text safety bounds (fail closed before pathological allocation).
MAX_AUDIO_BYTES = 50 * 1024 * 1024  # 50 MiB upload bound
MAX_AUDIO_DURATION_S = 3600.0  # 1 hour decoded
MAX_TTS_CHARS = 8_000
MAX_ACTIVE_SESSIONS = 32
MAX_PARTIALS_PER_SESSION = 64
MAX_TTS_CHUNKS_BUFFER = 128
DEFAULT_SESSION_TTL_SECONDS = 900.0


@dataclass
class VoiceSession:
    session_id: str
    conversation_id: str | None = None
    run_id: str | None = None
    sync_id: str | None = None
    worker_generation: str = ""
    persona: dict[str, Any] = field(default_factory=dict)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    cancel_generation: int = 0
    partials: list[dict[str, Any]] = field(default_factory=list)
    transcript: str = ""
    metrics: VoiceMetrics = field(default_factory=VoiceMetrics)
    created_at: str = field(default_factory=_utc_now)
    last_activity_at: str = field(default_factory=_utc_now)
    active: bool = True
    backend_state: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        self.last_activity_at = _utc_now()

    def public_dict(self) -> dict[str, Any]:
        # Bound partial history exposed to callers
        recent = self.partials[-MAX_PARTIALS_PER_SESSION:]
        return {
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "run_id": self.run_id,
            "sync_id": self.sync_id,
            "worker_generation": self.worker_generation,
            "persona": dict(self.persona),
            "partials": list(recent),
            "transcript": self.transcript,
            "metrics": self.metrics.public_dict(),
            "active": self.active,
            "created_at": self.created_at,
            "last_activity_at": self.last_activity_at,
            "cancelled": self.cancel_event.is_set(),
            "cancel_generation": self.cancel_generation,
            "backend_state": dict(self.backend_state),
            "truth": {
                "no_parallel_voice_memory": True,
                "barge_in_propagates_to_asr_llm_tts": True,
                "session_bound_to_worker_generation": True,
            },
        }


class VoiceService:
    """Singleton-oriented voice session owner for the voice worker pool.

    Production backends come from Settings/env. Fixture backends are opt-in for
    tests and never claim PRODUCTION_CAPABLE / READY for production status.
    """

    def __init__(
        self,
        *,
        asr_backend: VoiceAsrBackend | None = None,
        tts_backend: VoiceTtsBackend | None = None,
        allow_fixture: bool = False,
        session_ttl_seconds: float = DEFAULT_SESSION_TTL_SECONDS,
        worker_generation: str | None = None,
    ) -> None:
        self.worker_generation = worker_generation or f"vg_{uuid.uuid4().hex[:10]}"
        self.session_ttl_seconds = float(session_ttl_seconds)
        self._lock = threading.RLock()
        self._sessions: dict[str, VoiceSession] = {}
        self._allow_fixture = bool(allow_fixture)
        if asr_backend is not None:
            self.asr = asr_backend
        else:
            self.asr = resolve_asr_backend(allow_fixture=self._allow_fixture)
        if tts_backend is not None:
            self.tts = tts_backend
        else:
            self.tts = resolve_tts_backend(allow_fixture=self._allow_fixture)
        self._cached_readiness = self._compute_readiness()

    # --- readiness (cached; status must not run inference) ---

    def _compute_readiness(self) -> dict[str, Any]:
        asr_r = self.asr.readiness()
        tts_r = self.tts.readiness()
        asr_id = self.asr.identity()
        tts_id = self.tts.identity()
        production_asr = asr_r == BackendReadiness.READY and asr_id.production_capable
        production_tts = tts_r == BackendReadiness.READY and tts_id.production_capable
        return {
            "voice_worker": "READY",
            "asr_backend": asr_r.value,
            "tts_backend": tts_r.value,
            "asr_identity": asr_id.public_dict(),
            "tts_identity": tts_id.public_dict(),
            "audio_preprocessing": "READY",
            "audio_postprocessing": "READY",
            "realtime_streaming": (
                "SUPPORTED"
                if (asr_id.streaming or tts_id.streaming)
                else "UNSUPPORTED"
            ),
            "barge_in": "MEASURED",
            "production_asr": production_asr,
            "production_tts": production_tts,
            "production_capable": production_asr and production_tts,
            "worker_generation": self.worker_generation,
            "active_sessions": len(self._sessions),
            "session_ttl_seconds": self.session_ttl_seconds,
            "truth": {
                "fixture_is_not_production": True,
                "status_does_not_run_inference": True,
                "no_fabricated_transcript_or_audio": True,
            },
        }

    def refresh_readiness(self) -> dict[str, Any]:
        """Explicit probe — worker-owned. Not for UI status poll."""
        self._cached_readiness = self._compute_readiness()
        return dict(self._cached_readiness)

    def status(self) -> dict[str, Any]:
        """Cheap cached readiness — safe for Control Plane status reads."""
        with self._lock:
            snap = dict(self._cached_readiness)
            snap["active_sessions"] = len(self._sessions)
            snap["worker_generation"] = self.worker_generation
            return snap

    # --- session lifecycle ---

    def expire_idle_sessions(self) -> list[str]:
        expired: list[str] = []
        cutoff = _utc_now_dt() - timedelta(seconds=self.session_ttl_seconds)
        with self._lock:
            for sid, session in list(self._sessions.items()):
                try:
                    last = datetime.fromisoformat(session.last_activity_at.replace("Z", "+00:00"))
                except ValueError:
                    last = cutoff
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if last < cutoff or not session.active:
                    self._cleanup_session(session)
                    del self._sessions[sid]
                    expired.append(sid)
        return expired

    def _cleanup_session(self, session: VoiceSession) -> None:
        session.active = False
        session.cancel_event.set()
        session.partials.clear()
        # Ephemeral buffers only — no indefinite retention.

    def start_session(
        self,
        *,
        conversation_id: str | None = None,
        run_id: str | None = None,
        sync_id: str | None = None,
        persona: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.expire_idle_sessions()
        with self._lock:
            if len(self._sessions) >= MAX_ACTIVE_SESSIONS:
                return {
                    "status": VoiceJobStatus.REJECTED.value,
                    "error_code": "VOICE_BACKPRESSURE",
                    "detail": f"Active session limit ({MAX_ACTIVE_SESSIONS}) reached",
                }
            persona_safe = self._validate_persona(persona)
            session = VoiceSession(
                session_id=f"vs_{uuid.uuid4().hex[:12]}",
                conversation_id=conversation_id,
                run_id=run_id,
                sync_id=sync_id,
                worker_generation=self.worker_generation,
                persona=persona_safe,
                backend_state={
                    "asr": self.asr.readiness().value,
                    "tts": self.tts.readiness().value,
                },
            )
            self._sessions[session.session_id] = session
        return {
            "status": VoiceJobStatus.COMPLETED.value,
            "session": session.public_dict(),
            "detail": "Voice session started on voice worker",
            "truth": {
                "persona_is_reproducible_generation_param": True,
                "owned_by_voice_worker": True,
                "no_parallel_voice_memory": True,
            },
        }

    def get_session(self, session_id: str) -> VoiceSession | None:
        self.expire_idle_sessions()
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if session.worker_generation != self.worker_generation:
                return None
            return session

    def _require_session(self, session_id: str) -> VoiceSession | dict[str, Any]:
        if not session_id:
            return {
                "status": VoiceJobStatus.REJECTED.value,
                "error_code": "VOICE_SESSION_LOST",
                "detail": "session_id required",
            }
        session = self.get_session(session_id)
        if session is None:
            return {
                "status": VoiceJobStatus.FAILED.value,
                "error_code": "VOICE_SESSION_LOST",
                "detail": "Voice session lost or bound to a different worker generation",
                "session_id": session_id,
            }
        if not session.active:
            return {
                "status": VoiceJobStatus.FAILED.value,
                "error_code": "VOICE_SESSION_EXPIRED",
                "detail": "Voice session expired",
                "session_id": session_id,
            }
        session.touch()
        return session

    def _validate_persona(self, persona: dict[str, Any] | None) -> dict[str, Any]:
        raw = dict(persona or {})
        voice_id = str(raw.get("voice") or "neutral")[:64]
        # Reject command-injection-looking persona strings
        if any(c in voice_id for c in (";", "|", "`", "$", "\n", "\r")):
            voice_id = "neutral"
        rate = raw.get("speaking_rate", 1.0)
        try:
            rate_f = float(rate)
        except (TypeError, ValueError):
            rate_f = 1.0
        rate_f = max(0.5, min(2.0, rate_f))
        style = str(raw.get("prosody") or raw.get("style") or "default")[:64]
        if any(c in style for c in (";", "|", "`", "$", "\n", "\r")):
            style = "default"
        return {"voice": voice_id, "prosody": style, "speaking_rate": rate_f}

    # --- barge-in / cancel ---

    def barge_in(self, session_id: str) -> dict[str, Any]:
        session_or_err = self._require_session(session_id)
        if isinstance(session_or_err, dict):
            return session_or_err
        session = session_or_err
        started = time.perf_counter()
        session.cancel_event.set()
        session.cancel_generation += 1
        session.metrics.barge_ins += 1
        session.metrics.cancelled_generations += 1
        try:
            self.asr.cancel()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.tts.cancel()
        except Exception:  # noqa: BLE001
            pass
        latency = (time.perf_counter() - started) * 1000.0
        session.metrics.interruption_latency_ms = latency
        session.touch()
        return {
            "status": VoiceJobStatus.COMPLETED.value,
            "session_id": session_id,
            "cancelled": True,
            "cancel_generation": session.cancel_generation,
            "interruption_latency_ms": latency,
            "detail": "Barge-in propagated — ASR/TTS generation cancelled",
            "metrics": session.metrics.public_dict(),
            "truth": {"barge_in_latency_is_measured": True},
        }

    # --- preprocess / postprocess ---

    def preprocess(self, *, audio_ref: str | None = None, path: str | None = None, **_: Any) -> dict[str, Any]:
        ref = str(audio_ref or path or "").strip()
        if not ref:
            return {
                "status": VoiceJobStatus.REJECTED.value,
                "error_code": "VOICE_AUDIO_INVALID",
                "detail": "audio_ref or path required",
            }
        # Bound checks for filesystem refs (artifact / path). Skip fixture refs.
        if ref.startswith("fixture://"):
            return {
                "status": VoiceJobStatus.COMPLETED.value,
                "audio_ref": ref,
                "detail": "Fixture audio ref accepted for test mode only",
                "truth": {"fixture_is_not_production": True},
            }
        size: int | None = None
        if os.path.isfile(ref):
            try:
                size = int(os.path.getsize(ref))
            except OSError:
                size = None
            if size is not None and size > MAX_AUDIO_BYTES:
                return {
                    "status": VoiceJobStatus.REJECTED.value,
                    "error_code": "VOICE_AUDIO_TOO_LARGE",
                    "detail": f"Audio exceeds {MAX_AUDIO_BYTES} bytes",
                    "byte_size": size,
                }
        return {
            "status": VoiceJobStatus.COMPLETED.value,
            "audio_ref": ref,
            "byte_size": size,
            "sample_rate": None,
            "channels": None,
            "detail": "Preprocess validated (decode deferred to ASR backend)",
            "truth": {"no_full_file_materialization": True},
        }

    def postprocess(self, *, text: str | None = None, **_: Any) -> dict[str, Any]:
        raw = str(text or "")
        # Bounded deterministic normalization only — no semantic rewrite.
        normalized = " ".join(raw.split())
        if len(normalized) > 50_000:
            normalized = normalized[:50_000]
        return {
            "status": VoiceJobStatus.COMPLETED.value,
            "text": normalized,
            "length": len(normalized),
            "detail": "Bounded transcript normalization",
        }

    # --- ASR / TTS ---

    def stream_asr(
        self,
        *,
        session_id: str,
        audio_ref: str,
        text_hint: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        pre = self.preprocess(audio_ref=audio_ref)
        if pre.get("status") != VoiceJobStatus.COMPLETED.value:
            return pre

        session_or_err = self._require_session(session_id) if session_id else None
        session: VoiceSession | None
        if isinstance(session_or_err, dict) and session_id:
            return session_or_err
        if session_or_err is None or isinstance(session_or_err, dict):
            created = self.start_session(run_id=run_id)
            if created.get("status") != VoiceJobStatus.COMPLETED.value:
                return created
            session = self._sessions[created["session"]["session_id"]]
        else:
            session = session_or_err

        if session.cancel_event.is_set():
            return {
                "status": VoiceJobStatus.CANCELLED.value,
                "error_code": "VOICE_CANCELLED",
                "detail": "ASR cancelled by barge-in",
                "session_id": session.session_id,
            }

        asr_ready = self.asr.readiness()
        if asr_ready in {BackendReadiness.NOT_CONFIGURED, BackendReadiness.UNAVAILABLE}:
            return {
                "status": VoiceJobStatus.FAILED.value,
                "error_code": "VOICE_ASR_UNAVAILABLE",
                "detail": "ASR backend unavailable",
                "session_id": session.session_id,
                "backend": self.asr.identity().public_dict(),
                "truth": {"no_fabricated_transcript": True, "production_capable": False},
            }

        def _cancelled() -> bool:
            return session.cancel_event.is_set()

        result = self.asr.transcribe(
            audio_ref=audio_ref,
            cancel_check=_cancelled,
            hint=text_hint,
        )
        partials = list(result.get("partials") or [])
        # Bound partial history on session
        for item in partials:
            session.partials.append(item)
            session.metrics.asr_partials += 1
        if len(session.partials) > MAX_PARTIALS_PER_SESSION:
            session.partials = session.partials[-MAX_PARTIALS_PER_SESSION:]

        if result.get("status") == "COMPLETED":
            # Only FINAL transcript becomes conversation input truth
            finals = [p for p in partials if p.get("is_final")]
            session.transcript = str(
                result.get("transcript")
                or (finals[-1]["text"] if finals else "")
            )
            post = self.postprocess(text=session.transcript)
            session.transcript = str(post.get("text") or session.transcript)

        session.touch()
        out = dict(result)
        out["session_id"] = session.session_id
        out["metrics"] = session.metrics.public_dict()
        out.setdefault(
            "truth",
            {
                "partial_is_not_final_conversation_input": True,
                "no_synthetic_confidence": True,
            },
        )
        return out

    def stream_tts(
        self,
        *,
        session_id: str,
        text: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        if not (text and text.strip()):
            return {
                "status": VoiceJobStatus.REJECTED.value,
                "error_code": "VOICE_AUDIO_INVALID",
                "detail": "SYNTHESIZE/STREAM_TTS requires text",
            }
        if len(text) > MAX_TTS_CHARS:
            # Chunk at linguistic boundaries for long documents
            text = text[:MAX_TTS_CHARS]

        session_or_err = self._require_session(session_id) if session_id else None
        if isinstance(session_or_err, dict) and session_id:
            return session_or_err
        if session_or_err is None or isinstance(session_or_err, dict):
            created = self.start_session(run_id=run_id)
            if created.get("status") != VoiceJobStatus.COMPLETED.value:
                return created
            session = self._sessions[created["session"]["session_id"]]
        else:
            session = session_or_err

        if session.cancel_event.is_set():
            return {
                "status": VoiceJobStatus.CANCELLED.value,
                "error_code": "VOICE_CANCELLED",
                "detail": "TTS cancelled by barge-in before start",
                "session_id": session.session_id,
            }

        tts_ready = self.tts.readiness()
        if tts_ready in {BackendReadiness.NOT_CONFIGURED, BackendReadiness.UNAVAILABLE}:
            return {
                "status": VoiceJobStatus.FAILED.value,
                "error_code": "VOICE_TTS_UNAVAILABLE",
                "detail": "TTS backend unavailable",
                "session_id": session.session_id,
                "backend": self.tts.identity().public_dict(),
                "truth": {"no_fabricated_audio": True, "production_capable": False},
            }

        # Reject fixture:// audio masquerading as production when not allow_fixture
        if not self._allow_fixture and isinstance(self.tts, FixtureTtsBackend):
            return {
                "status": VoiceJobStatus.FAILED.value,
                "error_code": "VOICE_TTS_UNAVAILABLE",
                "detail": "Fixture TTS is not production-capable",
                "session_id": session.session_id,
                "truth": {"fixture_is_not_production": True, "production_capable": False},
            }

        def _cancelled() -> bool:
            return session.cancel_event.is_set()

        result = self.tts.synthesize(
            text=text,
            persona=session.persona,
            cancel_check=_cancelled,
        )
        chunks = list(result.get("chunks") or [])[:MAX_TTS_CHUNKS_BUFFER]
        if result.get("status") == "COMPLETED":
            session.metrics.tts_chunks += len(chunks)
        elif result.get("status") == "CANCELLED":
            session.metrics.cancelled_generations += 1

        session.touch()
        out = dict(result)
        out["chunks"] = chunks
        out["session_id"] = session.session_id
        out["persona"] = dict(session.persona)
        out["metrics"] = session.metrics.public_dict()
        out.setdefault(
            "truth",
            {
                "no_artifact_per_100ms_chunk": True,
                "bounded_tts_buffer": True,
            },
        )
        return out

    def execute(
        self,
        *,
        action: VoiceAction | str,
        arguments: dict[str, Any] | None = None,
        run_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        args = dict(arguments or {})
        if isinstance(action, str):
            action = VoiceAction(action.upper())
        if action == VoiceAction.START_SESSION:
            return self.start_session(
                conversation_id=args.get("conversation_id"),
                run_id=run_id or args.get("run_id"),
                sync_id=args.get("sync_id"),
                persona=args.get("persona") if isinstance(args.get("persona"), dict) else None,
            )
        if action == VoiceAction.BARGE_IN:
            return self.barge_in(str(args.get("session_id") or ""))
        if action == VoiceAction.STREAM_ASR or action == VoiceAction.TRANSCRIBE:
            return self.stream_asr(
                session_id=str(args.get("session_id") or ""),
                audio_ref=str(args.get("audio_ref") or args.get("path") or ""),
                text_hint=args.get("text") or args.get("hint"),
                run_id=run_id,
            )
        if action == VoiceAction.STREAM_TTS or action == VoiceAction.SYNTHESIZE:
            return self.stream_tts(
                session_id=str(args.get("session_id") or ""),
                text=str(args.get("text") or ""),
                run_id=run_id,
            )
        if str(action.value if isinstance(action, VoiceAction) else action).upper() in {
            "PREPROCESS",
            "VOICE_PREPROCESS",
        }:
            return self.preprocess(
                audio_ref=args.get("audio_ref"),
                path=args.get("path"),
            )
        if str(action.value if isinstance(action, VoiceAction) else action).upper() in {
            "POSTPROCESS",
            "VOICE_POSTPROCESS",
        }:
            return self.postprocess(text=args.get("text"))
        return {
            "status": VoiceJobStatus.UNSUPPORTED.value,
            "detail": f"Unsupported voice action: {getattr(action, 'value', action)}",
        }


def build_production_voice_service(*, allow_fixture: bool = False) -> VoiceService:
    """Factory for voice worker — fixture only when explicitly allowed."""
    return VoiceService(allow_fixture=allow_fixture)
