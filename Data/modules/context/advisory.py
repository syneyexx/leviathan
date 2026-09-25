"""Model-facing advisory / reference normalization.

Compress Neuro / Memory / Why / Atlas / Observations into bounded semantic
records before they enter the LLM context. Never use str(dataclass)/repr.
ContextBuilder remains the canonical compiler — this module only serializes.
"""

from __future__ import annotations

import re
from typing import Any

_RAW_NEURO_RE = re.compile(r"NeuroSignal\s*\(")
_ADVISORY_TAG_RE = re.compile(r"\[ADVISORY_[A-Z0-9_]+\]")
_PROVENANCE_DUMP_RE = re.compile(r"\b(truth|provenance)\s*=\s*\{")


def _clip(text: str, max_chars: int) -> str:
    raw = (text or "").strip()
    if len(raw) <= max_chars:
        return raw
    return raw[: max(0, max_chars - 1)].rstrip() + "…"


def _confidence_label(strength: float | None) -> str:
    try:
        value = float(strength) if strength is not None else 0.3
    except (TypeError, ValueError):
        value = 0.3
    if value >= 0.75:
        return "high"
    if value >= 0.4:
        return "medium"
    return "low"


def sanitize_model_facing_text(text: str) -> str:
    """Strip raw implementation dumps from text that might reach the model."""
    if not text:
        return ""
    cleaned = text
    if _RAW_NEURO_RE.search(cleaned):
        # Replace dataclass repr dumps with a short advisory note.
        cleaned = _RAW_NEURO_RE.sub("[advisory signal]", cleaned)
        cleaned = re.sub(r"signal_id\s*=\s*\"[^\"]*\"\s*,?", "", cleaned)
        cleaned = re.sub(r"kind\s*=\s*\"[^\"]*\"\s*,?", "", cleaned)
        cleaned = re.sub(r"strength\s*=\s*[0-9.]+\s*,?", "", cleaned)
        cleaned = re.sub(r"summary\s*=\s*('[^']*'|\"[^\"]*\")\s*,?", r"\1", cleaned)
        cleaned = re.sub(r"provenance\s*=\s*\{[^}]*\}\s*,?", "", cleaned)
        cleaned = re.sub(r"truth\s*=\s*\{[^}]*\}\s*,?", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,")
    cleaned = _ADVISORY_TAG_RE.sub("[advisory]", cleaned)
    cleaned = _PROVENANCE_DUMP_RE.sub("meta={", cleaned)
    return cleaned.strip()


def normalize_neuro_item(item: Any, *, max_chars: int = 420) -> dict[str, Any]:
    """Convert a NeuroSignal / dict into a safe model-facing record."""
    if item is None:
        return {
            "id": "neuro-empty",
            "kind": "advisory",
            "content": "Advisory context unavailable.",
            "status": "advisory",
            "confidence": "low",
        }

    if hasattr(item, "public_dict") and callable(item.public_dict):
        payload = item.public_dict()
    elif isinstance(item, dict):
        payload = item
    else:
        summary = getattr(item, "summary", None) or getattr(item, "content", None)
        payload = {
            "signal_id": getattr(item, "signal_id", None) or getattr(item, "id", None),
            "kind": getattr(item, "kind", None) or "advisory",
            "strength": getattr(item, "strength", None),
            "summary": summary if summary is not None else "advisory association",
        }

    kind = str(payload.get("kind") or payload.get("signal_kind") or "advisory")
    summary = (
        payload.get("summary")
        or payload.get("content")
        or payload.get("claim")
        or payload.get("label")
        or ""
    )
    summary = sanitize_model_facing_text(str(summary))
    strength = payload.get("strength") or payload.get("confidence")
    confidence = _confidence_label(strength if isinstance(strength, (int, float)) else None)
    text = (
        f"Relevant {kind.replace('_', ' ')} association: {_clip(summary, max_chars)}. "
        f"Confidence: {confidence}. This is advisory and may be incomplete."
    )
    return {
        "id": str(payload.get("signal_id") or payload.get("id") or f"neuro-{kind}"),
        "kind": kind,
        "content": text,
        "status": "advisory",
        "confidence": confidence,
        "signal_kind": kind,
    }


def normalize_memory_item(item: dict[str, Any] | Any, *, max_chars: int = 600) -> dict[str, Any]:
    if hasattr(item, "as_context_item"):
        payload = item.as_context_item()
    elif isinstance(item, dict):
        payload = item
    else:
        payload = {"content": str(getattr(item, "content", item))}
    content = sanitize_model_facing_text(
        str(payload.get("content") or payload.get("summary") or payload.get("claim") or "")
    )
    return {
        "memory_id": str(payload.get("memory_id") or payload.get("id") or "memory"),
        "content": _clip(content, max_chars),
        "status": str(payload.get("status") or "ACTIVE"),
        "kind": str(payload.get("kind") or "memory"),
        "scope": payload.get("scope"),
    }


def normalize_generic_advisory(
    item: dict[str, Any] | Any,
    *,
    kind: str,
    max_chars: int = 480,
) -> dict[str, Any]:
    if isinstance(item, dict):
        payload = item
    else:
        payload = {"content": str(item)}
    raw = sanitize_model_facing_text(
        str(payload.get("content") or payload.get("claim") or payload.get("summary") or "")
    )
    title = payload.get("title")
    if title:
        raw = f"{title}: {raw}".strip(": ")
    return {
        "id": str(
            payload.get("id")
            or payload.get("atlas_id")
            or payload.get("why_id")
            or payload.get("evidence_id")
            or f"{kind}-item"
        ),
        "content": _clip(raw, max_chars),
        "status": str(payload.get("status") or "advisory"),
        "kind": kind,
        "title": title,
        "bucket": payload.get("bucket"),
    }


def normalize_neuro_list(items: list[Any] | None, *, limit: int = 8) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in (items or [])[:limit]:
        out.append(normalize_neuro_item(item))
    return out


def looks_like_diagnostic_leak(text: str) -> bool:
    if not text:
        return False
    if "NeuroSignal(" in text:
        return True
    if "[ADVISORY_" in text:
        return True
    if "provenance={" in text or "truth={" in text:
        return True
    if "signal_id=" in text and "kind=" in text and "strength=" in text:
        return True
    return False
