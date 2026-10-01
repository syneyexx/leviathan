"""Public cognition output sink — streams operational + public tokens without private CoT."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterator


PUBLIC_COGNITION_EVENT_TYPES = frozenset(
    {
        "execution.started",
        "retrieval.started",
        "retrieval.completed",
        "agents.delegated",
        "tool.started",
        "tool.progress",
        "tool.completed",
        "tool.failed",
        "verification.started",
        "verification.completed",
        "model.output",
        "status.terminal",
    }
)


@dataclass
class CognitionPublicEvent:
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {"event_type": self.event_type, "payload": dict(self.payload)}


class CognitionPublicSink:
    """Collects allowlisted public events during CognitiveRuntime execution.

    Private reasoning / chain-of-thought must never be appended here.
    """

    def __init__(self, on_event: Callable[[CognitionPublicEvent], None] | None = None) -> None:
        self._events: list[CognitionPublicEvent] = []
        self._on_event = on_event
        self._token_buffer: list[str] = []

    def emit(self, event_type: str, **payload: Any) -> None:
        if event_type not in PUBLIC_COGNITION_EVENT_TYPES and not event_type.startswith("tool."):
            # Unknown types are dropped unless they are clearly public operational.
            if event_type not in {
                "job.started",
                "job.progress",
                "job.completed",
                "capability.discovered",
                "module.starting",
                "module.ready",
                "artifact.created",
                "source.observed",
            }:
                return
        event = CognitionPublicEvent(event_type=event_type, payload=payload)
        self._events.append(event)
        if self._on_event is not None:
            self._on_event(event)

    def append_public_token(self, text: str) -> None:
        if not text:
            return
        self._token_buffer.append(text)
        self.emit("model.output", text=text, kind="token")

    def drain_tokens(self) -> str:
        text = "".join(self._token_buffer)
        self._token_buffer.clear()
        return text

    def events(self) -> list[dict[str, Any]]:
        return [e.public_dict() for e in self._events]

    def iter_sse_payloads(self) -> Iterator[tuple[str, dict[str, Any]]]:
        for event in self._events:
            et = event.event_type
            if et == "model.output":
                yield "token", {"text": event.payload.get("text") or "", "kind": "cognition"}
            elif et.startswith("tool.") or et.startswith("job.") or et.startswith("capability."):
                yield et, dict(event.payload)
            elif et.startswith("retrieval.") or et.startswith("verification.") or et.startswith("agents."):
                yield "activity", {"phase": et, **event.payload}
            elif et == "status.terminal":
                yield "snapshot", dict(event.payload)
            else:
                yield "activity", {"phase": et, **event.payload}


def map_cognition_events_to_public_sink(
    raw_events: list[dict[str, Any]] | None,
    sink: CognitionPublicSink,
) -> None:
    """Project existing cognition operational events into the public sink."""
    for ev in raw_events or []:
        if not isinstance(ev, dict):
            continue
        et = str(ev.get("event_type") or "")
        payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
        if et in {
            "tool.started",
            "tool.progress",
            "tool.completed",
            "tool.failed",
            "job.started",
            "job.progress",
            "job.completed",
            "capability.discovered",
            "module.starting",
            "module.ready",
            "artifact.created",
            "source.observed",
        }:
            sink.emit(et, **payload)
        elif et in {"retrieval.started", "retrieval.completed"}:
            sink.emit(et, **payload)
        elif et in {"verification.started", "verification.completed"}:
            sink.emit(et, **payload)
