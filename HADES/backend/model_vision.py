"""Honest vision / multimodal attachment helpers for local LM Studio models."""

from __future__ import annotations

import base64
from typing import Any


def model_supports_vision(model: dict[str, Any] | None) -> bool:
    """Return True only when LM Studio metadata clearly advertises vision."""
    if not isinstance(model, dict):
        return False
    model_type = str(model.get("type") or model.get("model_type") or "").strip().lower()
    if model_type in {"vlm", "vision", "multimodal"}:
        return True
    caps = model.get("capabilities")
    if isinstance(caps, dict) and caps.get("vision") is True:
        return True
    if isinstance(caps, (list, tuple, set)) and "vision" in {str(item).lower() for item in caps}:
        return True
    return False


def is_image_mime(mime: str | None) -> bool:
    return str(mime or "").lower().startswith("image/")


def find_model_record(models: list[dict[str, Any]], model_id: str | None) -> dict[str, Any] | None:
    needle = str(model_id or "").strip()
    if not needle:
        return None
    for item in models:
        if not isinstance(item, dict):
            continue
        for key in ("id", "key", "name"):
            if str(item.get(key) or "").strip() == needle:
                return item
    return None


def image_data_url(*, mime_type: str, payload: bytes) -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    mime = mime_type if mime_type.startswith("image/") else "image/png"
    return f"data:{mime};base64,{encoded}"


def apply_vision_parts_to_messages(
    messages: list[dict[str, Any]],
    *,
    vision_parts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach OpenAI-style image_url parts to the latest user message when present."""
    if not vision_parts or not messages:
        return messages
    out = [dict(item) for item in messages]
    for index in range(len(out) - 1, -1, -1):
        if out[index].get("role") != "user":
            continue
        existing = out[index].get("content")
        parts: list[dict[str, Any]] = []
        if isinstance(existing, list):
            parts.extend(item for item in existing if isinstance(item, dict))
        else:
            text = str(existing or "")
            if text:
                parts.append({"type": "text", "text": text})
        parts.extend(vision_parts)
        out[index]["content"] = parts
        break
    return out
