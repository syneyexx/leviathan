"""Token statistics — real tokenizer when available, else labeled estimate."""

from __future__ import annotations

import re
from typing import Any, Protocol

from .types import CanonicalRecord


class Tokenizer(Protocol):
    def encode(self, text: str) -> list[int]: ...


_WORD_RE = re.compile(r"\S+")


def estimate_tokens(text: str) -> int:
    """Labeled heuristic estimate — not a tokenizer claim."""
    words = _WORD_RE.findall(text or "")
    if not words:
        return 0
    # ~0.75 words/token average for English-ish text
    return max(1, int(round(len(words) / 0.75)))


def _try_load_tiktoken(encoding_name: str = "cl100k_base") -> Tokenizer | None:
    try:
        import tiktoken

        enc = tiktoken.get_encoding(encoding_name)

        class _Enc:
            def encode(self, text: str) -> list[int]:
                return list(enc.encode(text or ""))

        return _Enc()
    except Exception:  # noqa: BLE001 — optional dependency
        return None


def _record_text(rec: CanonicalRecord) -> str:
    if rec.text:
        return rec.text
    if rec.messages:
        parts = []
        for msg in rec.messages:
            content = msg.get("content") or msg.get("text") or ""
            if isinstance(content, str):
                parts.append(content)
        return "\n".join(parts)
    return ""


def compute_token_stats(
    records: list[CanonicalRecord],
    *,
    tokenizer: Tokenizer | None = None,
    encoding_name: str = "cl100k_base",
) -> dict[str, Any]:
    """Compute token stats.

    Uses a real tokenizer when provided or when tiktoken is installed;
    otherwise returns an explicitly labeled estimate.
    """
    tok = tokenizer or _try_load_tiktoken(encoding_name)
    lengths: list[int] = []
    method: str
    if tok is not None:
        method = "tiktoken" if tokenizer is None else "provided_tokenizer"
        encoding = encoding_name if tokenizer is None else "custom"
        for rec in records:
            lengths.append(len(tok.encode(_record_text(rec))))
        estimate = False
    else:
        method = "word_heuristic_estimate"
        encoding = None
        estimate = True
        for rec in records:
            lengths.append(estimate_tokens(_record_text(rec)))

    total = sum(lengths)
    n = len(lengths)
    avg = (total / n) if n else 0.0
    sorted_lens = sorted(lengths)
    def pct(p: float) -> int:
        if not sorted_lens:
            return 0
        idx = min(len(sorted_lens) - 1, max(0, int(round((p / 100.0) * (len(sorted_lens) - 1)))))
        return sorted_lens[idx]

    return {
        "method": method,
        "estimate": estimate,
        "encoding": encoding,
        "rowCount": n,
        "totalTokens": total,
        "avgTokens": round(avg, 3),
        "minTokens": min(lengths) if lengths else 0,
        "maxTokens": max(lengths) if lengths else 0,
        "p50Tokens": pct(50),
        "p95Tokens": pct(95),
        "note": (
            "Values are heuristic estimates, not tokenizer output"
            if estimate
            else "Values from a real tokenizer encoding"
        ),
    }
