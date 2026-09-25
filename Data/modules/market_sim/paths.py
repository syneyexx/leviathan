"""Cross-platform path helpers for market_sim workers/sandboxes (T11 / G47)."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath


def normalize_market_path(raw: str | os.PathLike[str], *, root: str | os.PathLike[str] | None = None) -> Path:
    """Normalize a market data / sandbox path for Linux, macOS, and Windows.

    Accepts mixed separators and Windows drive forms; returns an absolute ``Path``
    when ``root`` is provided, otherwise a cleaned relative/absolute Path.
    """
    text = str(raw).strip().replace("\\", "/")
    # Strip Windows drive letter for join under an explicit root.
    if len(text) >= 2 and text[1] == ":" and text[0].isalpha():
        text = text[2:].lstrip("/")
    pure = PurePosixPath(text)
    if ".." in pure.parts:
        raise ValueError(f"path escapes markets root: {raw}")
    parts = [p for p in pure.parts if p not in {"", "."}]
    rel = Path(*parts) if parts else Path(".")
    if root is None:
        return rel
    base = Path(root).expanduser().resolve()
    out = (base / rel).resolve()
    # Containment: refuse escape outside root.
    try:
        out.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"path escapes markets root: {raw}") from exc
    return out


def windows_style_to_posix(raw: str) -> str:
    """Convert a Windows-style path string to posix form (for manifests/tests)."""
    return PureWindowsPath(raw).as_posix()


def job_sandbox_dir(base: str | os.PathLike[str], job_id: str) -> Path:
    """Stable per-job sandbox directory (safe on Windows MAX_PATH-ish ids)."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(job_id))[:120]
    return normalize_market_path(safe, root=base)
