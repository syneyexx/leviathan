"""Path traversal / escape protection."""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath


class PathEscapeError(ValueError):
    pass


def _contains_null(text: str) -> bool:
    return "\x00" in text


def safe_join(root: Path, *parts: str) -> Path:
    """Join parts under root; raise if the result escapes root."""
    root = Path(root).resolve()
    if any(_contains_null(part) for part in parts):
        raise PathEscapeError("Null byte in path component")
    candidate = root
    for part in parts:
        # Reject absolute components and parent escapes early.
        pure = PureWindowsPath(part) if "\\" in part else PurePosixPath(part)
        if pure.is_absolute() or getattr(pure, "drive", ""):
            raise PathEscapeError(f"Absolute path component refused: {part!r}")
        if ".." in pure.parts:
            raise PathEscapeError(f"Parent traversal refused: {part!r}")
        candidate = candidate / part
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PathEscapeError(f"Path escapes root: {resolved}") from exc
    return resolved


def safe_relpath(root: Path, target: Path) -> Path:
    root = Path(root).resolve()
    target = Path(target).resolve()
    try:
        return target.relative_to(root)
    except ValueError as exc:
        raise PathEscapeError(f"Path escapes root: {target}") from exc
