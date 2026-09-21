"""Open a workspace-scoped file in a local GUI editor (VS Code / Cursor).

Fail-closed: only known editor binaries, argv arrays, shell=False, path must
remain inside the approved workspace root. No arbitrary-command endpoint.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from path_boundary import join_within_root, path_within_root, resolve_root

_EDITOR_CANDIDATES = ("cursor", "cursor.cmd", "code", "code.cmd")


def resolve_editor_binary() -> str | None:
    for name in _EDITOR_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    return None


def open_in_external_editor(root: Path | str, *, relative: str) -> dict[str, Any]:
    resolved_root = resolve_root(root)
    rel = str(relative or "").replace("\\", "/").strip().strip("/")
    if not rel:
        raise ValueError("relative path ontbreekt")
    target = join_within_root(resolved_root, rel)
    if not path_within_root(target, resolved_root):
        raise ValueError(f"Pad buiten scope: {relative}")
    if target.is_symlink() and not path_within_root(target.resolve(strict=False), resolved_root):
        raise ValueError(f"Pad buiten scope: {relative}")
    if not target.exists():
        raise FileNotFoundError(rel)

    binary = resolve_editor_binary()
    if not binary:
        return {
            "opened": False,
            "error": "editor_not_found",
            "message": "Geen VS Code/Cursor op PATH (code/cursor).",
            "path": rel,
            "root": str(resolved_root),
        }

    argv = [binary, str(target)]
    try:
        subprocess.Popen(argv, shell=False, cwd=str(resolved_root))  # noqa: S603 — fixed argv, no shell
    except OSError as exc:
        return {
            "opened": False,
            "error": "spawn_failed",
            "message": f"Editor starten mislukt: {exc}",
            "path": rel,
            "root": str(resolved_root),
            "editor": binary,
            "argv": argv,
        }
    return {
        "opened": True,
        "path": rel,
        "root": str(resolved_root),
        "editor": binary,
        "argv": argv,
    }
