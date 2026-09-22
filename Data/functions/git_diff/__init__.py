from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def run(path: str | None = None, *, staged: bool = False) -> dict[str, Any]:
    """Return git diff. Honest FAILED when .git is missing."""
    root = Path(path).expanduser() if path else Path.cwd()
    target_path = None
    if root.is_file():
        target_path = root
        root = root.parent
    git_dir = root / ".git"
    # Walk up a few levels to find .git
    probe = root
    for _ in range(6):
        if (probe / ".git").exists():
            root = probe
            git_dir = probe / ".git"
            break
        if probe.parent == probe:
            break
        probe = probe.parent

    if not git_dir.exists():
        return {
            "status": "FAILED",
            "error": "no .git directory — not a git repository",
            "path": str(root),
            "diff": "",
            "staged": staged,
        }

    argv = ["git", "diff"]
    if staged:
        argv.append("--cached")
    if target_path is not None:
        argv.append("--")
        argv.append(str(target_path))

    try:
        proc = subprocess.run(
            argv,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except FileNotFoundError:
        return {
            "status": "FAILED",
            "error": "git executable not found",
            "path": str(root),
            "diff": "",
            "staged": staged,
        }
    if proc.returncode != 0:
        return {
            "status": "FAILED",
            "error": (proc.stderr or "git diff failed")[:2000],
            "path": str(root),
            "diff": "",
            "staged": staged,
            "exit_code": proc.returncode,
        }
    return {
        "status": "COMPLETED",
        "path": str(root),
        "diff": (proc.stdout or "")[:100_000],
        "staged": staged,
    }
