"""Typed filesystem path parameters for ExecutionGateway.

Path security must not rely on argument *names* alone. Capability schemas and
metadata declare path semantics explicitly; the gateway normalizes and resolves
every declared path before provider dispatch.

Declaration (any of):
- property schema: ``"x-leviathan-path": true``
- property schema: ``"format": "leviathan-path"`` (or ``"path"`` / ``"uri-path"``)
- property schema: ``"x-leviathan-path-role": "source"|"dest"|"cwd"|...``
- capability metadata: ``"path_parameters": ["path", "dest_path", ...]``

Legacy well-known argument names remain a fallback for older builtins.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

from Data.modules.common.paths import PathEscapeError

LEGACY_PATH_ARGUMENT_KEYS = frozenset(
    {
        "path",
        "cwd",
        "workspace_root",
        "file_path",
        "source_path",
        "dest_path",
        "destination",
        "destination_path",
        "target",
        "target_path",
        "output_path",
        "output_dir",
        "outdir",
        "out_dir",
        "content_path",
        "directory",
        "dir",
        "root",
        "base_path",
        "src",
        "dst",
        "dest",
        "input_path",
        "infile",
        "outfile",
    }
)

_PATH_FORMATS = frozenset({"leviathan-path", "path", "uri-path", "file-path"})
_FILE_URL_RE = re.compile(r"^file:", re.IGNORECASE)


def is_path_property_schema(prop_schema: Any) -> bool:
    if not isinstance(prop_schema, dict):
        return False
    if prop_schema.get("x-leviathan-path") is True:
        return True
    if prop_schema.get("x-leviathan-path-role"):
        return True
    fmt = str(prop_schema.get("format") or "").strip().lower()
    return fmt in _PATH_FORMATS


def path_keys_from_schema(schema: dict[str, Any] | None) -> set[str]:
    found: set[str] = set()
    if not isinstance(schema, dict):
        return found

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            if isinstance(node, list):
                for item in node:
                    walk(item)
            return
        props = node.get("properties")
        if isinstance(props, dict):
            for key, sub in props.items():
                if is_path_property_schema(sub):
                    found.add(str(key))
                walk(sub)
        items = node.get("items")
        if isinstance(items, (dict, list)):
            walk(items)
        for combinator in ("oneOf", "anyOf", "allOf"):
            branch = node.get(combinator)
            if isinstance(branch, list):
                for sub in branch:
                    walk(sub)
        additional = node.get("additionalProperties")
        if isinstance(additional, dict):
            walk(additional)

    walk(schema)
    return found


def path_keys_from_metadata(metadata: dict[str, Any] | None) -> set[str]:
    raw = dict(metadata or {})
    keys: set[str] = set()
    for candidate in (
        raw.get("path_parameters"),
        (raw.get("extra") or {}).get("path_parameters") if isinstance(raw.get("extra"), dict) else None,
    ):
        if isinstance(candidate, (list, tuple, set, frozenset)):
            for item in candidate:
                text = str(item).strip()
                if text:
                    keys.add(text)
        elif isinstance(candidate, str) and candidate.strip():
            keys.add(candidate.strip())
    return keys


def resolve_path_argument_keys(
    *,
    input_schema: dict[str, Any] | None,
    metadata: dict[str, Any] | None = None,
    arguments: dict[str, Any] | None = None,
    include_legacy_names: bool = True,
) -> set[str]:
    keys = path_keys_from_schema(input_schema) | path_keys_from_metadata(metadata)
    if include_legacy_names:
        args = arguments or {}
        for name in LEGACY_PATH_ARGUMENT_KEYS:
            if name in args:
                keys.add(name)
    return keys


def strip_file_url(raw: str) -> str:
    text = raw.strip()
    if not _FILE_URL_RE.match(text):
        return text
    parsed = urlparse(text)
    if parsed.scheme.lower() != "file":
        return text
    path = unquote(parsed.path or "")
    if parsed.netloc and parsed.netloc not in {"", "localhost", "LOCALHOST"}:
        path = f"//{parsed.netloc}{path}"
    if len(path) >= 3 and path[0] == "/" and path[2] == ":" and path[1].isalpha():
        path = path[1:]
    return path or text


def normalize_path_argument(raw: Any) -> str:
    if raw is None:
        return ""
    text = strip_file_url(str(raw)).strip()
    if not text:
        return ""
    if "\x00" in text:
        raise PathEscapeError("Null byte in path")
    return text


def mark_path_property(prop: dict[str, Any], *, role: str | None = None) -> dict[str, Any]:
    out = dict(prop)
    out.setdefault("type", "string")
    out["x-leviathan-path"] = True
    out.setdefault("format", "leviathan-path")
    if role:
        out["x-leviathan-path-role"] = role
    return out


def annotate_schema_paths(
    schema: dict[str, Any],
    path_keys: Iterable[str],
    *,
    roles: dict[str, str] | None = None,
) -> dict[str, Any]:
    out = dict(schema)
    props = dict(out.get("properties") or {})
    role_map = dict(roles or {})
    for key in path_keys:
        existing = dict(props.get(key) or {"type": "string"})
        props[key] = mark_path_property(existing, role=role_map.get(key))
    out["properties"] = props
    return out


def looks_like_windows_path(text: str) -> bool:
    if len(text) >= 3 and text[0].isalpha() and text[1] == ":" and text[2] in {"/", "\\"}:
        return True
    if text.startswith("\\\\") or text.startswith("//"):
        return True
    return "\\" in text


def path_has_parent_traversal(text: str) -> bool:
    pure = PureWindowsPath(text) if looks_like_windows_path(text) else PurePosixPath(text)
    return ".." in pure.parts
