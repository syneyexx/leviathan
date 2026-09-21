from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def run(path: str | None = None) -> dict[str, Any]:
    """Return git status. Honest empty/FAILED when .git is missing."""
    root = Path(path).expanduser() if path else Path.cwd()
    if root.is_file():
        root = root.parent
    git_dir = root / ".git"
    if not git_dir.exists():
        return {
            "status": "FAILED",
            "error": "no .git directory — not a git repository",
            "path": str(root),
            "clean": None,
            "entries": [],
        }
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "-b"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        return {
            "status": "FAILED",
            "error": "git executable not found",
            "path": str(root),
            "clean": None,
            "entries": [],
        }
    if proc.returncode != 0:
        return {
            "status": "FAILED",
            "error": (proc.stderr or proc.stdout or "git status failed")[:2000],
            "path": str(root),
            "clean": None,
            "entries": [],
            "exit_code": proc.returncode,
        }
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    branch = lines[0] if lines and lines[0].startswith("##") else None
    entries = lines[1:] if branch else lines
    return {
        "status": "COMPLETED",
        "path": str(root),
        "branch": branch,
        "entries": entries,
        "clean": len(entries) == 0,
        "raw": proc.stdout or "",
    }
