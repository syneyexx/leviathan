"""Canonical bounded Coding subprocess runner.

Typed argv only (no shell=True by default). Platform-correct process-tree
termination, timeouts, env allowlist, bounded output capture.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

# Safe baseline environment keys for coding toolchains.
DEFAULT_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {
        "PATH",
        "PATHEXT",
        "HOME",
        "USERPROFILE",
        "USER",
        "USERNAME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "TEMP",
        "TMP",
        "TMPDIR",
        "SYSTEMROOT",
        "COMSPEC",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "WINDIR",
        "TERM",
        "GIT_TERMINAL_PROMPT",
        "GIT_LFS_SKIP_SMUDGE",
        "GIT_CONFIG_NOSYSTEM",
        "GIT_CONFIG_GLOBAL",
        "CARGO_HOME",
        "RUSTUP_HOME",
        "GOPATH",
        "GOROOT",
        "NODE_ENV",
        "npm_config_cache",
    }
)

_MAX_CAPTURE_BYTES_DEFAULT = 20_000


@dataclass
class ProcessResult:
    exit_code: int
    stdout: str
    stderr: str
    argv: list[str]
    cwd: str
    status: str  # PASSED | FAILED | TIMEOUT | CANCELLED | REJECTED
    duration_seconds: float
    process_killed: bool = False
    error: str | None = None
    stdout_artifact_id: str | None = None
    stderr_artifact_id: str | None = None
    truth: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == "PASSED" and self.exit_code == 0

    def public_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "status": self.status,
            "passed": self.passed,
            "duration_seconds": self.duration_seconds,
            "process_killed": self.process_killed,
            "error": self.error,
            "stdout_artifact_id": self.stdout_artifact_id,
            "stderr_artifact_id": self.stderr_artifact_id,
            "truth": dict(self.truth),
        }


def filter_environment(
    source: Mapping[str, str] | None = None,
    *,
    allowlist: frozenset[str] | None = None,
    extras: Mapping[str, str] | None = None,
) -> dict[str, str]:
    allow = allowlist or DEFAULT_ENV_ALLOWLIST
    base = dict(source if source is not None else os.environ)
    out: dict[str, str] = {}
    for key in allow:
        val = base.get(key)
        if val:
            out[key] = val
    if extras:
        for key, val in extras.items():
            if val is not None:
                out[str(key)] = str(val)
    return out


def _is_windows() -> bool:
    return os.name == "nt" or sys.platform.startswith("win")


def kill_process_tree(proc: subprocess.Popen[Any], *, grace_seconds: float = 0.5) -> bool:
    """Kill the process and its descendants. Returns True if a kill was attempted."""
    if proc.poll() is not None:
        return False
    pid = proc.pid
    killed = False
    if _is_windows():
        # Prefer taskkill /T so child compilers/npm/git helpers die with the parent.
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=15,
                check=False,
            )
            killed = True
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
                killed = True
            except OSError:
                pass
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
            killed = True
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
                killed = True
            except OSError:
                pass
    if grace_seconds > 0:
        deadline = time.monotonic() + grace_seconds
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if proc.poll() is None:
            try:
                proc.kill()
                killed = True
            except OSError:
                pass
    return killed


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    half = max(1, limit // 2 - 20)
    return text[:half] + "\n...[truncated]...\n" + text[-half:]


def run_argv(
    argv: Sequence[str],
    *,
    cwd: str | Path,
    timeout_seconds: float = 120.0,
    env: Mapping[str, str] | None = None,
    env_allowlist: frozenset[str] | None = None,
    env_extras: Mapping[str, str] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    max_capture_bytes: int = _MAX_CAPTURE_BYTES_DEFAULT,
    expected_exit_code: int = 0,
    purpose: str = "coding.process",
) -> ProcessResult:
    """Run an explicit argv list with timeout, cancel, and process-tree kill.

    Never uses shell=True. Success requires exit_code == expected_exit_code.
    """
    if not argv:
        return ProcessResult(
            exit_code=126,
            stdout="",
            stderr="empty argv",
            argv=[],
            cwd=str(cwd),
            status="REJECTED",
            duration_seconds=0.0,
            error="empty_argv",
            truth={"shell": False, "purpose": purpose},
        )
    # Reject option-shaped first token that looks like a shell invocation.
    first = str(argv[0] or "")
    if first in {"sh", "bash", "zsh", "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh"}:
        return ProcessResult(
            exit_code=126,
            stdout="",
            stderr=f"shell interpreter refused: {first}",
            argv=[str(a) for a in argv],
            cwd=str(cwd),
            status="REJECTED",
            duration_seconds=0.0,
            error="shell_refused",
            truth={"shell": False, "purpose": purpose},
        )

    work = Path(cwd)
    if not work.exists() or not work.is_dir():
        return ProcessResult(
            exit_code=126,
            stdout="",
            stderr=f"cwd missing or not a directory: {work}",
            argv=[str(a) for a in argv],
            cwd=str(work),
            status="REJECTED",
            duration_seconds=0.0,
            error="cwd_invalid",
            truth={"shell": False, "purpose": purpose},
        )

    run_env = filter_environment(env, allowlist=env_allowlist, extras=env_extras)
    # Non-interactive Git / tooling by default.
    run_env.setdefault("GIT_TERMINAL_PROMPT", "0")

    creationflags = 0
    start_new_session = False
    if _is_windows():
        creationflags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    else:
        start_new_session = True

    timeout = max(0.1, float(timeout_seconds))
    started = time.monotonic()
    proc: subprocess.Popen[str] | None = None
    argv_list = [str(a) for a in argv]
    try:
        proc = subprocess.Popen(
            argv_list,
            cwd=str(work),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=run_env,
            start_new_session=start_new_session,
            creationflags=creationflags,
        )
    except FileNotFoundError as exc:
        return ProcessResult(
            exit_code=127,
            stdout="",
            stderr=str(exc),
            argv=argv_list,
            cwd=str(work),
            status="FAILED",
            duration_seconds=time.monotonic() - started,
            error=f"executable_missing: {exc}",
            truth={"shell": False, "purpose": purpose},
        )
    except OSError as exc:
        return ProcessResult(
            exit_code=126,
            stdout="",
            stderr=str(exc),
            argv=argv_list,
            cwd=str(work),
            status="FAILED",
            duration_seconds=time.monotonic() - started,
            error=f"spawn_failed: {exc}",
            truth={"shell": False, "purpose": purpose},
        )

    assert proc is not None
    stdout = ""
    stderr = ""
    status = "FAILED"
    killed = False
    error: str | None = None
    exit_code = -1

    try:
        deadline = started + timeout
        while True:
            if callable(cancel_check) and cancel_check():
                killed = kill_process_tree(proc)
                try:
                    stdout, stderr = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    kill_process_tree(proc)
                    stdout, stderr = proc.communicate()
                status = "CANCELLED"
                error = "cancelled"
                exit_code = int(proc.returncode if proc.returncode is not None else -1)
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                killed = kill_process_tree(proc)
                try:
                    stdout, stderr = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    kill_process_tree(proc)
                    stdout, stderr = proc.communicate()
                status = "TIMEOUT"
                error = f"timeout after {timeout}s"
                exit_code = 124
                break
            try:
                stdout, stderr = proc.communicate(timeout=min(0.25, remaining))
                exit_code = int(proc.returncode if proc.returncode is not None else 0)
                if exit_code == expected_exit_code:
                    status = "PASSED"
                else:
                    status = "FAILED"
                break
            except subprocess.TimeoutExpired:
                continue
    finally:
        if proc.poll() is None:
            killed = kill_process_tree(proc) or killed

    duration = time.monotonic() - started
    return ProcessResult(
        exit_code=exit_code,
        stdout=_truncate(stdout or "", max_capture_bytes),
        stderr=_truncate(stderr or "", max_capture_bytes),
        argv=argv_list,
        cwd=str(work),
        status=status,
        duration_seconds=duration,
        process_killed=killed,
        error=error,
        truth={
            "shell": False,
            "purpose": purpose,
            "process_tree_kill": True,
            "windows": _is_windows(),
            "exit_code_is_authority": True,
        },
    )
