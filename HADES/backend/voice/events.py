"""Voice session event contracts and ordered audio segment queue."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

VoiceEventType = Literal[
    "session_started",
    "speech_started",
    "transcript_partial",
    "transcript_final",
    "response_started",
    "speech_segment_ready",
    "playback_started",
    "interrupted",
    "session_stopped",
    "status",
    "error",
    "metrics",
    "wake_detected",
]


def new_event_id() -> str:
    return f"vevt_{uuid.uuid4().hex[:16]}"


@dataclass
class VoiceEvent:
    type: VoiceEventType
    session_id: str
    sequence: int
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=new_event_id)
    turn_id: str | None = None
    response_id: str | None = None
    generation: int = 1
    timestamp: float = field(default_factory=lambda: time.time())

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "type": self.type,
            "session_id": self.session_id,
            "sequence": self.sequence,
            "turn_id": self.turn_id,
            "response_id": self.response_id,
            "generation": self.generation,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }


@dataclass
class AudioSegment:
    session_id: str
    turn_id: str
    response_id: str
    order: int
    generation: int
    mime_type: str
    sample_rate: int
    audio_b64: str
    text: str
    cancelled: bool = False


class AudioSegmentQueue:
    """Bounded ordered queue with generation-based cancellation."""

    def __init__(self, maxsize: int = 32):
        self.maxsize = maxsize
        self._items: list[AudioSegment] = []
        self._generation = 1

    @property
    def generation(self) -> int:
        return self._generation

    def bump_generation(self) -> int:
        self._generation += 1
        for item in self._items:
            item.cancelled = True
        self._items.clear()
        return self._generation

    def push(self, segment: AudioSegment) -> bool:
        if segment.generation != self._generation:
            return False
        if len(self._items) >= self.maxsize:
            return False
        self._items.append(segment)
        self._items.sort(key=lambda item: item.order)
        return True

    def pop_ready(self) -> AudioSegment | None:
        while self._items:
            item = self._items.pop(0)
            if not item.cancelled and item.generation == self._generation:
                return item
        return None

    def clear(self) -> None:
        self._items.clear()
