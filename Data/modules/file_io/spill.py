"""Spill large capability results to ArtifactStore; keep JobStore/HTTP bounded."""

from __future__ import annotations

import json
from typing import Any, Callable

from Data.modules.execution.file_io_thresholds import load_file_io_thresholds


def maybe_spill_result(
    payload: dict[str, Any],
    *,
    artifact_store: Any | None,
    producer: str,
    artifact_type: str = "file_io_result",
    filename: str = "result.json",
    run_id: str | None = None,
    job_id: str | None = None,
    preview_keys: tuple[str, ...] = ("content", "excerpt", "sample_rows", "entries", "rows"),
    max_inline_result_bytes: int | None = None,
) -> dict[str, Any]:
    """If serialized payload exceeds inline limit, store full body as artifact.

    Returns a bounded dict with ``artifact_ref`` / ``artifact_id`` and previews.
    """
    thresholds = load_file_io_thresholds()
    limit = (
        int(max_inline_result_bytes)
        if max_inline_result_bytes is not None
        else thresholds.max_inline_result_bytes
    )
    encoded = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    if len(encoded) <= limit:
        return {**payload, "truncated": bool(payload.get("truncated")), "artifact_ref": None}

    if artifact_store is None or not hasattr(artifact_store, "create_from_bytes"):
        # Fail closed on enormous inline results — keep a truncated preview only.
        bounded = _bounded_preview(payload, preview_keys=preview_keys, limit=limit)
        bounded["truncated"] = True
        bounded["artifact_ref"] = None
        bounded["spill_error"] = "ARTIFACT_STORE_UNAVAILABLE"
        return bounded

    record = artifact_store.create_from_bytes(
        data=encoded,
        artifact_type=artifact_type,
        producer=producer,
        filename=filename,
        run_id=run_id,
        job_id=job_id,
        metadata={"spilled": True, "original_bytes": len(encoded)},
    )
    bounded = _bounded_preview(payload, preview_keys=preview_keys, limit=limit)
    bounded["truncated"] = True
    bounded["artifact_ref"] = getattr(record, "artifact_id", None) or str(record)
    bounded["artifact_id"] = bounded["artifact_ref"]
    bounded["artifact_bytes"] = len(encoded)
    bounded["content_hash"] = getattr(record, "content_hash", None)
    return bounded


def _bounded_preview(
    payload: dict[str, Any],
    *,
    preview_keys: tuple[str, ...],
    limit: int,
) -> dict[str, Any]:
    out = dict(payload)
    for key in preview_keys:
        if key not in out:
            continue
        value = out[key]
        if isinstance(value, str) and len(value.encode("utf-8")) > limit // 4:
            # Keep a UTF-8-safe prefix.
            raw = value.encode("utf-8")[: max(256, limit // 4)]
            out[key] = raw.decode("utf-8", errors="ignore")
            out[f"{key}_preview"] = True
        elif isinstance(value, list) and len(value) > 50:
            out[key] = value[:50]
            out[f"{key}_preview"] = True
            out[f"{key}_total"] = len(value)
    # Ensure overall size still bounded.
    encoded = json.dumps(out, ensure_ascii=False, default=str).encode("utf-8")
    if len(encoded) > limit:
        for key in preview_keys:
            if key in out and isinstance(out[key], str):
                out[key] = out[key][:512]
        out["truncated"] = True
    return out


ProgressCallback = Callable[[dict[str, Any]], None]


def emit_progress(callback: ProgressCallback | None, **fields: Any) -> None:
    if callback is None:
        return
    try:
        callback(dict(fields))
    except Exception:  # noqa: BLE001 — progress must not break work
        pass
