#!/usr/bin/env python3
"""Git worktree tools for parallel HADES / agent work (worktrunk-compatible operations)."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def _git() -> str | None:
    return shutil.which("git") or shutil.which("git.exe")


def _run(args: list[str], cwd: str | None = None, timeout: int = 60) -> dict:
    git = _git()
    if not git:
        return {"ok": False, "error": "git_not_found", "hint": "Install Git and ensure it is on PATH."}
    command = [git, *args]
    process = subprocess.run(
        command,
        cwd=cwd or None,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )
    return {
        "ok": process.returncode == 0,
        "command": command,
        "exit_code": process.returncode,
        "stdout": (process.stdout or "")[-20_000:],
        "stderr": (process.stderr or "")[-20_000:],
    }


def doctor() -> dict:
    git = _git()
    payload = _run(["--version"]) if git else {"ok": False, "error": "git_not_found"}
    payload["git"] = git
    payload["python"] = sys.executable
    payload["notes"] = [
        "HADES uses git worktree directly so this works without the Rust worktrunk binary.",
        "add/remove change the local git workspace — autonomous use is disabled.",
    ]
    return payload


def list_worktrees(repo: str) -> dict:
    payload = _run(["worktree", "list", "--porcelain"], cwd=repo or None)
    if not payload.get("ok"):
        payload["error"] = payload.get("error") or "worktree_list_failed"
        return payload
    items = []
    current: dict[str, str] = {}
    for line in (payload.get("stdout") or "").splitlines():
        if not line.strip():
            if current:
                items.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            current["path"] = line.split(" ", 1)[1]
        elif line.startswith("HEAD "):
            current["head"] = line.split(" ", 1)[1]
        elif line.startswith("branch "):
            current["branch"] = line.split(" ", 1)[1]
        elif line == "bare":
            current["bare"] = "true"
        elif line == "detached":
            current["detached"] = "true"
    if current:
        items.append(current)
    payload["worktrees"] = items
    payload["count"] = len(items)
    return payload


def add_worktree(repo: str, path: str, branch: str, start_point: str, create_branch: bool) -> dict:
    dest = Path(path).expanduser()
    args = ["worktree", "add"]
    if create_branch:
        if not branch.strip():
            return {"ok": False, "error": "branch_required"}
        args.extend(["-b", branch.strip()])
    args.append(str(dest))
    if start_point.strip():
        args.append(start_point.strip())
    elif branch.strip() and not create_branch:
        args.append(branch.strip())
    payload = _run(args, cwd=repo or None)
    payload["path"] = str(dest)
    if not payload.get("ok"):
        payload["error"] = payload.get("error") or "worktree_add_failed"
    return payload


def remove_worktree(repo: str, path: str, force: bool) -> dict:
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(path)
    payload = _run(args, cwd=repo or None)
    if not payload.get("ok"):
        payload["error"] = payload.get("error") or "worktree_remove_failed"
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES git worktree bridge")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    lst = sub.add_parser("list")
    lst.add_argument("--repo", default="")
    add = sub.add_parser("add")
    add.add_argument("--repo", default="")
    add.add_argument("--path", required=True)
    add.add_argument("--branch", default="")
    add.add_argument("--start-point", default="")
    add.add_argument("--create-branch", default="false")
    rm = sub.add_parser("remove")
    rm.add_argument("--repo", default="")
    rm.add_argument("--path", required=True)
    rm.add_argument("--force", default="false")
    args = parser.parse_args()
    if args.cmd == "doctor":
        payload = doctor()
    elif args.cmd == "list":
        payload = list_worktrees(args.repo)
    elif args.cmd == "add":
        payload = add_worktree(
            args.repo,
            args.path,
            args.branch,
            args.start_point,
            str(args.create_branch).lower() in {"1", "true", "yes"},
        )
    else:
        payload = remove_worktree(args.repo, args.path, str(args.force).lower() in {"1", "true", "yes"})
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
