from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .types import CapabilityAnnouncement, ModuleIsolation, ModuleManifest


class ManifestError(ValueError):
    pass


def _as_tuple_str(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    raise ManifestError(f"Expected string list, got {type(value).__name__}")


def parse_manifest(data: dict[str, Any], *, source_path: Path | None = None) -> ModuleManifest:
    module_id = str(data.get("module_id") or "").strip()
    name = str(data.get("name") or "").strip()
    version = str(data.get("version") or "0.0.0").strip()
    entrypoint = str(data.get("entrypoint") or "").strip()
    if not module_id or not name or not entrypoint:
        raise ManifestError("module_id, name, and entrypoint are required")
    if ":" not in entrypoint:
        raise ManifestError("entrypoint must be 'package.module:Factory'")

    caps_raw = data.get("capabilities") or []
    capabilities: list[CapabilityAnnouncement] = []
    if not isinstance(caps_raw, list):
        raise ManifestError("capabilities must be a list")
    for item in caps_raw:
        if not isinstance(item, dict):
            raise ManifestError("capability entries must be objects")
        capability_id = str(item.get("capability_id") or "").strip()
        cap_name = str(item.get("name") or capability_id).strip()
        if not capability_id:
            raise ManifestError("capability_id required")
        capabilities.append(
            CapabilityAnnouncement(
                capability_id=capability_id,
                name=cap_name,
                description=str(item.get("description") or ""),
                external_name=(str(item["external_name"]) if item.get("external_name") else None),
                side_effects=_as_tuple_str(item.get("side_effects") or ("READ",)),
                required_permissions=_as_tuple_str(item.get("required_permissions")),
            )
        )

    isolation_raw = str(data.get("isolation") or "INPROC").upper()
    try:
        isolation = ModuleIsolation(isolation_raw)
    except ValueError as exc:
        raise ManifestError(f"Unknown isolation: {isolation_raw}") from exc

    metadata = dict(data.get("metadata") or {})
    if isinstance(data.get("mcp"), dict):
        metadata = {**metadata, "mcp": data["mcp"]}

    return ModuleManifest(
        module_id=module_id,
        name=name,
        version=version,
        entrypoint=entrypoint,
        capabilities=tuple(capabilities),
        permissions=_as_tuple_str(data.get("permissions")),
        side_effects=_as_tuple_str(data.get("side_effects") or ("READ",)),
        isolation=isolation,
        hot_reload=bool(data.get("hot_reload", False)),
        neuro_hooks=_as_tuple_str(data.get("neuro_hooks")),
        source_path=str(source_path) if source_path is not None else None,
        metadata=metadata,
    )


def load_manifest_file(path: Path) -> ModuleManifest:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"Failed to read manifest {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError(f"Manifest root must be an object: {path}")
    return parse_manifest(data, source_path=path)


def discover_manifest_paths(roots: Iterable[Path]) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for path in sorted(root.glob("*/module.json")):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            found.append(path)
    return found
