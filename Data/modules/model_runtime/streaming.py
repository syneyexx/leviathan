"""Chat SSE helpers + typed stream frame normalization.

Transport only. Does not authorize side-effects or residual authority.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterator, Literal

FrameKind = Literal[
    "delta",
    "snapshot",
    "replace",
    "done",
    "error",
    "meta",
    "reasoning_delta",
    "tool_delta",
]
StreamChannel = Literal["content", "reasoning", "tool", "meta"]


@dataclass
class StreamChannelHonesty:
    """W04 — reasoning/content channel separation honesty."""

    content_frames: int = 0
    reasoning_frames: int = 0
    tool_frames: int = 0
    # separated | partial | unseparated | absent
    reasoning_separation: str = "absent"
    tools_silently_dropped: bool = False

    def note_reasoning_field(self, *, separated: bool) -> None:
        if separated:
            if self.reasoning_separation == "absent":
                self.reasoning_separation = "separated"
            elif self.reasoning_separation == "unseparated":
                self.reasoning_separation = "partial"
        else:
            if self.reasoning_separation == "absent":
                self.reasoning_separation = "unseparated"
            elif self.reasoning_separation == "separated":
                self.reasoning_separation = "partial"

    def public_dict(self) -> dict[str, Any]:
        return {
            "contentFrames": self.content_frames,
            "reasoningFrames": self.reasoning_frames,
            "toolFrames": self.tool_frames,
            "reasoningSeparation": self.reasoning_separation,
            "toolsSilentlyDropped": self.tools_silently_dropped,
            "truth": {
                "reasoning_not_merged_into_content_when_separated": (
                    self.reasoning_separation in {"separated", "absent", "partial"}
                ),
                "partial_separation_is_labeled": self.reasoning_separation != "separated"
                or self.reasoning_frames > 0,
                "tool_deltas_never_silently_dropped": not self.tools_silently_dropped,
            },
        }


@dataclass
class StreamFrame:
    kind: FrameKind
    text: str = ""
    sequence: int = 0
    finish_reason: str | None = None
    termination_source: str | None = None
    model: str | None = None
    request_id: str | None = None
    turn_id: str | None = None
    channel: StreamChannel = "content"
    tool_calls: list[dict[str, Any]] | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "kind": self.kind,
            "text": self.text,
            "sequence": self.sequence,
            "channel": self.channel,
        }
        if self.finish_reason is not None:
            data["finish_reason"] = self.finish_reason
        if self.termination_source is not None:
            data["termination_source"] = self.termination_source
        if self.model is not None:
            data["model"] = self.model
        if self.request_id is not None:
            data["request_id"] = self.request_id
        if self.turn_id is not None:
            data["turn_id"] = self.turn_id
        if self.tool_calls is not None:
            data["tool_calls"] = list(self.tool_calls)
        if self.meta:
            data["meta"] = self.meta
        return data


def _extract_reasoning_text(payload: dict[str, Any]) -> str | None:
    """Return separated reasoning text from delta/message when present."""
    for key in ("reasoning_content", "reasoning", "thinking"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            # OpenAI reasoning object shape: {"content": "..."} / {"summary": ...}
            for sub in ("content", "text", "summary"):
                inner = value.get(sub)
                if isinstance(inner, str) and inner:
                    return inner
    return None


@dataclass
class StreamNormalizer:
    """Normalize provider delta vs cumulative snapshot frames into deltas.

    Rules:
    - choice.delta.content => delta (content channel)
    - choice.delta.reasoning_content / reasoning => reasoning_delta (never merged)
    - choice.delta.tool_calls => tool_delta (never silently dropped)
    - choice.message.content => snapshot (unless proven incremental)
    - cumulative snapshots emit only the new suffix
    - identical snapshots emit nothing
    - diverging snapshots emit replace
    - partial channel separation is labeled honestly
    """

    sequence: int = 0
    _snapshot_prefix: str = ""
    _reasoning_prefix: str = ""
    duplicate_snapshots_suppressed: int = 0
    delta_count: int = 0
    snapshot_count: int = 0
    raw_frame_type_counts: dict[str, int] = field(default_factory=dict)
    channel_honesty: StreamChannelHonesty = field(default_factory=StreamChannelHonesty)

    def next_seq(self) -> int:
        self.sequence += 1
        return self.sequence

    def _count_raw(self, label: str) -> None:
        self.raw_frame_type_counts[label] = self.raw_frame_type_counts.get(label, 0) + 1

    def _emit_reasoning(self, text: str, *, finish_reason: str | None = None) -> StreamFrame:
        self._count_raw("delta.reasoning")
        self.channel_honesty.reasoning_frames += 1
        self.channel_honesty.note_reasoning_field(separated=True)
        self._reasoning_prefix += text
        return StreamFrame(
            kind="reasoning_delta",
            text=text,
            sequence=self.next_seq(),
            finish_reason=finish_reason,
            channel="reasoning",
            meta={"separated": True},
        )

    def _emit_tool_deltas(
        self,
        tool_calls: Any,
        *,
        finish_reason: str | None = None,
    ) -> list[StreamFrame]:
        if not isinstance(tool_calls, list) or not tool_calls:
            return []
        self._count_raw("delta.tool_calls")
        self.channel_honesty.tool_frames += 1
        cleaned = [tc for tc in tool_calls if isinstance(tc, dict)]
        if not cleaned:
            return []
        return [
            StreamFrame(
                kind="tool_delta",
                text="",
                sequence=self.next_seq(),
                finish_reason=finish_reason,
                channel="tool",
                tool_calls=cleaned,
            )
        ]

    def ingest_openai_chunk(self, chunk: dict[str, Any]) -> list[StreamFrame]:
        """Convert one OpenAI-compatible chunk into zero or more StreamFrames."""
        if chunk.get("_done"):
            self._count_raw("done")
            return [
                StreamFrame(
                    kind="done",
                    sequence=self.next_seq(),
                    finish_reason="stop",
                    termination_source="provider_done",
                    channel="meta",
                    meta={"channels": self.channel_honesty.public_dict()},
                )
            ]
        choices = chunk.get("choices")
        if not isinstance(choices, list) or not choices:
            self._count_raw("empty_choices")
            return []
        choice = choices[0]
        if not isinstance(choice, dict):
            return []
        finish = choice.get("finish_reason")
        finish_s = str(finish) if finish else None
        frames: list[StreamFrame] = []

        delta = choice.get("delta")
        if isinstance(delta, dict):
            reasoning = _extract_reasoning_text(delta)
            if reasoning:
                frames.append(self._emit_reasoning(reasoning, finish_reason=finish_s))

            if "tool_calls" in delta:
                frames.extend(
                    self._emit_tool_deltas(delta.get("tool_calls"), finish_reason=finish_s)
                )

            if "content" in delta:
                self._count_raw("delta.content")
                content = delta.get("content")
                if isinstance(content, str) and content:
                    self.delta_count += 1
                    self.channel_honesty.content_frames += 1
                    # Track cumulative for mixed providers that later send snapshots.
                    self._snapshot_prefix += content
                    frames.append(
                        StreamFrame(
                            kind="delta",
                            text=content,
                            sequence=self.next_seq(),
                            finish_reason=finish_s,
                            channel="content",
                        )
                    )
                elif finish_s and not frames:
                    frames.append(
                        StreamFrame(
                            kind="done",
                            sequence=self.next_seq(),
                            finish_reason=finish_s,
                            termination_source="provider_finish_reason",
                            channel="meta",
                            meta={"channels": self.channel_honesty.public_dict()},
                        )
                    )
                return frames

            if frames:
                if finish_s and not any(f.kind == "done" for f in frames):
                    # Reasoning/tool-only chunk with finish — append done.
                    if finish_s in {"stop", "tool_calls", "length", "content_filter"}:
                        frames.append(
                            StreamFrame(
                                kind="done",
                                sequence=self.next_seq(),
                                finish_reason=finish_s,
                                termination_source="provider_finish_reason",
                                channel="meta",
                                meta={"channels": self.channel_honesty.public_dict()},
                            )
                        )
                return frames

            if finish_s:
                self._count_raw("finish_only")
                frames.append(
                    StreamFrame(
                        kind="done",
                        sequence=self.next_seq(),
                        finish_reason=finish_s,
                        termination_source="provider_finish_reason",
                        channel="meta",
                        meta={"channels": self.channel_honesty.public_dict()},
                    )
                )
            return frames

        message = choice.get("message")
        if isinstance(message, dict):
            reasoning = _extract_reasoning_text(message)
            if reasoning:
                frames.append(self._emit_reasoning(reasoning, finish_reason=finish_s))
            if message.get("tool_calls"):
                frames.extend(
                    self._emit_tool_deltas(message.get("tool_calls"), finish_reason=finish_s)
                )
            if isinstance(message.get("content"), str):
                self._count_raw("message.content")
                self.channel_honesty.content_frames += 1
                frames.extend(
                    self.ingest_snapshot(str(message["content"]), finish_reason=finish_s)
                )
                return frames
            if frames:
                return frames

        if finish_s:
            self._count_raw("finish_only")
            frames.append(
                StreamFrame(
                    kind="done",
                    sequence=self.next_seq(),
                    finish_reason=finish_s,
                    termination_source="provider_finish_reason",
                    channel="meta",
                    meta={"channels": self.channel_honesty.public_dict()},
                )
            )
        return frames

    def ingest_snapshot(self, text: str, *, finish_reason: str | None = None) -> list[StreamFrame]:
        """Treat full message text as a cumulative snapshot."""
        self.snapshot_count += 1
        previous = self._snapshot_prefix
        if text == previous:
            self.duplicate_snapshots_suppressed += 1
            if finish_reason:
                return [
                    StreamFrame(
                        kind="done",
                        sequence=self.next_seq(),
                        finish_reason=finish_reason,
                        termination_source="provider_finish_reason",
                    )
                ]
            return []
        if previous and text.startswith(previous):
            suffix = text[len(previous) :]
            self._snapshot_prefix = text
            if not suffix:
                return []
            self.delta_count += 1
            return [
                StreamFrame(
                    kind="delta",
                    text=suffix,
                    sequence=self.next_seq(),
                    finish_reason=finish_reason,
                    meta={"from_snapshot": True},
                )
            ]
        # Diverged or first snapshot
        self._snapshot_prefix = text
        kind: FrameKind = "replace" if previous else "snapshot"
        return [
            StreamFrame(
                kind=kind,
                text=text,
                sequence=self.next_seq(),
                finish_reason=finish_reason,
                meta={"from_snapshot": True, "previous_len": len(previous)},
            )
        ]

    def ingest_delta(self, text: str, *, finish_reason: str | None = None) -> list[StreamFrame]:
        if not text:
            return []
        self._count_raw("synthetic_delta")
        self.delta_count += 1
        self._snapshot_prefix += text
        return [
            StreamFrame(
                kind="delta",
                text=text,
                sequence=self.next_seq(),
                finish_reason=finish_reason,
            )
        ]

    def final_text(self) -> str:
        return self._snapshot_prefix

    def final_reasoning(self) -> str:
        return self._reasoning_prefix

    def stats(self) -> dict[str, Any]:
        return {
            "delta_count": self.delta_count,
            "snapshot_count": self.snapshot_count,
            "duplicate_snapshots_suppressed": self.duplicate_snapshots_suppressed,
            "raw_frame_type_counts": dict(self.raw_frame_type_counts),
            "sequence": self.sequence,
            "channels": self.channel_honesty.public_dict(),
            "reasoning_chars": len(self._reasoning_prefix),
        }


def mark_unseparated_reasoning(normalizer: StreamNormalizer) -> None:
    """Label honesty when a provider only emits mixed content (no reasoning field)."""
    normalizer.channel_honesty.note_reasoning_field(separated=False)


def sse_encode(event: str, data: dict[str, Any] | str) -> str:
    """Encode one SSE event block (ends with blank line)."""
    if isinstance(data, str):
        payload = data
    else:
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("\r\n", "\n").replace("\r", "\n")
    lines = payload.split("\n")
    body = "\n".join(f"data: {line}" for line in lines)
    return f"event: {event}\n{body}\n\n"


def chat_truth(
    *,
    streaming_degraded: bool = False,
    residual_implemented: bool = False,
    residual_applied: bool = False,
) -> dict[str, bool]:
    return {
        "neural_signal_is_not_authority": True,
        "residual_implemented": bool(residual_implemented),
        "residual_applied": bool(residual_applied),
        "discoverable_is_not_authorized": True,
        "unapplied_is_not_success": True,
        "model_output_is_not_evidence": True,
        "unsupported_is_not_failure_of_core": True,
        "streaming_degraded": bool(streaming_degraded),
    }


async def iter_sse(
    events: AsyncIterator[tuple[str, dict[str, Any]]],
) -> AsyncIterator[str]:
    async for event, data in events:
        yield sse_encode(event, data)


def parse_openai_sse_line(line: str) -> dict[str, Any] | None:
    """Parse one OpenAI-compatible SSE data line into a JSON object (or None)."""
    text = line.strip()
    if not text:
        return None
    if text.startswith("data:"):
        text = text[5:].strip()
    if text == "[DONE]":
        return {"_done": True}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def extract_delta_text(chunk: dict[str, Any]) -> str:
    """Extract assistant delta text ONLY from choice.delta.content.

    Non-standard full message.content must go through StreamNormalizer as snapshot.
    Kept for backward-compatible callers; prefer StreamNormalizer.
    """
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    choice = choices[0]
    if not isinstance(choice, dict):
        return ""
    delta = choice.get("delta") or {}
    if isinstance(delta, dict):
        content = delta.get("content")
        if isinstance(content, str):
            return content
    return ""


def extract_message_snapshot(chunk: dict[str, Any]) -> str | None:
    """Return choice.message.content when present (cumulative snapshot candidate)."""
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    choice = choices[0]
    if not isinstance(choice, dict):
        return None
    # Prefer delta when both exist
    delta = choice.get("delta")
    if isinstance(delta, dict) and isinstance(delta.get("content"), str):
        return None
    message = choice.get("message") or {}
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
    return None


def extract_finish_reason(chunk: dict[str, Any]) -> str | None:
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    choice = choices[0]
    if not isinstance(choice, dict):
        return None
    reason = choice.get("finish_reason")
    return str(reason) if reason else None


def sync_chunks_to_text(chunks: Iterator[str]) -> str:
    return "".join(chunks)


def apply_stream_frames(frames: list[StreamFrame]) -> str:
    """Reduce typed frames to final assistant *content* text (not reasoning)."""
    text = ""
    for frame in frames:
        if frame.channel == "reasoning" or frame.kind == "reasoning_delta":
            continue
        if frame.kind == "delta":
            text += frame.text
        elif frame.kind in {"snapshot", "replace"}:
            text = frame.text
    return text


def apply_reasoning_frames(frames: list[StreamFrame]) -> str:
    """Reduce typed frames to final reasoning-channel text only."""
    text = ""
    for frame in frames:
        if frame.kind == "reasoning_delta" or frame.channel == "reasoning":
            text += frame.text
    return text
