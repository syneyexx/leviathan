"""Shared resolved-root / containment helpers for workspace-scoped file access.

Use these helpers whenever HADES reads, hashes, copies or enumerates paths under
an approved workspace/worktree. Symlink targets that resolve outside the root
must fail closed.
"""

from __future__ import annotations

import os
import re
from pathlib import Path


_UNSAFE_RUN_ID = re.compile(r"[\\/]|^\.\.($|.)|\.\.")


def resolve_root(root: Path | str) -> Path:
    return Path(root).expanduser().resolve(strict=False)


def path_within_root(path: Path | str, root: Path | str) -> bool:
    """True when ``path`` resolves inside ``root`` (symlink-aware, fail-closed)."""
    try:
        resolved_root = resolve_root(root)
        resolved_path = Path(path).resolve(strict=False)
        resolved_path.relative_to(resolved_root)
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def resolve_within_root(path: Path | str, root: Path | str) -> Path | None:
    """Resolve ``path`` and return it only when it stays inside ``root``."""
    try:
        resolved_root = resolve_root(root)
        resolved_path = Path(path).resolve(strict=False)
        resolved_path.relative_to(resolved_root)
        return resolved_path
    except (OSError, RuntimeError, ValueError):
        return None


def join_within_root(root: Path | str, rel: str) -> Path:
    """Join a relative path under root; raise ValueError on escape/absolute input."""
    candidate = Path(rel)
    if candidate.is_absolute() or candidate.drive:
        raise ValueError("Absolute paden zijn niet toegestaan.")
    # Reject Windows-style drive / UNC fragments and parent escapes before resolve.
    raw = str(rel).replace("\\", "/")
    first = Path(raw).parts[0] if Path(raw).parts else ""
    if raw.startswith("/") or (first and ":" in first):
        raise ValueError(f"Pad buiten scope: {rel}")
    resolved_root = resolve_root(root)
    resolved = (resolved_root / candidate).resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"Pad buiten scope: {rel}") from exc
    # Extra Windows-safe commonpath check for mixed separators / short-name quirks.
    if os.path.commonpath([str(resolved), str(resolved_root)]) != str(resolved_root):
        raise ValueError(f"Pad buiten scope: {rel}")
    return resolved


def validate_run_id(run_id: str) -> str:
    """Reject run IDs that can escape a runs_root via separators or parent segments."""
    text = str(run_id or "").strip()
    if not text:
        raise ValueError("run_id ontbreekt")
    if _UNSAFE_RUN_ID.search(text) or text in {".", ".."}:
        raise ValueError(f"Ongeldige run_id: {run_id}")
    if Path(text).is_absolute() or Path(text).drive:
        raise ValueError(f"Ongeldige run_id: {run_id}")
    return text


def run_dir(runs_root: Path | str, run_id: str) -> Path:
    """Return the canonical run directory under runs_root for a validated run_id."""
    safe_id = validate_run_id(run_id)
    root = resolve_root(runs_root)
    path = (root / safe_id).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"run_id buiten runs_root: {run_id}") from exc
    return path
