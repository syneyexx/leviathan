"""Voice as transport — ASR/TTS into Chat/CognitiveRuntime (W21).

Voice does NOT own intelligence. Duplicate conversation memory is forbidden.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class VoiceCapabilityStatus:
    asr: str  # MEASURED | UNAVAILABLE | NOT_CONFIGURED | FEATURE_GATED
    tts: str
    detail: str = ""
    barge_in: bool = False
    partial_transcripts: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "asr": self.asr,
            "tts": self.tts,
            "detail": self.detail,
            "barge_in": self.barge_in,
            "partial_transcripts": self.partial_transcripts,
            "truth": {
                "voice_is_transport": True,
                "does_not_own_intelligence": True,
                "no_duplicate_conversation_memory": True,
            },
        }


def probe_voice_capabilities(*, asr_ready: bool | None = None, tts_ready: bool | None = None) -> VoiceCapabilityStatus:
    def _st(flag: bool | None) -> str:
        if flag is True:
            return "MEASURED"
        if flag is False:
            return "UNAVAILABLE"
        return "NOT_CONFIGURED"

    return VoiceCapabilityStatus(
        asr=_st(asr_ready),
        tts=_st(tts_ready),
        detail="voice adapters report honest availability",
        barge_in=False,
        partial_transcripts=bool(asr_ready),
    )


@dataclass
class VoiceTurnBridge:
    """Maps audio turn → existing conversation_id (no second memory)."""

    conversation_id: str
    transcript_partial: str = ""
    transcript_final: str = ""
    latency_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "transcript_partial": self.transcript_partial,
            "transcript_final": self.transcript_final,
            "latency_ms": self.latency_ms,
            "metadata": dict(self.metadata),
            "truth": {
                "routes_to_chat_cognitive_runtime": True,
                "no_second_assistant": True,
            },
        }
