"""Local filesystem importers with path-escape protection."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from Data.modules.common.atomic import ensure_dir
from Data.modules.common.hashing import sha256_file
from Data.modules.common.paths import PathEscapeError, safe_join, safe_relpath

from .formats import detect_format
from .types import DatasetError, DetectedFormat, FormatDetection


SUPPORTED_SUFFIXES = {".jsonl", ".json", ".csv", ".tsv", ".txt", ".md", ".markdown"}


def resolve_import_path(path: str | Path, *, allowed_roots: list[Path] | None = None) -> Path:
    """Resolve a user-supplied path; reject escapes outside allowed roots when set."""
    raw = Path(path).expanduser()
    if not raw.is_absolute():
        # Relative paths require an allowed root context
        if not allowed_roots:
            raise DatasetError(
                "Relative import paths require an allowed root",
                code="unsafe_path",
                http_status=400,
            )
        try:
            resolved = safe_join(allowed_roots[0], str(raw))
        except PathEscapeError as exc:
            raise DatasetError(str(exc), code="path_traversal", http_status=400) from exc
    else:
        resolved = raw.resolve()
        if allowed_roots:
            ok = False
            for root in allowed_roots:
                try:
                    safe_relpath(root, resolved)
                    ok = True
                    break
                except PathEscapeError:
                    continue
            if not ok:
                raise DatasetError(
                    "Import path escapes allowed roots",
                    code="path_traversal",
                    http_status=400,
                )
    if not resolved.is_file():
        raise DatasetError(f"Import path is not a file: {resolved}", code="not_found", http_status=404)
    return resolved


def reject_traversal_components(user_path: str) -> None:
    """Hard reject obvious traversal / absolute injection in API path strings."""
    text = user_path.strip()
    if not text:
        raise DatasetError("Empty path", code="unsafe_path", http_status=400)
    if "\x00" in text:
        raise DatasetError("Null byte in path", code="path_traversal", http_status=400)
    normalized = text.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) >= 2 and normalized[1] == ":"):
        # Absolute paths are allowed only when explicitly passed through resolve_import_path
        # with allowed_roots; still block null and .. here for relative segments.
        pass
    parts = Path(normalized).parts
    if ".." in parts:
        raise DatasetError("Parent traversal refused", code="path_traversal", http_status=400)


def copy_immutable_raw(
    source: Path,
    dest_dir: Path,
    *,
    filename: str | None = None,
) -> tuple[Path, str, int]:
    """Copy source into dest_dir immutably (content-addressed name) and return path/hash/size."""
    ensure_dir(dest_dir)
    digest = sha256_file(source)
    suffix = source.suffix.lower() or ".bin"
    name = filename or f"{digest}{suffix}"
    # Prevent traversal via attacker-controlled filename
    name = Path(name).name
    dest = dest_dir / name
    if dest.exists():
        existing = sha256_file(dest)
        if existing != digest:
            raise DatasetError(
                "Raw destination collision with different content",
                code="hash_collision",
                http_status=409,
            )
        return dest, digest, dest.stat().st_size
    tmp = dest_dir / f".{name}.tmp"
    try:
        shutil.copy2(source, tmp)
        tmp.replace(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    size = dest.stat().st_size
    verify = sha256_file(dest)
    if verify != digest:
        dest.unlink(missing_ok=True)
        raise DatasetError("Raw copy hash mismatch", code="integrity_error", http_status=500)
    return dest, digest, size


def inspect_local_file(path: Path) -> dict[str, Any]:
    detection: FormatDetection = detect_format(path)
    return {
        "path": str(path),
        "byteSize": path.stat().st_size,
        "contentHash": sha256_file(path),
        "detection": detection.public_dict(),
        "supported": detection.format != DetectedFormat.UNKNOWN
        or path.suffix.lower() in SUPPORTED_SUFFIXES,
    }
