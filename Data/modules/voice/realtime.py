"""Supervised realtime voice service — fixture ASR/TTS with barge-in (U250–U258).

Uses the shared conversation/run/context model — no parallel voice memory.
Fixture backend: no Whisper/TTS binaries required in CI.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterator


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class VoiceAction(str, Enum):
    TRANSCRIBE = "TRANSCRIBE"
    SYNTHESIZE = "SYNTHESIZE"
    START_SESSION = "START_SESSION"
    BARGE_IN = "BARGE_IN"
    STREAM_ASR = "STREAM_ASR"
    STREAM_TTS = "STREAM_TTS"


class VoiceJobStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class VoiceJob:
    job_id: str
    action: VoiceAction
    status: VoiceJobStatus
    detail: str
    metadata: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "action": self.action.value,
            "status": self.status.value,
            "detail": self.detail,
            "metadata": self.metadata,
            "output": self.output,
            "truth": {
                "no_fabricated_transcripts_or_audio": True,
                "fixture_is_not_whisper_or_tts": True,
                "fixture_is_not_production": True,
                "production_capable": False,
                "uses_shared_conversation_context": True,
            },
        }


@dataclass
class VoiceMetrics:
    asr_partials: int = 0
    barge_ins: int = 0
    cancelled_generations: int = 0
    end_of_speech_to_first_audio_ms: float | None = None
    interruption_latency_ms: float | None = None
    tts_chunks: int = 0

    def public_dict(self) -> dict[str, Any]:
        return {
            "asr_partials": self.asr_partials,
            "barge_ins": self.barge_ins,
            "cancelled_generations": self.cancelled_generations,
            "end_of_speech_to_first_audio_ms": self.end_of_speech_to_first_audio_ms,
            "interruption_latency_ms": self.interruption_latency_ms,
            "tts_chunks": self.tts_chunks,
            "truth": {
                "measured_when_fixture_instrumented": True,
                "fixture_timestamps_are_not_production_metrics": True,
                "asr_error_requires_eval_harness": True,
                "production_capable": False,
            },
        }


@dataclass
class RealtimeVoiceSession:
    session_id: str
    conversation_id: str | None = None
    run_id: str | None = None
    sync_id: str | None = None
    persona: dict[str, Any] = field(default_factory=dict)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    partials: list[dict[str, Any]] = field(default_factory=list)
    transcript: str = ""
    metrics: VoiceMetrics = field(default_factory=VoiceMetrics)
    created_at: str = field(default_factory=_utc_now)
    active: bool = True

    def public_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "run_id": self.run_id,
            "sync_id": self.sync_id,
            "persona": dict(self.persona),
            "partials": list(self.partials),
            "transcript": self.transcript,
            "metrics": self.metrics.public_dict(),
            "active": self.active,
            "created_at": self.created_at,
            "cancelled": self.cancel_event.is_set(),
            "truth": {
                "no_parallel_voice_memory": True,
                "barge_in_propagates_to_asr_llm_tts": True,
            },
        }


class RealtimeVoiceService:
    """Fixture realtime audio service — barge-in cancels in-flight generation."""

    def __init__(self) -> None:
        self._sessions: dict[str, RealtimeVoiceSession] = {}

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
                audio_ref=str(args.get("audio_ref") or args.get("path") or "fixture-audio"),
                text_hint=args.get("text") or args.get("hint"),
                run_id=run_id,
            )
        if action == VoiceAction.STREAM_TTS or action == VoiceAction.SYNTHESIZE:
            return self.stream_tts(
                session_id=str(args.get("session_id") or ""),
                text=str(args.get("text") or ""),
                run_id=run_id,
            )
        return {
            "status": VoiceJobStatus.UNSUPPORTED.value,
            "detail": f"Unsupported voice action: {action.value}",
        }

    def request(self, *, action: VoiceAction, text: str | None = None) -> VoiceJob:
        result = self.execute(action=action, arguments={"text": text} if text else {})
        status = VoiceJobStatus(result.get("status", "FAILED"))
        return VoiceJob(
            job_id=str(uuid.uuid4()),
            action=action,
            status=status,
            detail=str(result.get("detail") or result.get("error") or ""),
            metadata={"backend": "fixture"},
            output=result if status == VoiceJobStatus.COMPLETED else None,
        )

    def start_session(
        self,
        *,
        conversation_id: str | None = None,
        run_id: str | None = None,
        sync_id: str | None = None,
        persona: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = RealtimeVoiceSession(
            session_id=f"vs_{uuid.uuid4().hex[:12]}",
            conversation_id=conversation_id,
            run_id=run_id,
            sync_id=sync_id,
            persona={
                "voice": (persona or {}).get("voice", "neutral"),
                "prosody": (persona or {}).get("prosody", "default"),
                "speaking_rate": (persona or {}).get("speaking_rate", 1.0),
            },
        )
        self._sessions[session.session_id] = session
        return {
            "status": VoiceJobStatus.COMPLETED.value,
            "session": session.public_dict(),
            "detail": "Realtime voice session started (fixture)",
            "truth": {"persona_is_reproducible_generation_param": True},
        }

    def get_session(self, session_id: str) -> RealtimeVoiceSession | None:
        return self._sessions.get(session_id)

    def barge_in(self, session_id: str) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None:
            return {
                "status": VoiceJobStatus.REJECTED.value,
                "error": "Unknown voice session",
            }
        started = time.perf_counter()
        session.cancel_event.set()
        session.metrics.barge_ins += 1
        session.metrics.cancelled_generations += 1
        latency = (time.perf_counter() - started) * 1000
        session.metrics.interruption_latency_ms = latency
        return {
            "status": VoiceJobStatus.COMPLETED.value,
            "session_id": session_id,
            "cancelled": True,
            "interruption_latency_ms": latency,
            "detail": "Barge-in propagated — ASR/LLM/TTS generation cancelled",
            "metrics": session.metrics.public_dict(),
        }

    def stream_asr(
        self,
        *,
        session_id: str,
        audio_ref: str,
        text_hint: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        session = self._ensure_session(session_id, run_id=run_id)
        if session.cancel_event.is_set():
            return {
                "status": VoiceJobStatus.CANCELLED.value,
                "detail": "ASR cancelled by barge-in",
                "session_id": session.session_id,
            }
        # Fixture partials — deterministic chunks from hint or audio_ref.
        base = (text_hint or f"transcript for {audio_ref}").strip()
        words = base.split() or ["…"]
        partials: list[dict[str, Any]] = []
        acc = []
        for i, word in enumerate(words):
            if session.cancel_event.is_set():
                return {
                    "status": VoiceJobStatus.CANCELLED.value,
                    "partials": partials,
                    "detail": "ASR interrupted",
                    "session_id": session.session_id,
                    "metrics": session.metrics.public_dict(),
                }
            acc.append(word)
            piece = " ".join(acc)
            item = {
                "index": i,
                "text": piece,
                "is_final": i == len(words) - 1,
                "t_ms": i * 120,
                "t_ms_is_synthetic": True,
                "vad": "speech" if i < len(words) - 1 else "end_of_speech",
            }
            partials.append(item)
            session.partials.append(item)
            session.metrics.asr_partials += 1
        session.transcript = base
        return {
            "status": VoiceJobStatus.COMPLETED.value,
            "session_id": session.session_id,
            "partials": partials,
            "transcript": base,
            "diarization": [
                {
                    "speaker": "spk0",
                    "start_ms": 0,
                    "end_ms": max(120, len(words) * 120),
                    "timestamps_are_synthetic": True,
                }
            ],
            "backend": "fixture",
            "detail": "Fixture streaming ASR partials + VAD",
            "metrics": session.metrics.public_dict(),
            "truth": {
                "diarization_only_when_provider_supports": True,
                "fixture_is_not_production": True,
                "production_capable": False,
                "synthetic_latency_not_production_metric": True,
            },
        }

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
                "error": "SYNTHESIZE/STREAM_TTS requires text",
            }
        session = self._ensure_session(session_id, run_id=run_id)
        if session.cancel_event.is_set():
            return {
                "status": VoiceJobStatus.CANCELLED.value,
                "detail": "TTS cancelled by barge-in before start",
                "session_id": session.session_id,
            }
        # Fixture path: do NOT invent a constant production-looking latency.
        # Real backends must measure with perf_counter; here latency stays None/synthetic.
        started = time.perf_counter()
        chunks: list[dict[str, Any]] = []
        words = text.strip().split()
        for i, word in enumerate(words):
            if session.cancel_event.is_set():
                session.metrics.cancelled_generations += 1
                return {
                    "status": VoiceJobStatus.CANCELLED.value,
                    "chunks": chunks,
                    "detail": "TTS interrupted by barge-in",
                    "session_id": session.session_id,
                    "metrics": session.metrics.public_dict(),
                }
            chunks.append(
                {
                    "index": i,
                    "text": word,
                    "audio_ref": f"fixture://tts/{session.session_id}/{i}",
                    "persona": dict(session.persona),
                    "t_ms_synthetic": i * 120,
                }
            )
            session.metrics.tts_chunks += 1
        # Record wall time of the fixture loop only — labeled synthetic, not production TTS latency.
        synthetic_ms = (time.perf_counter() - started) * 1000.0
        session.metrics.end_of_speech_to_first_audio_ms = None
        return {
            "status": VoiceJobStatus.COMPLETED.value,
            "session_id": session.session_id,
            "chunks": chunks,
            "end_of_speech_to_first_audio_ms": None,
            "fixture_loop_ms": synthetic_ms,
            "persona": dict(session.persona),
            "backend": "fixture",
            "detail": "Fixture streaming TTS",
            "metrics": session.metrics.public_dict(),
            "truth": {
                "fixture_is_not_production": True,
                "production_capable": False,
                "synthetic_latency_not_production_metric": True,
            },
        }

    def iter_tts_chunks(
        self, session_id: str, text: str
    ) -> Iterator[dict[str, Any]]:
        result = self.stream_tts(session_id=session_id, text=text)
        for chunk in result.get("chunks") or []:
            yield chunk

    def _ensure_session(self, session_id: str, *, run_id: str | None) -> RealtimeVoiceSession:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        created = self.start_session(run_id=run_id)
        sid = created["session"]["session_id"]
        return self._sessions[sid]


class VoiceRuntimeStub:
    """Honest stub — voice/ASR/TTS not implemented (feature-off path)."""

    def request(self, *, action: VoiceAction, text: str | None = None) -> VoiceJob:
        if action == VoiceAction.SYNTHESIZE and not (text and text.strip()):
            return VoiceJob(
                job_id=str(uuid.uuid4()),
                action=action,
                status=VoiceJobStatus.REJECTED,
                detail="SYNTHESIZE requires text",
            )
        return VoiceJob(
            job_id=str(uuid.uuid4()),
            action=action,
            status=VoiceJobStatus.UNSUPPORTED,
            detail="Voice runtime is not implemented",
            metadata={"implemented": False},
        )
