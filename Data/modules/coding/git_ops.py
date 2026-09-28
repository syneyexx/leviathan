"""Coding-domain Git operations — clone / fetch / update / checkout.

Semantic ownership: coding worker only. ModuleManager installs remain separate.
Typed argv, remote validation, dirty-worktree guards, no shell, no hooks surprise.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

from Data.modules.coding.process import filter_environment, run_argv
from Data.modules.coding.types import CodingError
from Data.modules.coding.workspace import confine, is_denied
from Data.modules.coding.workspace_gen import capture_workspace_generation
from Data.modules.common.paths import PathEscapeError

_SAFE_REMOTE = re.compile(
    r"^(?:https://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%\-]+"
    r"|git@[A-Za-z0-9._\-]+:[A-Za-z0-9._/\-~]+\.git"
    r"|ssh://git@[A-Za-z0-9._\-]+[:\d]*/[A-Za-z0-9._/\-~]+)$"
)

_OPTION_SHAPED = re.compile(r"^-")


def _reject_option_shaped(value: str, *, field: str) -> str:
    text = (value or "").strip()
    if not text:
        raise CodingError("VALIDATION_ERROR", f"{field} is required", http_status=422)
    if _OPTION_SHAPED.match(text) or "\n" in text or "\x00" in text:
        raise CodingError(
            "GIT_REMOTE_INVALID" if field == "remote" else "VALIDATION_ERROR",
            f"option-shaped or unsafe {field} refused",
            http_status=400,
            details={field: text[:200]},
        )
    return text


def validate_remote(remote: str) -> str:
    text = _reject_option_shaped(remote, field="remote")
    lowered = text.lower()
    if lowered.startswith(("file://", "ext::", "fd::")):
        raise CodingError(
            "GIT_REMOTE_INVALID",
            "unsafe Git transport refused",
            http_status=400,
            details={"remote_scheme": text.split(":", 1)[0]},
        )
    if text.startswith("/") or text.startswith("\\\\") or (len(text) >= 3 and text[1] == ":"):
        raise CodingError(
            "GIT_REMOTE_INVALID",
            "local/UNC Git remotes refused",
            http_status=400,
        )
    if not _SAFE_REMOTE.match(text):
        # Allow plain https host/path without forcing .git suffix in regex — loosen slightly.
        if text.startswith("https://") and " " not in text and "'" not in text:
            return text
        raise CodingError(
            "GIT_REMOTE_INVALID",
            "remote URL failed allowlist validation",
            http_status=400,
            details={"remote": text[:200]},
        )
    return text


def _git_env() -> dict[str, str]:
    import os
    import sys

    hooks_null = "NUL" if (os.name == "nt" or sys.platform.startswith("win")) else "/dev/null"
    return filter_environment(
        extras={
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_LFS_SKIP_SMUDGE": "1",
            # Avoid repository hooks during clone/fetch/checkout.
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.hooksPath",
            "GIT_CONFIG_VALUE_0": hooks_null,
        }
    )


def _ensure_git_repo(path: Path) -> None:
    if not (path / ".git").exists():
        raise CodingError(
            "GIT_NOT_REPOSITORY",
            f"not a git repository: {path}",
            http_status=400,
        )


def _inspect_dirty(path: Path, *, cancel_check: Callable[[], bool] | None) -> dict[str, Any]:
    result = run_argv(
        ["git", "status", "--porcelain"],
        cwd=path,
        timeout_seconds=30,
        env_extras=_git_env(),
        cancel_check=cancel_check,
        purpose="coding.git.status",
    )
    if result.status == "TIMEOUT":
        raise CodingError("GIT_TIMEOUT", "git status timed out", http_status=504)
    dirty = bool((result.stdout or "").strip())
    return {"dirty": dirty, "porcelain": (result.stdout or "")[:4000]}


def git_clone(
    *,
    remote: str,
    destination: str | Path,
    workspace_root: str | Path | None = None,
    depth: int | None = None,
    cancel_check: Callable[[], bool] | None = None,
    timeout_seconds: float = 600.0,
    overwrite: bool = False,
) -> dict[str, Any]:
    remote_u = validate_remote(remote)
    dest = Path(destination)
    if workspace_root is not None:
        try:
            dest = confine(Path(workspace_root), str(dest) if not Path(destination).is_absolute() else destination)
        except PathEscapeError as exc:
            raise CodingError("WORKSPACE_DENIED", str(exc), http_status=403) from exc
    if is_denied(dest):
        raise CodingError("WORKSPACE_DENIED", f"destination denied: {dest}", http_status=403)
    if dest.exists() and any(dest.iterdir()) and not overwrite:
        raise CodingError(
            "GIT_CLONE_FAILED",
            "destination exists and is not empty",
            http_status=409,
            details={"destination": str(dest)},
        )

    parent = dest.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".lev-clone-", dir=str(parent)))
    try:
        argv = ["git", "clone", "--", remote_u, str(staging / "repo")]
        if depth is not None and int(depth) > 0:
            argv = ["git", "clone", f"--depth={int(depth)}", "--", remote_u, str(staging / "repo")]
        result = run_argv(
            argv,
            cwd=parent,
            timeout_seconds=timeout_seconds,
            env_extras=_git_env(),
            cancel_check=cancel_check,
            purpose="coding.git.clone",
        )
        if result.status == "TIMEOUT":
            raise CodingError("GIT_TIMEOUT", "git clone timed out", http_status=504)
        if result.status == "CANCELLED":
            raise CodingError("CODING_PROCESS_CANCELLED", "git clone cancelled", http_status=499)
        if not result.passed:
            raise CodingError(
                "GIT_CLONE_FAILED",
                result.stderr or result.error or "clone failed",
                http_status=400,
                details={"exit_code": result.exit_code},
            )
        cloned = staging / "repo"
        _ensure_git_repo(cloned)
        if dest.exists() and overwrite:
            shutil.rmtree(dest)
        cloned.rename(dest)
        gen = capture_workspace_generation(dest)
        return {
            "ok": True,
            "destination": str(dest),
            "remote": remote_u,
            "generation": gen.public_dict(),
            "stdout": result.stdout[:2000],
            "stderr": result.stderr[:2000],
            "executed": True,
            "truth": {"hooks_disabled": True, "lfs_smudge_skipped": True},
        }
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def git_fetch(
    *,
    repository: str | Path,
    remote: str = "origin",
    refs: list[str] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    timeout_seconds: float = 300.0,
) -> dict[str, Any]:
    repo = Path(repository)
    _ensure_git_repo(repo)
    remote_name = _reject_option_shaped(remote, field="remote")
    # Remote *name* only — not a URL (fetch from configured remote).
    if "://" in remote_name or remote_name.startswith("git@"):
        remote_name = validate_remote(remote_name)
    argv = ["git", "fetch", "--", remote_name]
    for ref in refs or []:
        argv.append(_reject_option_shaped(ref, field="ref"))
    result = run_argv(
        argv,
        cwd=repo,
        timeout_seconds=timeout_seconds,
        env_extras=_git_env(),
        cancel_check=cancel_check,
        purpose="coding.git.fetch",
    )
    if result.status == "TIMEOUT":
        raise CodingError("GIT_TIMEOUT", "git fetch timed out", http_status=504)
    if result.status == "CANCELLED":
        raise CodingError("CODING_PROCESS_CANCELLED", "git fetch cancelled", http_status=499)
    if not result.passed:
        code = "GIT_AUTH_FAILED" if "auth" in (result.stderr or "").lower() else "GIT_FETCH_FAILED"
        raise CodingError(code, result.stderr or result.error or "fetch failed", http_status=400)
    return {
        "ok": True,
        "repository": str(repo),
        "remote": remote_name,
        "refs": list(refs or []),
        "stdout": result.stdout[:2000],
        "stderr": result.stderr[:2000],
        "executed": True,
    }


def git_checkout(
    *,
    repository: str | Path,
    ref: str,
    cancel_check: Callable[[], bool] | None = None,
    timeout_seconds: float = 300.0,
    allow_dirty: bool = False,
) -> dict[str, Any]:
    repo = Path(repository)
    _ensure_git_repo(repo)
    target = _reject_option_shaped(ref, field="ref")
    dirty_info = _inspect_dirty(repo, cancel_check=cancel_check)
    if dirty_info["dirty"] and not allow_dirty:
        raise CodingError(
            "GIT_DIRTY_WORKTREE",
            "refusing checkout on dirty worktree",
            http_status=409,
            details=dirty_info,
        )

    # Resolve to SHA first.
    rev = run_argv(
        ["git", "rev-parse", "--verify", "--", target],
        cwd=repo,
        timeout_seconds=30,
        env_extras=_git_env(),
        cancel_check=cancel_check,
        purpose="coding.git.rev_parse",
    )
    if not rev.passed:
        raise CodingError("GIT_CHECKOUT_FAILED", f"ref not found: {target}", http_status=404)
    sha = (rev.stdout or "").strip()

    # Idempotent: already at target and clean.
    head = run_argv(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        timeout_seconds=15,
        env_extras=_git_env(),
        cancel_check=cancel_check,
        purpose="coding.git.rev_parse",
    )
    if head.passed and (head.stdout or "").strip() == sha and not dirty_info["dirty"]:
        return {
            "ok": True,
            "repository": str(repo),
            "ref": target,
            "commit": sha,
            "idempotent": True,
            "executed": True,
        }

    result = run_argv(
        ["git", "checkout", "--", target],
        cwd=repo,
        timeout_seconds=timeout_seconds,
        env_extras=_git_env(),
        cancel_check=cancel_check,
        purpose="coding.git.checkout",
    )
    if result.status == "TIMEOUT":
        raise CodingError("GIT_TIMEOUT", "git checkout timed out", http_status=504)
    if result.status == "CANCELLED":
        raise CodingError("CODING_PROCESS_CANCELLED", "git checkout cancelled", http_status=499)
    if not result.passed:
        raise CodingError(
            "GIT_CHECKOUT_FAILED",
            result.stderr or result.error or "checkout failed",
            http_status=400,
        )
    gen = capture_workspace_generation(repo)
    return {
        "ok": True,
        "repository": str(repo),
        "ref": target,
        "commit": sha,
        "generation": gen.public_dict(),
        "stdout": result.stdout[:2000],
        "stderr": result.stderr[:2000],
        "executed": True,
        "idempotent": False,
    }


def git_update(
    *,
    repository: str | Path,
    remote: str = "origin",
    ref: str = "HEAD",
    cancel_check: Callable[[], bool] | None = None,
    timeout_seconds: float = 300.0,
) -> dict[str, Any]:
    """Deterministic update: fetch then fast-forward only (no merge)."""
    repo = Path(repository)
    _ensure_git_repo(repo)
    dirty_info = _inspect_dirty(repo, cancel_check=cancel_check)
    if dirty_info["dirty"]:
        raise CodingError(
            "GIT_DIRTY_WORKTREE",
            "refusing update on dirty worktree",
            http_status=409,
            details=dirty_info,
        )
    fetch = git_fetch(
        repository=repo,
        remote=remote,
        cancel_check=cancel_check,
        timeout_seconds=timeout_seconds,
    )
    target = _reject_option_shaped(ref, field="ref")
    if target == "HEAD":
        # Resolve upstream tracking if possible.
        upstream = run_argv(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            cwd=repo,
            timeout_seconds=15,
            env_extras=_git_env(),
            cancel_check=cancel_check,
            purpose="coding.git.upstream",
        )
        target = (upstream.stdout or "").strip() or f"{remote}/HEAD"

    # Fast-forward only merge/reset to remote ref.
    result = run_argv(
        ["git", "merge", "--ff-only", "--", target],
        cwd=repo,
        timeout_seconds=timeout_seconds,
        env_extras=_git_env(),
        cancel_check=cancel_check,
        purpose="coding.git.update",
    )
    if result.status == "TIMEOUT":
        raise CodingError("GIT_TIMEOUT", "git update timed out", http_status=504)
    if not result.passed:
        raise CodingError(
            "GIT_UPDATE_CONFLICT",
            result.stderr or result.error or "fast-forward update failed",
            http_status=409,
            details={"fetch": fetch, "target": target},
        )
    head = run_argv(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        timeout_seconds=15,
        env_extras=_git_env(),
        cancel_check=cancel_check,
        purpose="coding.git.rev_parse",
    )
    gen = capture_workspace_generation(repo)
    return {
        "ok": True,
        "repository": str(repo),
        "target": target,
        "commit": (head.stdout or "").strip(),
        "generation": gen.public_dict(),
        "fetch": fetch,
        "executed": True,
        "truth": {"strategy": "ff-only", "no_auto_merge": True},
    }


def dispatch_git_op(
    action: str,
    args: Mapping[str, Any],
    *,
    cancel_check: Callable[[], bool] | None = None,
    settings: Any = None,
) -> dict[str, Any]:
    act = (action or "").strip().lower().removeprefix("git_")
    if act == "clone":
        return git_clone(
            remote=str(args.get("remote") or args.get("url") or ""),
            destination=str(args.get("destination") or args.get("path") or ""),
            workspace_root=args.get("workspace_root"),
            depth=args.get("depth"),
            cancel_check=cancel_check,
            timeout_seconds=float(args.get("timeout_seconds") or 600),
            overwrite=bool(args.get("overwrite")),
        )
    if act == "fetch":
        return git_fetch(
            repository=str(args.get("repository") or args.get("path") or args.get("workspace_root") or ""),
            remote=str(args.get("remote") or "origin"),
            refs=list(args.get("refs") or []) or None,
            cancel_check=cancel_check,
            timeout_seconds=float(args.get("timeout_seconds") or 300),
        )
    if act in {"checkout", "switch"}:
        return git_checkout(
            repository=str(args.get("repository") or args.get("path") or args.get("workspace_root") or ""),
            ref=str(args.get("ref") or args.get("branch") or args.get("commit") or ""),
            cancel_check=cancel_check,
            timeout_seconds=float(args.get("timeout_seconds") or 300),
            allow_dirty=bool(args.get("allow_dirty")),
        )
    if act in {"update", "pull"}:
        return git_update(
            repository=str(args.get("repository") or args.get("path") or args.get("workspace_root") or ""),
            remote=str(args.get("remote") or "origin"),
            ref=str(args.get("ref") or "HEAD"),
            cancel_check=cancel_check,
            timeout_seconds=float(args.get("timeout_seconds") or 300),
        )
    raise CodingError("VALIDATION_ERROR", f"unknown coding git action: {action}", http_status=422)
