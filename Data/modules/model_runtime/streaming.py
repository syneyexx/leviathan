"""Chat SSE helpers — Server-Sent Events framing for /api/chat streaming.

Transport only. Does not authorize side-effects or residual authority.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Iterator


def sse_encode(event: str, data: dict[str, Any] | str) -> str:
    """Encode one SSE event block (ends with blank line)."""
    if isinstance(data, str):
        payload = data
    else:
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # SSE forbids raw newlines inside data without multi-line framing; keep JSON single-line.
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
    """Extract assistant delta text from an OpenAI chat.completion.chunk payload."""
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
    # Some servers send full message on stream (non-standard).
    message = choice.get("message") or {}
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
    return ""


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

