"""Canonical low-level process-control helpers.

Shared utilities only — NEVER a semantic execution owner. Callers remain
responsible for ownership (model_runtime, mcp_execution, module_runtime,
native_compute, coding, sandbox probes).
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from typing import Any, Mapping

# Baseline host keys safe for untrusted / external children.
DEFAULT_CHILD_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {
        "PATH",
        "PATHEXT",
        "HOME",
        "USERPROFILE",
        "USER",
        "USERNAME",
        "LOGNAME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TEMP",
        "TMP",
        "TMPDIR",
        "SYSTEMROOT",
        "COMSPEC",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "WINDIR",
        "TERM",
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "NODE_ENV",
        "npm_config_cache",
        "GIT_TERMINAL_PROMPT",
        "GIT_LFS_SKIP_SMUDGE",
        "GIT_CONFIG_NOSYSTEM",
        "GIT_CONFIG_GLOBAL",
        "CARGO_HOME",
        "RUSTUP_HOME",
        "GOPATH",
        "GOROOT",
    }
)

_SECRET_KEY_RE = re.compile(
    r"(API[_-]?KEY|TOKEN|PASSWORD|SECRET|PRIVATE[_-]?KEY|AUTHORIZATION|CREDENTIAL|"
    r"AWS_|AZURE_|GCP_|OPENAI_|ANTHROPIC_|HF_TOKEN|DATABASE_URL|DSN)",
    re.IGNORECASE,
)


def is_windows() -> bool:
    return os.name == "nt" or sys.platform.startswith("win")


def is_secret_env_key(key: str) -> bool:
    return bool(_SECRET_KEY_RE.search(str(key or "")))


def scrub_child_environment(
    source: Mapping[str, str] | None = None,
    *,
    allowlist: frozenset[str] | None = None,
    extras: Mapping[str, str] | None = None,
    inherit_all: bool = False,
) -> dict[str, str]:
    """Build a child environment without ambient secrets.

    Default: allowlisted keys only. ``inherit_all=True`` still strips secret-shaped
    keys unless they appear in ``extras`` (explicit lease).
    """
    base = dict(source if source is not None else os.environ)
    out: dict[str, str] = {}
    if inherit_all:
        for key, val in base.items():
            if val is None:
                continue
            if is_secret_env_key(key):
                continue
            out[str(key)] = str(val)
    else:
        allow = allowlist or DEFAULT_CHILD_ENV_ALLOWLIST
        for key in allow:
            val = base.get(key)
            if val:
                out[key] = val
    if extras:
        for key, val in extras.items():
            if val is not None:
                out[str(key)] = str(val)
    return out


def owned_child_popen_kwargs() -> dict[str, Any]:
    """Platform flags so we can terminate the owned process tree later."""
    if is_windows():
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return {"creationflags": flags} if flags else {}
    return {"start_new_session": True}


def kill_process_tree(
    proc: subprocess.Popen[Any] | None = None,
    *,
    pid: int | None = None,
    grace_seconds: float = 0.5,
) -> bool:
    """Kill an owned process and its descendants. Returns True if kill attempted."""
    target_pid = pid
    if proc is not None:
        if proc.poll() is not None and pid is None:
            return False
        target_pid = int(proc.pid)
    if not isinstance(target_pid, int) or target_pid <= 0:
        return False

    killed = False
    if is_windows():
        try:
            subprocess.run(
                ["taskkill", "/PID", str(target_pid), "/T", "/F"],
                capture_output=True,
                timeout=15,
                check=False,
            )
            killed = True
        except (OSError, subprocess.TimeoutExpired):
            if proc is not None:
                try:
                    proc.kill()
                    killed = True
                except OSError:
                    pass
    else:
        try:
            os.killpg(os.getpgid(target_pid), signal.SIGKILL)
            killed = True
        except (ProcessLookupError, PermissionError, OSError):
            if proc is not None:
                try:
                    proc.kill()
                    killed = True
                except OSError:
                    pass
            else:
                try:
                    os.kill(target_pid, signal.SIGKILL)
                    killed = True
                except OSError:
                    pass
    if grace_seconds > 0:
        time.sleep(min(grace_seconds, 0.5))
    return killed


def terminate_owned_process(
    proc: subprocess.Popen[Any],
    *,
    graceful_timeout_seconds: float = 5.0,
    force_timeout_seconds: float = 3.0,
) -> dict[str, Any]:
    """Graceful stop of a LEVIATHAN-owned Popen, then force process-tree kill.

    Never targets an arbitrary PID alone — only the Popen we own (or its tree
    after ownership is proven by the caller).
    """
    if proc.poll() is not None:
        return {
            "alreadyExited": True,
            "returncode": proc.returncode,
            "forced": False,
            "stillAlive": False,
        }

    forced = False
    try:
        if is_windows():
            proc.terminate()
        else:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                proc.terminate()
    except Exception:  # noqa: BLE001
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass

    try:
        proc.wait(timeout=max(0.1, float(graceful_timeout_seconds)))
        return {
            "alreadyExited": False,
            "returncode": proc.returncode,
            "forced": False,
            "stillAlive": False,
        }
    except subprocess.TimeoutExpired:
        forced = True

    kill_process_tree(proc, grace_seconds=0.1)
    try:
        proc.wait(timeout=max(0.1, float(force_timeout_seconds)))
    except subprocess.TimeoutExpired:
        return {
            "alreadyExited": False,
            "returncode": None,
            "forced": forced,
            "stillAlive": True,
        }
    return {
        "alreadyExited": False,
        "returncode": proc.returncode,
        "forced": forced,
        "stillAlive": False,
    }


def terminate_owned_pid(
    pid: int,
    *,
    fingerprint: str | None = None,
    expected_fingerprint: str | None = None,
    grace_seconds: float = 5.0,
    force: bool = True,
) -> dict[str, Any]:
    """Terminate by PID only when fingerprint ownership is proven.

    If ownership is unproven, returns OWNERSHIP_UNPROVEN and does not kill.
    """
    from Data.modules.common.process import pid_fingerprint, pid_is_alive

    if not isinstance(pid, int) or pid <= 0:
        return {"killed": False, "reason": "invalid_pid"}
    if not pid_is_alive(pid):
        return {"killed": False, "reason": "already_dead", "stillAlive": False}

    expected = expected_fingerprint or fingerprint
    if expected:
        current = pid_fingerprint(pid)
        if not current or current != expected:
            return {
                "killed": False,
                "reason": "OWNERSHIP_UNPROVEN",
                "code": "OWNERSHIP_UNPROVEN",
                "stillAlive": True,
                "pid": pid,
            }

    try:
        if is_windows():
            # Soft terminate via taskkill without /F first when possible.
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T"],
                capture_output=True,
                timeout=15,
                check=False,
            )
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                os.kill(pid, signal.SIGTERM)
    except OSError:
        pass

    deadline = time.monotonic() + max(0.1, float(grace_seconds))
    while time.monotonic() < deadline and pid_is_alive(pid):
        time.sleep(0.1)

    if pid_is_alive(pid) and force:
        # Re-check fingerprint before force kill.
        if expected:
            current = pid_fingerprint(pid)
            if current != expected:
                return {
                    "killed": False,
                    "reason": "OWNERSHIP_UNPROVEN",
                    "code": "OWNERSHIP_UNPROVEN",
                    "stillAlive": True,
                    "pid": pid,
                }
        kill_process_tree(pid=pid, grace_seconds=0.1)

    alive = pid_is_alive(pid)
    return {
        "killed": not alive,
        "reason": "terminated" if not alive else "still_alive",
        "stillAlive": alive,
        "pid": pid,
        "forced": force and not alive,
    }
