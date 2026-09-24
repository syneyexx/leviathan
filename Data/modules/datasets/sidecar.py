"""Durable on-disk dataset identity sidecars (atomic, human-readable).

Sidecars are a recovery aid for catalog reconciliation after clean installs.
They do **not** replace DatasetStore or KnowledgeStore as sources of truth.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from Data.modules.common.atomic import atomic_write_text
from Data.modules.common.paths import normalize_path_key

SIDECAR_FILENAME = ".leviathan-dataset.json"
TOMBSTONE_FILENAME = ".leviathan-dataset.deleted"
SIDECAR_SCHEMA_VERSION = 1


class SidecarError(Exception):
    def __init__(self, message: str, *, code: str = "sidecar_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def sidecar_path_for(directory: Path) -> Path:
    return Path(directory) / SIDECAR_FILENAME


def tombstone_path_for(directory: Path) -> Path:
    return Path(directory) / TOMBSTONE_FILENAME


def build_sidecar_payload(
    *,
    dataset_id: str,
    name: str,
    source_type: str | None = None,
    content_hash: str | None = None,
    original_uri: str | None = None,
    original_filename: str | None = None,
    raw_path: str | None = None,
    version_id: str | None = None,
    version_label: str | None = None,
    detected_format: str | None = None,
    row_count: int | None = None,
    byte_size: int | None = None,
    provenance: dict[str, Any] | None = None,
    created_at: str | None = None,
    updated_at: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not dataset_id or not str(dataset_id).strip():
        raise SidecarError("datasetId is required", code="sidecar_missing_id")
    if not name or not str(name).strip():
        raise SidecarError("name is required", code="sidecar_missing_name")
    payload: dict[str, Any] = {
        "schemaVersion": SIDECAR_SCHEMA_VERSION,
        "datasetId": str(dataset_id).strip(),
        "name": str(name).strip(),
        "sourceType": source_type,
        "contentHash": content_hash,
        "originalUri": original_uri,
        "originalFilename": original_filename,
        "rawPath": raw_path,
        "versionId": version_id,
        "versionLabel": version_label,
        "detectedFormat": detected_format,
        "rowCount": row_count,
        "byteSize": byte_size,
        "provenance": dict(provenance or {}),
        "createdAt": created_at,
        "updatedAt": updated_at,
        "truth": {
            "sidecar_is_not_catalog": True,
            "sidecar_is_not_knowledge_store": True,
            "catalog_remains_authoritative": True,
        },
    }
    if extra:
        payload["extra"] = dict(extra)
    return payload


def write_sidecar(directory: Path, payload: dict[str, Any]) -> Path:
    """Atomically write a validated sidecar next to the dataset corpus folder."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    validated = validate_sidecar(payload)
    path = sidecar_path_for(directory)
    atomic_write_text(path, json.dumps(validated, ensure_ascii=False, indent=2) + "\n")
    # Clear tombstone if we are deliberately restoring identity.
    tomb = tombstone_path_for(directory)
    if tomb.exists():
        try:
            tomb.unlink()
        except OSError:
            pass
    return path


def write_tombstone(directory: Path, *, dataset_id: str, reason: str = "deleted") -> Path:
    """Mark a dataset directory as intentionally deleted (blocks auto-restore)."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = tombstone_path_for(directory)
    payload = {
        "schemaVersion": SIDECAR_SCHEMA_VERSION,
        "datasetId": dataset_id,
        "reason": reason,
        "truth": {"intentional_delete_blocks_auto_restore": True},
    }
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path


def read_sidecar(path: Path) -> dict[str, Any] | None:
    path = Path(path)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        return validate_sidecar(raw)
    except SidecarError:
        return None


def validate_sidecar(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SidecarError("sidecar must be an object", code="sidecar_invalid")
    dataset_id = str(payload.get("datasetId") or payload.get("dataset_id") or "").strip()
    name = str(payload.get("name") or "").strip()
    if not dataset_id:
        raise SidecarError("sidecar missing datasetId", code="sidecar_missing_id")
    if not name:
        raise SidecarError("sidecar missing name", code="sidecar_missing_name")
    schema = int(payload.get("schemaVersion") or payload.get("schema_version") or 1)
    if schema < 1 or schema > SIDECAR_SCHEMA_VERSION:
        raise SidecarError(f"unsupported sidecar schemaVersion={schema}", code="sidecar_schema")
    # Normalize to canonical keys; do not invent missing provenance fields.
    out = build_sidecar_payload(
        dataset_id=dataset_id,
        name=name,
        source_type=_opt_str(payload.get("sourceType") or payload.get("source_type")),
        content_hash=_opt_str(payload.get("contentHash") or payload.get("content_hash")),
        original_uri=_opt_str(payload.get("originalUri") or payload.get("original_uri")),
        original_filename=_opt_str(
            payload.get("originalFilename") or payload.get("original_filename")
        ),
        raw_path=_opt_str(payload.get("rawPath") or payload.get("raw_path")),
        version_id=_opt_str(payload.get("versionId") or payload.get("version_id")),
        version_label=_opt_str(payload.get("versionLabel") or payload.get("version_label")),
        detected_format=_opt_str(payload.get("detectedFormat") or payload.get("detected_format")),
        row_count=_opt_int(payload.get("rowCount") or payload.get("row_count")),
        byte_size=_opt_int(payload.get("byteSize") or payload.get("byte_size")),
        provenance=payload.get("provenance") if isinstance(payload.get("provenance"), dict) else {},
        created_at=_opt_str(payload.get("createdAt") or payload.get("created_at")),
        updated_at=_opt_str(payload.get("updatedAt") or payload.get("updated_at")),
        extra=payload.get("extra") if isinstance(payload.get("extra"), dict) else None,
    )
    return out


def find_sidecars_under_roots(
    roots: list[tuple[str, Path]],
    *,
    max_files: int = 2000,
) -> list[dict[str, Any]]:
    """Discover sidecar files under allowed roots only."""
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root_id, root in roots:
        root = Path(root)
        if not root.exists() or not root.is_dir():
            continue
        try:
            candidates = list(root.rglob(SIDECAR_FILENAME))
        except OSError:
            continue
        for path in candidates:
            if len(found) >= max_files:
                return found
            try:
                key = normalize_path_key(str(path.resolve()))
            except OSError:
                key = normalize_path_key(str(path))
            if key in seen:
                continue
            seen.add(key)
            directory = path.parent
            tomb = tombstone_path_for(directory)
            payload = read_sidecar(path)
            found.append(
                {
                    "rootId": root_id,
                    "path": str(path),
                    "directory": str(directory),
                    "pathKey": key,
                    "tombstoned": tomb.is_file(),
                    "sidecar": payload,
                    "valid": payload is not None,
                }
            )
    return found


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _opt_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
