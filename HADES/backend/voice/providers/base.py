"""Provider interfaces for local ASR and TTS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from voice.errors import VoiceProviderError

__all__ = [
    "VoiceProviderError",
    "TranscriptResult",
    "VoiceInfo",
    "SynthesisResult",
    "AsrProvider",
    "TtsProvider",
    "DevicePreference",
]


@dataclass
class TranscriptResult:
    text: str
    language: str | None = None
    is_partial: bool = False
    # Only set when the provider actually reports confidence; never invent a percentage.
    confidence: float | None = None
    duration_seconds: float | None = None
    provider: str = ""
    model: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class VoiceInfo:
    id: str
    name: str
    language: str
    gender: str | None = None
    sample_rate: int = 22050
    offline: bool = True
    provider: str = ""
    path: str | None = None


@dataclass
class SynthesisResult:
    audio: bytes
    mime_type: str
    sample_rate: int
    voice_id: str
    provider: str
    duration_seconds: float | None = None
    speakable_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class AsrProvider(ABC):
    id: str
    label: str

    @abstractmethod
    def availability(self) -> dict[str, Any]:
        """Return ready/missing/error status without loading large models unless already loaded."""

    @abstractmethod
    def supported_languages(self) -> list[str]:
        ...

    @abstractmethod
    def model_status(self) -> dict[str, Any]:
        ...

    @abstractmethod
    def transcribe(
        self,
        audio: bytes,
        *,
        language: str | None = None,
        mime_type: str = "audio/wav",
        cancel_check: Any | None = None,
    ) -> TranscriptResult:
        ...

    def cancel(self) -> None:
        """Best-effort cancel of in-flight transcription."""

    def unload(self) -> None:
        """Release loaded models."""


class TtsProvider(ABC):
    id: str
    label: str

    @abstractmethod
    def availability(self) -> dict[str, Any]:
        ...

    @abstractmethod
    def list_voices(self, language: str | None = None) -> list[VoiceInfo]:
        ...

    @abstractmethod
    def synthesize(
        self,
        text: str,
        *,
        voice_id: str | None = None,
        language: str | None = None,
        speed: float = 1.0,
        cancel_check: Any | None = None,
    ) -> SynthesisResult:
        ...

    def cancel(self) -> None:
        ...

    def unload(self) -> None:
        ...


DevicePreference = Literal["cpu", "cuda", "auto"]
