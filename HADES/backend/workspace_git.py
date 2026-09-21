"""Bounded Git helpers for an approved workspace root.

Uses argv arrays + shell=False. Never injects credentials. Supports status,
branch, dirty files, diff, and explicit commit only — no push/merge/rebase/force.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from path_boundary import resolve_root


def _git_binary() -> str | None:
    return shutil.which("git") or shutil.which("git.exe")


def _run_git(root: Path, args: list[str], *, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    binary = _git_binary()
    if not binary:
        raise FileNotFoundError("git_not_found")
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SystemRoot": os.environ.get("SystemRoot", ""),
        "LANG": "C",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "",
        "GCM_INTERACTIVE": "never",
    }
    # Strip empty Windows-only keys
    env = {k: v for k, v in env.items() if v}
    argv = [binary, "-c", "safe.directory=*", *args]
    return subprocess.run(  # noqa: S603
        argv,
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
        env=env,
        check=False,
    )


def workspace_git_status(root: Path | str, *, timeout: float = 30.0) -> dict[str, Any]:
    resolved = resolve_root(root)
    if not resolved.is_dir():
        raise FileNotFoundError(resolved)
    if not _git_binary():
        return {
            "is_git": False,
            "error": "git_not_found",
            "message": "Git binary niet gevonden op PATH.",
            "root": str(resolved),
        }
    probe = _run_git(resolved, ["rev-parse", "--is-inside-work-tree"], timeout=timeout)
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        return {
            "is_git": False,
            "error": "not_a_git_repository",
            "message": "Pad is geen Git-repository.",
            "root": str(resolved),
            "stderr": (probe.stderr or "").strip()[:400],
        }
    branch_proc = _run_git(resolved, ["branch", "--show-current"], timeout=timeout)
    status_proc = _run_git(resolved, ["status", "--porcelain=v1", "-b"], timeout=timeout)
    diff_proc = _run_git(resolved, ["diff", "--no-color", "HEAD"], timeout=timeout)
    branch = branch_proc.stdout.strip() or None
    dirty: list[dict[str, str]] = []
    for line in (status_proc.stdout or "").splitlines():
        if line.startswith("##"):
            continue
        if len(line) < 4:
            continue
        code = line[:2]
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[-1].strip()
        dirty.append({"code": code, "path": path})
    return {
        "is_git": True,
        "root": str(resolved),
        "branch": branch,
        "dirty": dirty,
        "dirty_count": len(dirty),
        "diff": diff_proc.stdout or "",
        "status_text": status_proc.stdout or "",
        "ok": status_proc.returncode == 0,
    }


def workspace_git_commit(
    root: Path | str,
    *,
    message: str,
    approved: bool,
    timeout: float = 60.0,
) -> dict[str, Any]:
    if not approved:
        raise PermissionError("Commit vereist expliciete goedkeuring.")
    text = str(message or "").strip()
    if not text:
        raise ValueError("Commit message ontbreekt.")
    if "\x00" in text:
        raise ValueError("Ongeldige commit message.")
    status = workspace_git_status(root, timeout=timeout)
    if not status.get("is_git"):
        return {**status, "committed": False}
    if not status.get("dirty"):
        return {
            "is_git": True,
            "committed": False,
            "error": "nothing_to_commit",
            "message": "Geen dirty bestanden om te committen.",
            "root": status["root"],
            "branch": status.get("branch"),
        }
    # Stage tracked + untracked within repo (still no force/push).
    add_proc = _run_git(resolve_root(root), ["add", "-A"], timeout=timeout)
    if add_proc.returncode != 0:
        return {
            "is_git": True,
            "committed": False,
            "error": "git_add_failed",
            "message": (add_proc.stderr or add_proc.stdout or "git add mislukt").strip()[:500],
            "root": status["root"],
            "branch": status.get("branch"),
        }
    commit_proc = _run_git(resolve_root(root), ["commit", "-m", text], timeout=timeout)
    if commit_proc.returncode != 0:
        return {
            "is_git": True,
            "committed": False,
            "error": "git_commit_failed",
            "message": (commit_proc.stderr or commit_proc.stdout or "git commit mislukt").strip()[:500],
            "root": status["root"],
            "branch": status.get("branch"),
        }
    return {
        "is_git": True,
        "committed": True,
        "root": status["root"],
        "branch": status.get("branch"),
        "message": text,
        "stdout": (commit_proc.stdout or "").strip()[:500],
    }
