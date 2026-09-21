"""Local speech (TTS/STT) integration for HADES.

VoiceStudio is an optional swappable local provider. Chat remains usable when
the service is unavailable — HADES never silently falls back to cloud TTS.
"""

from speech.runtime import SpeechRuntime, get_speech_runtime
from speech.speakable import prepare_speakable_text, split_speakable_chunks

__all__ = [
    "SpeechRuntime",
    "get_speech_runtime",
    "prepare_speakable_text",
    "split_speakable_chunks",
]
