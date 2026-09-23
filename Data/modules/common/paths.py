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


def normalize_path_key(path: str | Path) -> str:
    """Stable identity key for local paths (Windows-safe).

    ``D:\\ModelData\\foo``, ``d:/ModelData/foo``, and ``D:\\ModelData\\foo\\``
    collapse to the same key. Never requires reading file contents.
    """
    text = str(path).replace("\\", "/").strip()
    if not text:
        return ""
    # Preserve Windows drive-letter identity without resolving against a foreign CWD
    # (e.g. Linux CI hosting a configured ``D:/ModelData`` root).
    if len(text) >= 2 and text[1] == ":":
        return (text[0].upper() + text[1:]).rstrip("/").casefold()
    raw = Path(text)
    try:
        resolved = raw.resolve()
        text = str(resolved).replace("\\", "/")
    except OSError:
        if not raw.is_absolute():
            text = str((Path.cwd() / raw)).replace("\\", "/")
    return text.rstrip("/").casefold()


def path_under_root(root: Path, target: Path, *, follow_symlinks: bool = False) -> bool:
    """Return True when ``target`` is under ``root`` without escaping."""
    try:
        root_res = root.resolve() if follow_symlinks or root.exists() else root.absolute()
        target_res = target.resolve() if follow_symlinks or target.exists() else target.absolute()
        safe_relpath(root_res, target_res)
        return True
    except (OSError, PathEscapeError, ValueError):
        # Fallback string prefix for non-existent Windows-style roots in tests.
        root_key = normalize_path_key(root)
        target_key = normalize_path_key(target)
        if not root_key or not target_key:
            return False
        return target_key == root_key or target_key.startswith(root_key.rstrip("/") + "/")
