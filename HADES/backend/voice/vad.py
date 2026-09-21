"""Server-side energy VAD helpers (browser also runs local VAD)."""

from __future__ import annotations

from dataclasses import dataclass

from voice.audio_utils import rms_level


@dataclass
class VadConfig:
    sensitivity: float = 0.5  # 0..1 higher = more sensitive
    end_silence_ms: int = 900
    min_speech_ms: int = 280
    pre_roll_ms: int = 180
    max_turn_ms: int = 30000


@dataclass
class VadState:
    in_speech: bool = False
    speech_ms: float = 0.0
    silence_ms: float = 0.0
    level: float = 0.0


def threshold_for_sensitivity(sensitivity: float) -> float:
    # Map 0..1 → RMS threshold roughly 0.04..0.006
    s = max(0.0, min(1.0, sensitivity))
    return 0.04 - (0.034 * s)


def update_vad(state: VadState, pcm16: bytes, *, sample_rate: int, config: VadConfig, frame_ms: float) -> tuple[VadState, str | None]:
    """Return updated state and optional edge event: speech_started | speech_ended."""
    level = rms_level(pcm16)
    state.level = level
    thr = threshold_for_sensitivity(config.sensitivity)
    event = None
    if level >= thr:
        state.speech_ms += frame_ms
        state.silence_ms = 0.0
        if not state.in_speech and state.speech_ms >= config.min_speech_ms:
            state.in_speech = True
            event = "speech_started"
    else:
        state.silence_ms += frame_ms
        if state.in_speech and state.silence_ms >= config.end_silence_ms:
            state.in_speech = False
            state.speech_ms = 0.0
            event = "speech_ended"
        elif not state.in_speech:
            state.speech_ms = 0.0
    return state, event
