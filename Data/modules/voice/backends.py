"""Production voice ASR/TTS backend abstractions.

Fixtures are test/dev only — they must never report PRODUCTION_CAPABLE / READY
for production ASR/TTS readiness. Missing real backends report UNAVAILABLE /
NOT_CONFIGURED honestly.
"""

from __future__ import annotations

import abc
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterator


class BackendReadiness(str, Enum):
    READY = "READY"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    FIXTURE_ONLY = "FIXTURE_ONLY"


class ResourceRequirement(str, Enum):
    CPU_LIGHT = "CPU_LIGHT"
    CPU_HEAVY = "CPU_HEAVY"
    MEMORY_HEAVY = "MEMORY_HEAVY"
    MODEL_INFERENCE = "MODEL_INFERENCE"


@dataclass(frozen=True)
class BackendIdentity:
    backend_id: str
    kind: str  # asr | tts
    version: str | None = None
    streaming: bool = False
    formats: tuple[str, ...] = ()
    sample_rates: tuple[int, ...] = ()
    resource_requirements: tuple[str, ...] = (ResourceRequirement.CPU_LIGHT.value,)
    production_capable: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "backend_id": self.backend_id,
            "kind": self.kind,
            "version": self.version,
            "streaming": self.streaming,
            "formats": list(self.formats),
            "sample_rates": list(self.sample_rates),
            "resource_requirements": list(self.resource_requirements),
            "production_capable": self.production_capable,
        }


@dataclass
class AsrPartial:
    sequence: int
    text: str
    is_final: bool
    start_ms: float | None = None
    end_ms: float | None = None
    confidence: float | None = None
    backend: str = ""
    timestamp: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "text": self.text,
            "is_final": self.is_final,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "confidence": self.confidence,
            "backend": self.backend,
            "timestamp": self.timestamp,
            "metadata": dict(self.metadata),
        }


@dataclass
class TtsChunk:
    sequence: int
    audio_ref: str | None = None
    audio_bytes: bytes | None = None
    text: str = ""
    duration_ms: float | None = None
    backend: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "audio_ref": self.audio_ref,
            "text": self.text,
            "duration_ms": self.duration_ms,
            "backend": self.backend,
            "byte_size": len(self.audio_bytes) if self.audio_bytes else 0,
            "metadata": dict(self.metadata),
        }


class VoiceAsrBackend(abc.ABC):
    """Canonical ASR backend interface — HTTP routes must not know implementations."""

    @abc.abstractmethod
    def identity(self) -> BackendIdentity: ...

    @abc.abstractmethod
    def readiness(self) -> BackendReadiness: ...

    @abc.abstractmethod
    def transcribe(
        self,
        *,
        audio_ref: str,
        cancel_check: Any | None = None,
        hint: str | None = None,
    ) -> dict[str, Any]:
        """Return final transcript + bounded partials. Never fabricate production output."""
        ...

    def supports_streaming(self) -> bool:
        return self.identity().streaming

    def cancel(self) -> None:
        """Best-effort cancel in-flight request."""


class VoiceTtsBackend(abc.ABC):
    """Canonical TTS backend interface."""

    @abc.abstractmethod
    def identity(self) -> BackendIdentity: ...

    @abc.abstractmethod
    def readiness(self) -> BackendReadiness: ...

    @abc.abstractmethod
    def synthesize(
        self,
        *,
        text: str,
        persona: dict[str, Any] | None = None,
        cancel_check: Any | None = None,
    ) -> dict[str, Any]:
        """Return audio chunks/refs. Never emit fixture:// in production mode."""
        ...

    def supports_streaming(self) -> bool:
        return self.identity().streaming

    def cancel(self) -> None:
        """Best-effort cancel in-flight request."""


class UnavailableAsrBackend(VoiceAsrBackend):
    """Production default when no real ASR backend is configured."""

    def __init__(self, *, reason: str = "ASR backend not configured") -> None:
        self._reason = reason

    def identity(self) -> BackendIdentity:
        return BackendIdentity(
            backend_id="asr.unavailable",
            kind="asr",
            version=None,
            streaming=False,
            production_capable=False,
        )

    def readiness(self) -> BackendReadiness:
        return BackendReadiness.NOT_CONFIGURED

    def transcribe(
        self,
        *,
        audio_ref: str,
        cancel_check: Any | None = None,
        hint: str | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "FAILED",
            "error_code": "VOICE_ASR_UNAVAILABLE",
            "detail": self._reason,
            "backend": self.identity().public_dict(),
            "truth": {
                "no_fabricated_transcript": True,
                "production_capable": False,
            },
        }


