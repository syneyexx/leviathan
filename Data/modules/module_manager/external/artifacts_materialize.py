"""Materialize external FILE/stdout results into ArtifactStore.

Keeps CapabilityResult.output bounded: Chat gets artifact_ids, not giant blobs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


def materialize_external_files(
    output: Mapping[str, Any] | None,
    *,
    artifact_store: Any,
    module_id: str,
    operation: str,
    max_file_bytes: int = 25_000_000,
) -> dict[str, Any]:
    """Register FILE parts / path refs into ArtifactStore; rewrite artifact_refs to ids."""
    out = dict(output or {})
    if artifact_store is None or not hasattr(artifact_store, "create_from_bytes"):
        return out

    stored: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    # Collect candidate file maps from FILE parts and leftover path-like refs.
    candidates: list[Mapping[str, Any]] = []
    for part in list(out.get("parts") or []):
        if not isinstance(part, Mapping):
            continue
        if str(part.get("kind") or "").upper() != "FILE":
            continue
        for f in list(part.get("files") or []):
            if isinstance(f, Mapping):
                candidates.append(f)

    for ref in list(out.get("artifact_refs") or []):
        sref = str(ref or "")
        if sref.startswith("/") or sref.startswith("file:"):
            path = sref.removeprefix("file:")
            candidates.append({"path": path, "name": Path(path).name})

    for item in candidates:
        path_s = str(item.get("path") or "")
        if not path_s or path_s in seen_paths:
            continue
        path = Path(path_s)
        if not path.is_file():
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > max_file_bytes:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        name = str(item.get("name") or path.name)
        # ArtifactStore requires a plain basename.
        safe_name = Path(name).name or "artifact.bin"
        try:
            record = artifact_store.create_from_bytes(
                data=data,
                artifact_type=str(item.get("artifact_type") or _guess_type(safe_name)),
                producer=f"external:{module_id}:{operation}",
                filename=safe_name,
                metadata={
                    "module_id": module_id,
                    "operation": operation,
                    "source_path": str(path),
                    "content_hash_hint": item.get("content_hash"),
                },
            )
        except Exception:  # noqa: BLE001 — never fail the tool for store issues
            continue
        seen_paths.add(path_s)
        stored.append(
            {
                "artifact_id": record.artifact_id,
                "ref": record.artifact_id,
                "path": record.path,
                "name": safe_name,
                "size": record.size_bytes,
                "content_hash": record.content_hash,
            }
        )

    if not stored:
        return out

    # Rewrite ARTIFACT part + artifact_refs to store ids (drop raw path refs).
    parts = [p for p in list(out.get("parts") or []) if not (isinstance(p, Mapping) and str(p.get("kind")).upper() == "ARTIFACT")]
    parts.append({"kind": "ARTIFACT", "artifacts": stored, "count": len(stored)})
    # Keep FILE parts for UI (path) but prefer ARTIFACT ids in refs.
    out["parts"] = parts
    out["artifact_refs"] = [s["artifact_id"] for s in stored]
    meta = dict(out.get("metadata") or {})
    meta["artifacts_materialized"] = len(stored)
    out["metadata"] = meta
    return out


def materialize_large_stdout(
    output: Mapping[str, Any] | None,
    *,
    stdout: str,
    artifact_store: Any,
    module_id: str,
    operation: str,
    max_inline_bytes: int = 64_000,
) -> dict[str, Any]:
    """Spill oversized stdout into ArtifactStore; keep a short excerpt inline."""
    out = dict(output or {})
    if artifact_store is None or not hasattr(artifact_store, "create_from_bytes"):
        return out
    raw = stdout.encode("utf-8", errors="replace")
    if len(raw) <= max_inline_bytes:
        return out
    try:
        record = artifact_store.create_from_bytes(
            data=raw,
            artifact_type="text",
            producer=f"external:{module_id}:{operation}",
            filename="stdout.txt",
            metadata={"module_id": module_id, "operation": operation, "kind": "stdout"},
        )
    except Exception:  # noqa: BLE001
        return out
    out["stdout_artifact"] = record.artifact_id
    refs = list(out.get("artifact_refs") or [])
    if record.artifact_id not in refs:
        refs.append(record.artifact_id)
    out["artifact_refs"] = refs
    # Drop giant TEXT parts that mirror full stdout.
    bounded_parts = []
    for part in list(out.get("parts") or []):
        if not isinstance(part, Mapping):
            continue
        if str(part.get("kind") or "").upper() == "TEXT" and len(str(part.get("text") or "").encode()) > max_inline_bytes:
            bounded_parts.append(
                {
                    "kind": "TEXT",
                    "text": str(part.get("text") or "")[:2000] + "\n…[truncated — see stdout artifact]",
                    "truncated": True,
                    "stdout_artifact": record.artifact_id,
                }
            )
            continue
        bounded_parts.append(dict(part))
    out["parts"] = bounded_parts
    meta = dict(out.get("metadata") or {})
    meta["stdout_spilled"] = True
    meta["stdout_bytes"] = len(raw)
    out["metadata"] = meta
    out["stdout_excerpt"] = stdout[:4000]
    return out


def _guess_type(name: str) -> str:
    lower = name.lower()
    if lower.endswith((".md", ".txt", ".log", ".json", ".jsonl", ".csv", ".html", ".htm")):
        return "text"
    if lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
        return "image"
    if lower.endswith((".pdf", ".pptx", ".xlsx", ".zip")):
        return "document"
    return "binary"
