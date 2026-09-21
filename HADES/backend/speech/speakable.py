"""Sanitize assistant text before TTS.

Never speak internal reasoning, tool dump output, or raw fenced code blocks.
"""

from __future__ import annotations

import re
from typing import Iterable

_CODE_FENCE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_THINK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_REASONING_BLOCK_RE = re.compile(
    r"(?im)^(redenering|reasoning|internal thoughts?|chain[- ]of[- ]thought)\s*:\s*.+(?:\n\s{2,}.+)*"
)
_TOOL_BLOCK_RE = re.compile(
    r"(?im)^(tool(?:call| result| output)?|function call|plugin result)\s*[:\[].+(?:\n\s{2,}.+)*"
)
_JSON_TOOL_RE = re.compile(r"(?s)\{\s*\"(?:name|tool|function)\"\s*:.*?\}")
_MARKDOWN_HEADING_RE = re.compile(r"(?m)^#{1,6}\s+")
_BULLET_RE = re.compile(r"(?m)^[\-\*\u2022]\s+")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_MULTI_NL_RE = re.compile(r"\n{3,}")
_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+(?=[\"'“‘(\[]?[A-ZÀ-ÖØ-Þ0-9])")


def prepare_speakable_text(text: str, *, max_chars: int = 4096) -> str:
    """Return cleaned speakable prose, truncated to VoiceStudio's input limit."""
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return ""

    cleaned = _THINK_RE.sub(" ", raw)
    cleaned = _CODE_FENCE_RE.sub(" ", cleaned)
    cleaned = _REASONING_BLOCK_RE.sub(" ", cleaned)
    cleaned = _TOOL_BLOCK_RE.sub(" ", cleaned)
    cleaned = _JSON_TOOL_RE.sub(" ", cleaned)
    cleaned = _INLINE_CODE_RE.sub(r"\1", cleaned)
    cleaned = _MARKDOWN_HEADING_RE.sub("", cleaned)
    cleaned = _BULLET_RE.sub("", cleaned)
    cleaned = cleaned.replace("**", "").replace("__", "").replace("*", "")
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned)
    cleaned = _MULTI_NL_RE.sub("\n\n", cleaned)
    cleaned = " ".join(line.strip() for line in cleaned.splitlines() if line.strip())
    cleaned = cleaned.strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return cleaned


def split_speakable_chunks(text: str, *, max_chars: int = 480) -> list[str]:
    """Split speakable text into sequential chunks for HADES-side sentence TTS.

    VoiceStudio's OpenAI-compatible ``POST /v1/audio/speech`` synthesizes a
    complete clip per request (no PCM/SSE incremental stream). Chunking here
    only reduces time-to-first-audio by requesting smaller clips sequentially.
    """
    speakable = prepare_speakable_text(text)
    if not speakable:
        return []
    if len(speakable) <= max_chars:
        return [speakable]

    sentences = [part.strip() for part in _SENTENCE_RE.split(speakable) if part.strip()]
    if not sentences:
        return _hard_wrap(speakable, max_chars)

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_hard_wrap(sentence, max_chars))
            continue
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def _hard_wrap(text: str, max_chars: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    out: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip() if current else word
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                out.append(current)
            if len(word) > max_chars:
                out.extend(word[i : i + max_chars] for i in range(0, len(word), max_chars))
                current = ""
            else:
                current = word
    if current:
        out.append(current)
    return out


def join_preview_sample(language: str = "nl") -> str:
    if (language or "").lower().startswith("en"):
        return "Hello, this is the selected HADES voice profile."
    return "Hallo, dit is het gekozen HADES-stemprofiel. Nederlandse uitspraak klinkt zo."
