"""Optional local wake-word detection for 'Hades' via short ASR windows.

Default OFF. Uses the same local faster-whisper route — not a disconnected adapter.
"""

from __future__ import annotations

import re
from typing import Any, TYPE_CHECKING

from voice.errors import VoiceProviderError

if TYPE_CHECKING:
    from voice.providers.base import AsrProvider

WAKE_PATTERNS = (
    re.compile(r"\bhey\s+hades\b", re.I),
    re.compile(r"\bok(?:ay)?\s+hades\b", re.I),
    re.compile(r"\bhades\b", re.I),
)


class WakeWordDetector:
    def __init__(self, asr: "AsrProvider", *, enabled: bool = False):
        self.asr = asr
        self.enabled = enabled
        self._last_hit_at = 0.0

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def process_audio(self, audio: bytes, *, mime_type: str = "audio/wav", language: str = "nl") -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "detected": False}
        try:
            result = self.asr.transcribe(audio, language=language, mime_type=mime_type)
        except VoiceProviderError as exc:
            return {"enabled": True, "detected": False, "error": exc.to_dict()}
        text = (result.text or "").strip()
        detected = bool(text) and any(pat.search(text) for pat in WAKE_PATTERNS)
        remainder = ""
        if detected:
            remainder = text
            for pat in WAKE_PATTERNS:
                remainder = pat.sub(" ", remainder, count=1)
            remainder = re.sub(r"\s+", " ", remainder).strip(" .,!?;:")
        return {
            "enabled": True,
            "detected": detected,
            "text": text,
            "remainder": remainder,
            "language": result.language,
        }
