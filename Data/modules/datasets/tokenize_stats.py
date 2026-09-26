"""Token statistics — bounded-memory online aggregation."""

from __future__ import annotations

import random
import re
from typing import Any, Iterable, Protocol

from .memory_policy import (
    DEFAULT_TOKEN_STATS_EXACT_MAX_ROWS,
    DEFAULT_TOKEN_STATS_RESERVOIR,
    resolve_dataset_memory_policy,
)
from .types import CanonicalRecord


class Tokenizer(Protocol):
    def encode(self, text: str) -> list[int]: ...


_WORD_RE = re.compile(r"\S+")


def estimate_tokens(text: str) -> int:
    """Labeled heuristic estimate — not a tokenizer claim."""
    words = _WORD_RE.findall(text or "")
    if not words:
        return 0
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


def _percentile_from_sorted(sorted_lens: list[int], p: float) -> int:
    if not sorted_lens:
        return 0
    idx = min(len(sorted_lens) - 1, max(0, int(round((p / 100.0) * (len(sorted_lens) - 1)))))
    return sorted_lens[idx]


def compute_token_stats(
    records: Iterable[CanonicalRecord],
    *,
    tokenizer: Tokenizer | None = None,
    encoding_name: str = "cl100k_base",
    exact_max_rows: int | None = None,
    reservoir_size: int | None = None,
) -> dict[str, Any]:
    """Compute token stats with bounded memory.

    Exact percentiles when row_count <= exact_max_rows; otherwise reservoir
    sampling for approximate percentiles (honestly labeled).
    Online: row_count, total, min, max, mean are always exact.
    """
    policy = resolve_dataset_memory_policy()
    exact_cap = (
        int(exact_max_rows)
        if exact_max_rows is not None
        else policy.token_stats_exact_max_rows or DEFAULT_TOKEN_STATS_EXACT_MAX_ROWS
    )
    reservoir_cap = (
        int(reservoir_size)
        if reservoir_size is not None
        else policy.token_stats_reservoir or DEFAULT_TOKEN_STATS_RESERVOIR
    )

    tok = tokenizer or _try_load_tiktoken(encoding_name)
    if tok is not None:
        method = "tiktoken" if tokenizer is None else "provided_tokenizer"
        encoding: str | None = encoding_name if tokenizer is None else "custom"
        estimate = False
    else:
        method = "word_heuristic_estimate"
        encoding = None
        estimate = True

    total = 0
    n = 0
    min_tok = 0
    max_tok = 0
    lengths_exact: list[int] = []
    reservoir: list[int] = []
    approximate = False
    rng = random.Random(42)

    for rec in records:
        text = _record_text(rec)
        length = len(tok.encode(text)) if tok is not None else estimate_tokens(text)
        n += 1
        total += length
        if n == 1:
            min_tok = max_tok = length
        else:
            if length < min_tok:
                min_tok = length
            if length > max_tok:
                max_tok = length

        if not approximate:
            if n <= exact_cap:
                lengths_exact.append(length)
            else:
                # Switch to reservoir: seed with existing exact lengths
                approximate = True
                reservoir = list(lengths_exact)
                lengths_exact = []
                if len(reservoir) > reservoir_cap:
                    reservoir = reservoir[:reservoir_cap]
                # Include current length via reservoir algorithm
                if len(reservoir) < reservoir_cap:
                    reservoir.append(length)
                else:
                    j = rng.randint(1, n)
                    if j <= reservoir_cap:
                        reservoir[j - 1] = length
        else:
            if len(reservoir) < reservoir_cap:
                reservoir.append(length)
            else:
                j = rng.randint(1, n)
                if j <= reservoir_cap:
                    reservoir[j - 1] = length

    avg = (total / n) if n else 0.0
    if approximate:
        sample = sorted(reservoir)
        quantile_method = "reservoir_sample"
        p50 = _percentile_from_sorted(sample, 50)
        p95 = _percentile_from_sorted(sample, 95)
    else:
        sample = sorted(lengths_exact)
        quantile_method = "exact"
        p50 = _percentile_from_sorted(sample, 50)
        p95 = _percentile_from_sorted(sample, 95)

    return {
        "method": method,
        "estimate": estimate,
        "encoding": encoding,
        "rowCount": n,
        "totalTokens": total,
        "avgTokens": round(avg, 3),
        "minTokens": min_tok if n else 0,
        "maxTokens": max_tok if n else 0,
        "p50Tokens": p50,
        "p95Tokens": p95,
        "quantileMethod": quantile_method,
        "approximate": approximate,
        "reservoirSize": len(reservoir) if approximate else None,
        "sampleSize": len(sample),
        "note": (
            "Values are heuristic estimates, not tokenizer output"
            if estimate
            else "Values from a real tokenizer encoding"
        )
        + (
            "; percentiles are approximate (reservoir sample)"
            if approximate
            else "; percentiles are exact"
        ),
    }
