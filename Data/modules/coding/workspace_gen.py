"""Repository generation fingerprint for semantic maps / verification receipts."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorkspaceGeneration:
    """Identifies repository/workspace state for staleness detection."""

    workspace_root: str
    kind: str  # git | workspace
    head_commit: str | None
    dirty: bool
    fingerprint: str
    algorithm_version: str = "coding.gen.v1"

    def public_dict(self) -> dict[str, Any]:
        return {
            "workspace_root": self.workspace_root,
            "kind": self.kind,
            "head_commit": self.head_commit,
            "dirty": self.dirty,
            "fingerprint": self.fingerprint,
            "algorithm_version": self.algorithm_version,
        }

    def matches(self, other: "WorkspaceGeneration | None") -> bool:
        if other is None:
            return False
        return (
            self.fingerprint == other.fingerprint
            and self.algorithm_version == other.algorithm_version
            and self.workspace_root == other.workspace_root
        )


def _run_git(root: Path, *args: str, timeout: float = 15.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={
                "PATH": __import__("os").environ.get("PATH", ""),
                "GIT_TERMINAL_PROMPT": "0",
                "LANG": "C.UTF-8",
            },
        )
        return int(proc.returncode or 0), (proc.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""


def capture_workspace_generation(workspace_root: Path | str) -> WorkspaceGeneration:
    """Capture a cheap generation fingerprint for a workspace."""
    root = Path(workspace_root).resolve()
    root_s = str(root)
    git_dir = root / ".git"
    if git_dir.exists():
        code, head = _run_git(root, "rev-parse", "HEAD")
        head_commit = head if code == 0 and head else None
        code2, status = _run_git(root, "status", "--porcelain")
        dirty = bool(status) if code2 == 0 else True
        # Include a bounded dirty summary hash — not full file contents.
        dirty_hash = hashlib.sha256(status.encode("utf-8", errors="replace")).hexdigest()[:16]
        fp_src = f"git|{head_commit or 'unknown'}|{int(dirty)}|{dirty_hash}"
        fingerprint = hashlib.sha256(fp_src.encode("utf-8")).hexdigest()[:32]
        return WorkspaceGeneration(
            workspace_root=root_s,
            kind="git",
            head_commit=head_commit,
            dirty=dirty,
            fingerprint=fingerprint,
        )

    # Non-git: cheap top-level + bounded mtime/size sample.
    h = hashlib.sha256()
    h.update(b"workspace|")
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name.lower())[:200]
    except OSError:
        entries = []
    for item in entries:
        try:
            st = item.stat()
            h.update(item.name.encode("utf-8", errors="replace"))
            h.update(str(int(st.st_mtime_ns)).encode("ascii"))
            h.update(str(int(st.st_size)).encode("ascii"))
        except OSError:
            continue
    return WorkspaceGeneration(
        workspace_root=root_s,
        kind="workspace",
        head_commit=None,
        dirty=False,
        fingerprint=h.hexdigest()[:32],
    )
