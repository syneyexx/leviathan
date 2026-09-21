"""Provider registry and optional stubs for browser/system TTS metadata."""

from __future__ import annotations

from typing import Any

from voice.providers.base import AsrProvider, TtsProvider, VoiceInfo
from voice.providers.faster_whisper_asr import FasterWhisperAsr
from voice.providers.piper_tts import PiperTts
from voice.providers.voicestudio_tts import VoiceStudioTts


class BrowserTtsMeta(TtsProvider):
    """Metadata-only provider: actual synthesis happens in the browser via speechSynthesis.

    Marked offline only when the client reports local voices; server never fakes audio.
    """

    id = "browser"
    label = "Browser / systeemstem (client)"

    def availability(self) -> dict[str, Any]:
        return {
            "ready": False,
            "provider": self.id,
            "status": "client_only",
            "message": "Browser-TTS draait in de client via speechSynthesis. Offline alleen wanneer de browser lokale stemmen heeft.",
            "offline": None,
            "server_synthesis": False,
        }

    def list_voices(self, language: str | None = None) -> list[VoiceInfo]:
        return []

    def synthesize(self, text: str, *, voice_id: str | None = None, language: str | None = None, speed: float = 1.0, cancel_check=None):
        from voice.errors import VoiceProviderError

        raise VoiceProviderError(
            "client_only",
            "Browser-TTS moet in de frontend via speechSynthesis.",
            recovery="Kies Piper of VoiceStudio voor server-side TTS, of gebruik de browserstem in de client.",
        )


def build_asr_provider(settings: dict[str, Any] | None = None) -> AsrProvider:
    values = settings or {}
    return FasterWhisperAsr(
        model_size=str(values.get("voice_asr_model") or "base"),
        device=str(values.get("voice_asr_device") or "auto"),
        compute_type=str(values.get("voice_asr_compute_type") or "auto"),
    )


def resolve_tts_provider_id(settings: dict[str, Any] | None = None) -> str:
    """Canonical TTS selection across voice_* and legacy tts_* keys."""
    values = settings or {}
    voice = str(values.get("voice_tts_provider") or "").lower().strip()
    speech = str(values.get("tts_provider") or "").lower().strip()
    if voice in {"voicestudio", "voice_studio"} or speech in {"voicestudio", "voice_studio"}:
        return "voicestudio"
    if voice == "browser":
        return "browser"
    return "piper"


def build_tts_provider(settings: dict[str, Any] | None = None) -> TtsProvider:
    values = settings or {}
    provider = resolve_tts_provider_id(values)
    if provider == "browser":
        return BrowserTtsMeta()
    if provider == "voicestudio":
        return VoiceStudioTts(values)
    return PiperTts()


def list_provider_summaries(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    asr = build_asr_provider(settings)
    piper = PiperTts()
    browser = BrowserTtsMeta()
    studio = VoiceStudioTts(settings)
    return {
        "asr": [asr.availability()],
        "tts": [piper.availability(), browser.availability(), studio.availability()],
        "selected_tts": resolve_tts_provider_id(settings),
    }