class UnavailableTtsBackend(VoiceTtsBackend):
    """Production default when no real TTS backend is configured."""

    def __init__(self, *, reason: str = "TTS backend not configured") -> None:
        self._reason = reason

    def identity(self) -> BackendIdentity:
        return BackendIdentity(
            backend_id="tts.unavailable",
            kind="tts",
            version=None,
            streaming=False,
            production_capable=False,
        )

    def readiness(self) -> BackendReadiness:
        return BackendReadiness.NOT_CONFIGURED

    def synthesize(
        self,
        *,
        text: str,
        persona: dict[str, Any] | None = None,
        cancel_check: Any | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "FAILED",
            "error_code": "VOICE_TTS_UNAVAILABLE",
            "detail": self._reason,
            "backend": self.identity().public_dict(),
            "truth": {
                "no_fabricated_audio": True,
                "production_capable": False,
            },
        }


class FixtureAsrBackend(VoiceAsrBackend):
    """Deterministic fixture ASR — TEST/DEV ONLY. Never production READY."""

    def identity(self) -> BackendIdentity:
        return BackendIdentity(
            backend_id="asr.fixture",
            kind="asr",
            version="fixture-1",
            streaming=True,
            formats=("text/hint",),
            sample_rates=(),
            production_capable=False,
        )

    def readiness(self) -> BackendReadiness:
        return BackendReadiness.FIXTURE_ONLY

    def transcribe(
        self,
        *,
        audio_ref: str,
        cancel_check: Any | None = None,
        hint: str | None = None,
    ) -> dict[str, Any]:
        base = (hint or f"transcript for {audio_ref}").strip()
        words = base.split() or ["…"]
        partials: list[dict[str, Any]] = []
        acc: list[str] = []
        for i, word in enumerate(words):
            if cancel_check is not None and cancel_check():
                return {
                    "status": "CANCELLED",
                    "error_code": "VOICE_CANCELLED",
                    "partials": partials,
                    "backend": "fixture",
                    "truth": {"fixture_is_not_production": True, "production_capable": False},
                }
            acc.append(word)
            partials.append(
                AsrPartial(
                    sequence=i,
                    text=" ".join(acc),
                    is_final=i == len(words) - 1,
                    start_ms=float(i * 120),
                    end_ms=float((i + 1) * 120),
                    confidence=None,  # never synthetic confidence
                    backend="fixture",
                    metadata={"t_ms_is_synthetic": True, "vad": "speech" if i < len(words) - 1 else "end_of_speech"},
                ).public_dict()
            )
        return {
            "status": "COMPLETED",
            "partials": partials,
            "transcript": base,
            "diarization": None,  # UNMEASURED — fixture speaker labels stay test-only
            "diarization_status": "UNMEASURED",
            "backend": "fixture",
            "truth": {
                "fixture_is_not_production": True,
                "production_capable": False,
                "no_synthetic_confidence": True,
                "diarization_only_when_measured": True,
            },
        }


class FixtureTtsBackend(VoiceTtsBackend):
    """Deterministic fixture TTS — TEST/DEV ONLY. Never production READY."""

    def identity(self) -> BackendIdentity:
        return BackendIdentity(
            backend_id="tts.fixture",
            kind="tts",
            version="fixture-1",
            streaming=True,
            formats=("fixture://",),
            sample_rates=(),
            production_capable=False,
        )

    def readiness(self) -> BackendReadiness:
        return BackendReadiness.FIXTURE_ONLY

    def synthesize(
        self,
        *,
        text: str,
        persona: dict[str, Any] | None = None,
        cancel_check: Any | None = None,
    ) -> dict[str, Any]:
        if not (text and text.strip()):
            return {
                "status": "REJECTED",
                "error_code": "VOICE_AUDIO_INVALID",
                "detail": "SYNTHESIZE requires text",
            }
        words = text.strip().split()
        chunks: list[dict[str, Any]] = []
        for i, word in enumerate(words):
            if cancel_check is not None and cancel_check():
                return {
                    "status": "CANCELLED",
                    "error_code": "VOICE_CANCELLED",
                    "chunks": chunks,
                    "backend": "fixture",
                    "truth": {"fixture_is_not_production": True, "production_capable": False},
                }
            chunks.append(
                TtsChunk(
                    sequence=i,
                    audio_ref=f"fixture://tts/{i}",
                    text=word,
                    duration_ms=None,  # not a measured production duration
                    backend="fixture",
                    metadata={"t_ms_synthetic": i * 120, "persona": dict(persona or {})},
                ).public_dict()
            )
        return {
            "status": "COMPLETED",
            "chunks": chunks,
            "backend": "fixture",
            "end_of_speech_to_first_audio_ms": None,
            "truth": {
                "fixture_is_not_production": True,
                "production_capable": False,
                "synthetic_latency_not_production_metric": True,
            },
        }


