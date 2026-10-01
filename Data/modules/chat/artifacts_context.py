"""Resolve Chat attachment artifact IDs into MultimodalSession / ContextBuilder parts.

ArtifactStore remains the sole artifact authority. Chat only references IDs and
builds typed multimodal parts for the existing ContextBuilder history path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from Data.modules.context.multimodal import (
    MultimodalPart,
    MultimodalSessionRegistry,
    PartKind,
    new_sync_id,
)


_TEXT_MIME_PREFIXES = ("text/",)
_TEXT_TYPES = frozenset({"text", "json", "xml", "markdown", "md", "csv", "txt"})
_IMAGE_TYPES = frozenset({"image", "png", "jpg", "jpeg", "gif", "webp", "bmp"})
_AUDIO_TYPES = frozenset({"audio", "wav", "mp3", "ogg", "flac", "m4a"})
_MAX_TEXT_INLINE = 48_000


def _safe_read_text(path: str | Path, *, limit: int = _MAX_TEXT_INLINE) -> str | None:
    try:
        raw = Path(path).read_bytes()[: limit + 1]
    except OSError:
        return None
    if len(raw) > limit:
        raw = raw[:limit]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("latin-1")
        except UnicodeDecodeError:
            return None


def _kind_for_record(record: Any, declared_mime: str | None = None) -> PartKind:
    mime = (declared_mime or "").strip().lower()
    atype = str(getattr(record, "artifact_type", "") or "").strip().lower()
    meta = getattr(record, "metadata", None) or {}
    if isinstance(meta, dict):
        mime = mime or str(meta.get("declared_mime_type") or meta.get("mime_type") or "").lower()
        filename = str(meta.get("filename") or meta.get("original_filename") or "")
    else:
        filename = ""
    if mime.startswith("image/") or atype in _IMAGE_TYPES:
        return PartKind.IMAGE
    if mime.startswith("audio/") or atype in _AUDIO_TYPES:
        return PartKind.AUDIO
    if (
        mime.startswith(_TEXT_MIME_PREFIXES)
        or atype in _TEXT_TYPES
        or filename.lower().endswith((".txt", ".md", ".json", ".csv", ".xml", ".py", ".ts", ".tsx"))
    ):
        return PartKind.FILE  # text-bearing file; content inlined below when readable
    return PartKind.FILE


def resolve_artifact_parts(
    *,
    artifact_store: Any,
    artifact_ids: list[str],
    conversation_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Validate IDs and build MultimodalPart dicts + optional text excerpts.

    Returns:
      safe_ids: validated ArtifactStore IDs
      parts: public_dict list suitable for history[i]["parts"]
      text_excerpts: filename → truncated text (for model-visible content)
      vision_parts: count of image parts
      unavailable: list of {artifact_id, reason}
    """
    safe_ids: list[str] = []
    parts: list[dict[str, Any]] = []
    text_excerpts: list[str] = []
    unavailable: list[dict[str, str]] = []
    vision_parts = 0
    sync = new_sync_id()

    for aid in artifact_ids[:20]:
        aid_s = str(aid or "").strip()
        if not aid_s:
            continue
        try:
            record = artifact_store.get(aid_s)
        except Exception as exc:  # noqa: BLE001
            unavailable.append({"artifact_id": aid_s, "reason": f"lookup_failed:{type(exc).__name__}"})
            continue
        if record is None:
            unavailable.append({"artifact_id": aid_s, "reason": "not_found"})
            continue
        safe_ids.append(aid_s)
        meta = record.metadata if isinstance(record.metadata, dict) else {}
        declared_mime = str(
            meta.get("declared_mime_type") or meta.get("mime_type") or ""
        )
        filename = str(meta.get("filename") or Path(str(record.path)).name)
        kind = _kind_for_record(record, declared_mime)
        mime = declared_mime or {
            PartKind.IMAGE: "image/png",
            PartKind.AUDIO: "audio/wav",
            PartKind.FILE: "application/octet-stream",
            PartKind.TEXT: "text/plain",
        }.get(kind, "application/octet-stream")

        text_body: str | None = None
        if kind in {PartKind.FILE, PartKind.TEXT} and not mime.startswith("image/"):
            text_body = _safe_read_text(record.path)
            if text_body is not None:
                text_excerpts.append(
                    f"[attachment:{filename} artifact_id={aid_s}]\n{text_body}"
                )
                part = MultimodalPart.text_part(
                    f"[attachment:{filename}]\n{text_body[:8000]}",
                    sync_id=sync,
                )
                # Preserve artifact linkage on a companion file part.
                file_part = MultimodalPart(
                    part_id=f"part_file_{aid_s[:10]}",
                    kind=PartKind.FILE,
                    mime_type=mime,
                    content_hash=getattr(record, "content_hash", None),
                    artifact_id=aid_s,
                    sync_id=sync,
                    provenance={
                        "source": "chat.attachment",
                        "filename": filename,
                        "size_bytes": getattr(record, "size_bytes", None),
                    },
                )
                parts.append(part.public_dict())
                parts.append(file_part.public_dict())
                continue

        if kind == PartKind.IMAGE:
            vision_parts += 1
            part = MultimodalPart.image_part(
                mime_type=mime if mime.startswith("image/") else "image/png",
                artifact_id=aid_s,
                sync_id=sync,
            )
        elif kind == PartKind.AUDIO:
            part = MultimodalPart.audio_part(
                mime_type=mime if mime.startswith("audio/") else "audio/wav",
                artifact_id=aid_s,
                sync_id=sync,
            )
        else:
            part = MultimodalPart(
                part_id=f"part_file_{aid_s[:10]}",
                kind=PartKind.FILE,
                mime_type=mime,
                content_hash=getattr(record, "content_hash", None),
                artifact_id=aid_s,
                sync_id=sync,
                provenance={
                    "source": "chat.attachment",
                    "filename": filename,
                    "size_bytes": getattr(record, "size_bytes", None),
                    "text_inline": False,
                },
            )
            text_excerpts.append(
                f"[attachment:{filename} artifact_id={aid_s} — binary/file reference only; "
                "content not inlined]"
            )
        parts.append(part.public_dict())

    return {
        "safe_ids": safe_ids,
        "parts": parts,
        "text_excerpts": text_excerpts,
        "vision_parts": vision_parts,
        "unavailable": unavailable,
        "sync_id": sync,
    }


