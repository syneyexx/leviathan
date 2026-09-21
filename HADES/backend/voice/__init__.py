"""HADES local voice subsystem: ASR, TTS, speakable text, and session coordination.

This package provides built-in local speech capabilities. It is separate from:
- ``voice_tasks`` / ``/voice/to-task`` (transcript → task proposal, no ASR)
- ``plugins/local-stt-paste`` (paste-only workflow)
- ``plugins/voicestudio`` (optional external Docker service wrapper)
"""

from __future__ import annotations

__all__ = [
    "VOICE_DATA_DIR",
    "get_voice_runtime",
]

from pathlib import Path

VOICE_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "voice"


def get_voice_runtime():
    from voice.runtime import VoiceRuntime

    return VoiceRuntime.instance()