class LocalExecutableAsrBackend(VoiceAsrBackend):
    """Optional local ASR via explicitly configured executable (no auto-install)."""

    def __init__(self, *, executable: str, version: str | None = None) -> None:
        self._executable = executable
        self._version = version

    def identity(self) -> BackendIdentity:
        return BackendIdentity(
            backend_id="asr.local_executable",
            kind="asr",
            version=self._version,
            streaming=False,
            formats=("wav", "pcm", "flac"),
            sample_rates=(16000, 22050, 44100, 48000),
            resource_requirements=(
                ResourceRequirement.CPU_HEAVY.value,
                ResourceRequirement.MODEL_INFERENCE.value,
            ),
            production_capable=True,
        )

    def readiness(self) -> BackendReadiness:
        if not self._executable:
            return BackendReadiness.NOT_CONFIGURED
        if not os.path.isfile(self._executable) and not _which(self._executable):
            return BackendReadiness.UNAVAILABLE
        return BackendReadiness.READY

    def transcribe(
        self,
        *,
        audio_ref: str,
        cancel_check: Any | None = None,
        hint: str | None = None,
    ) -> dict[str, Any]:
        # Real local ASR subprocess invocation is intentionally not auto-wired —
        # Settings must provide a verified adapter. Fail closed when invoked without one.
        return {
            "status": "FAILED",
            "error_code": "VOICE_ASR_UNAVAILABLE",
            "detail": (
                f"Local ASR executable configured ({self._executable}) but "
                "subprocess adapter is not production-verified in this build"
            ),
            "backend": self.identity().public_dict(),
            "truth": {"no_fabricated_transcript": True, "no_auto_install": True},
        }


class LocalExecutableTtsBackend(VoiceTtsBackend):
    """Optional local TTS via explicitly configured executable (no auto-install)."""

    def __init__(self, *, executable: str, version: str | None = None) -> None:
        self._executable = executable
        self._version = version

    def identity(self) -> BackendIdentity:
        return BackendIdentity(
            backend_id="tts.local_executable",
            kind="tts",
            version=self._version,
            streaming=False,
            formats=("wav", "pcm"),
            sample_rates=(22050, 24000, 44100),
            resource_requirements=(
                ResourceRequirement.CPU_HEAVY.value,
                ResourceRequirement.MODEL_INFERENCE.value,
            ),
            production_capable=True,
        )

    def readiness(self) -> BackendReadiness:
        if not self._executable:
            return BackendReadiness.NOT_CONFIGURED
        if not os.path.isfile(self._executable) and not _which(self._executable):
            return BackendReadiness.UNAVAILABLE
        return BackendReadiness.READY

    def synthesize(
        self,
        *,
        text: str,
        persona: dict[str, Any] | None = None,
        cancel_check: Any | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "FAILED",
            "error_code": "VOICE_TTS_UNAVAILABLE",
            "detail": (
                f"Local TTS executable configured ({self._executable}) but "
                "subprocess adapter is not production-verified in this build"
            ),
            "backend": self.identity().public_dict(),
            "truth": {"no_fabricated_audio": True, "no_auto_install": True},
        }


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)


def resolve_asr_backend(
    *,
    allow_fixture: bool = False,
    executable: str | None = None,
) -> VoiceAsrBackend:
    """Resolve ASR backend from settings. Fixture only when explicitly allowed."""
    exe = (executable or os.environ.get("LEVIATHAN_VOICE_ASR_EXECUTABLE") or "").strip()
    if exe:
        return LocalExecutableAsrBackend(executable=exe)
    if allow_fixture or os.environ.get("LEVIATHAN_VOICE_ALLOW_FIXTURE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        # Explicit fixture mode for CI/unit tests — readiness stays FIXTURE_ONLY.
        return FixtureAsrBackend()
    return UnavailableAsrBackend()


def resolve_tts_backend(
    *,
    allow_fixture: bool = False,
    executable: str | None = None,
) -> VoiceTtsBackend:
    exe = (executable or os.environ.get("LEVIATHAN_VOICE_TTS_EXECUTABLE") or "").strip()
    if exe:
        return LocalExecutableTtsBackend(executable=exe)
    if allow_fixture or os.environ.get("LEVIATHAN_VOICE_ALLOW_FIXTURE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return FixtureTtsBackend()
    return UnavailableTtsBackend()