def attach_parts_to_history(
    history: list[dict[str, Any]],
    *,
    parts: list[dict[str, Any]],
    text_excerpts: list[str],
) -> list[dict[str, Any]]:
    """Merge multimodal parts onto the latest user history turn (in place copy)."""
    if not history or (not parts and not text_excerpts):
        return history
    out = [dict(item) for item in history]
    # Prefer last user message; else append annotation to last item.
    target_idx = None
    for i in range(len(out) - 1, -1, -1):
        if out[i].get("role") == "user":
            target_idx = i
            break
    if target_idx is None:
        target_idx = len(out) - 1
    entry = dict(out[target_idx])
    content = str(entry.get("content") or "")
    if text_excerpts:
        excerpt_block = "\n\n".join(text_excerpts)
        content = f"{content}\n\n{excerpt_block}".strip() if content else excerpt_block
    entry["content"] = content
    if parts:
        existing = entry.get("parts") if isinstance(entry.get("parts"), list) else []
        entry["parts"] = list(existing) + list(parts)
    out[target_idx] = entry
    return out


def register_turn_multimodal_session(
    registry: MultimodalSessionRegistry | None,
    *,
    conversation_id: str,
    run_id: str,
    user_text: str,
    parts: list[dict[str, Any]],
) -> str | None:
    """Create a MultimodalSession for this turn when registry is available."""
    if registry is None or not parts:
        return None
    session = registry.create(conversation_id=conversation_id, run_id=run_id)
    typed: list[MultimodalPart] = []
    if user_text.strip():
        typed.append(MultimodalPart.text_part(user_text.strip()))
    for raw in parts:
        kind_s = str(raw.get("kind") or "file")
        try:
            kind = PartKind(kind_s)
        except ValueError:
            kind = PartKind.FILE
        typed.append(
            MultimodalPart(
                part_id=str(raw.get("part_id") or f"part_{len(typed)}"),
                kind=kind,
                mime_type=str(raw.get("mime_type") or "application/octet-stream"),
                content_hash=raw.get("content_hash"),
                text=raw.get("text"),
                artifact_id=raw.get("artifact_id"),
                uri=raw.get("uri"),
                width=raw.get("width"),
                height=raw.get("height"),
                duration_ms=raw.get("duration_ms"),
                region=raw.get("region"),
                timespan=raw.get("timespan"),
                provenance=dict(raw.get("provenance") or {}),
                scope=str(raw.get("scope") or "conversation"),
                sync_id=raw.get("sync_id"),
            )
        )
    session.append("user", typed, sync_id=parts[0].get("sync_id") if parts else None)
    return session.session_id
