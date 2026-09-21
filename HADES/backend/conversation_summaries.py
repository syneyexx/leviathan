"""Cached hierarchical conversation summaries (HADES-10 Phase 5).

Summaries are NOT evidence. They link to source message IDs, are keyed by
source-range hash, and fail honestly when the model is unavailable.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:24]


def range_key(message_ids: list[str], contents: list[str]) -> str:
    blob = "\n".join(f"{mid}\0{content}" for mid, content in zip(message_ids, contents))
    return _sha(blob)


def build_hierarchical_history(
    messages: list[dict[str, Any]],
    *,
    max_recent_raw: int = 12,
    layer_size: int = 30,
    max_chars: int = 55_000,
    cache: dict[str, dict[str, Any]] | None = None,
    summarize_fn: Callable[[str], str] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Return prompt history: cached layer summaries + recent raw turns.

    Does not re-summarize the entire conversation every turn. Only missing or
    invalidated layers are (re)computed. Without ``summarize_fn``, layers use an
    extractive stub labeled ``stub_not_model_summary``.
    """
    cache = cache if isinstance(cache, dict) else {}
    normalized: list[dict[str, str]] = []
    for item in messages:
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        entry: dict[str, str] = {
            "role": str(item.get("role") or "user"),
            "content": content,
            "id": str(item.get("id") or ""),
        }
        normalized.append(entry)

    if len(normalized) <= max_recent_raw:
        used = 0
        out: list[dict[str, str]] = []
        for item in reversed(normalized):
            if out and used + len(item["content"]) > max_chars:
                break
            out.append({"role": item["role"], "content": item["content"], "id": item["id"]})
            used += len(item["content"])
        out.reverse()
        return out, {"layers": [], "mode": "raw_only", "cache_hits": 0, "cache_misses": 0}

    older = normalized[:-max_recent_raw]
    recent = normalized[-max_recent_raw:]
    layers: list[dict[str, Any]] = []
    cache_hits = 0
    cache_misses = 0
    prompt_parts: list[dict[str, str]] = []

    for start in range(0, len(older), layer_size):
        chunk = older[start : start + layer_size]
        ids = [m["id"] for m in chunk]
        contents = [m["content"] for m in chunk]
        key = range_key(ids, contents)
        cached = cache.get(key) if isinstance(cache.get(key), dict) else None
        if cached and cached.get("source_range_key") == key and cached.get("text"):
            text = str(cached["text"])
            quality = str(cached.get("summary_quality") or "stub_not_model_summary")
            cache_hits += 1
        else:
            cache_misses += 1
            quality = "stub_not_model_summary"
            text = ""
            if summarize_fn is not None:
                try:
                    joined = "\n".join(f"{m['role']}: {m['content'][:800]}" for m in chunk)
                    raw = str(
                        summarize_fn(
                            "Summarize this conversation segment for later context. "
                            "Keep decisions, constraints, and open questions. "
                            "Do not invent facts.\n\n" + joined
                        )
                        or ""
                    ).strip()
                    if raw:
                        text = raw[:4_000]
                        quality = "model_summary"
                except Exception as exc:  # noqa: BLE001
                    text = ""
                    quality = "stub_not_model_summary"
                    cache[key] = {
                        "source_range_key": key,
                        "summary_quality": quality,
                        "text": "",
                        "error": str(exc)[:240],
                        "source_message_ids": ids,
                    }
            if not text:
                bullets = []
                for m in chunk[:12]:
                    snippet = m["content"].replace("\n", " ").strip()[:180]
                    bullets.append(f"- [{m['role']}] {snippet}")
                text = (
                    f"[stub_not_model_summary] Segment {start + 1}–{start + len(chunk)}:\n"
                    + "\n".join(bullets)
                )
                quality = "stub_not_model_summary"
            cache[key] = {
                "source_range_key": key,
                "summary_quality": quality,
                "text": text,
                "source_message_ids": ids,
            }
        layers.append(
            {
                "range_key": key,
                "summary_quality": quality,
                "source_message_ids": ids,
                "start": start,
                "end": start + len(chunk),
            }
        )
        prompt_parts.append(
            {
                "role": "system",
                "content": f"CONVERSATION SUMMARY ({quality}; not evidence; sources={','.join(i for i in ids if i)}):\n{text}",
                "id": f"summary:{key}",
            }
        )

    used = sum(len(p["content"]) for p in prompt_parts)
    for item in recent:
        if used + len(item["content"]) > max_chars and prompt_parts:
            break
        prompt_parts.append({"role": item["role"], "content": item["content"], "id": item["id"]})
        used += len(item["content"])

    meta = {
        "layers": layers,
        "mode": "hierarchical",
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "recent_raw": len(recent),
        "summary_quality_set": sorted({layer["summary_quality"] for layer in layers}),
        "note": "Summaries are not evidence; raw messages remain authoritative.",
    }
    # Drop empty id keys for LM compatibility while keeping ids in meta.
    out_msgs = [{"role": m["role"], "content": m["content"]} for m in prompt_parts]
    return out_msgs, meta


def dump_summary_cache(cache: dict[str, dict[str, Any]]) -> str:
    return json.dumps(cache, ensure_ascii=False)


def load_summary_cache(raw: Any) -> dict[str, dict[str, Any]]:
    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items() if isinstance(v, dict)}
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return {str(k): v for k, v in parsed.items() if isinstance(v, dict)}
    return {}
