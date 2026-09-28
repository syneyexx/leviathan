"""Cross-platform owned-process termination for managed model workers.

Delegates tree-kill / env-scrub helpers to canonical
``Data.modules.common.process_control`` — do not fork a second Windows
tree-kill policy. Local helpers cover spawn, log buffers, and wait loops.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from typing import Any

from Data.modules.common.process_control import (
    kill_process_tree,
    scrub_child_environment,
    terminate_owned_pid,
    terminate_owned_process as common_terminate_owned_process,
)

__all__ = [
    "WorkerLogBuffer",
    "drain_pipe_bounded",
    "kill_process_tree",
    "scrub_child_environment",
    "spawn_owned_process",
    "terminate_owned_pid",
    "terminate_owned_process",
    "wait_until",
]


def terminate_owned_process(
    proc: subprocess.Popen[Any],
    *,
    graceful_timeout_seconds: float = 5.0,
    force_timeout_seconds: float = 3.0,
) -> dict[str, Any]:
    """Gracefully stop a LEVIATHAN-owned subprocess tree, then force-kill if needed.

    Prefer Windows CTRL_BREAK when available; otherwise delegate to the shared
    common.process_control tree-kill path. Never targets an arbitrary PID —
    only the Popen we own.
    """
    if proc.poll() is not None:
        return {
            "alreadyExited": True,
            "returncode": proc.returncode,
            "forced": False,
            "stillAlive": False,
        }

    # Windows: try CTRL_BREAK to the process group before shared terminate.
    if os.name == "nt":
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            try:
                proc.wait(timeout=max(0.1, float(graceful_timeout_seconds)))
                return {
                    "alreadyExited": False,
                    "returncode": proc.returncode,
                    "forced": False,
                    "stillAlive": False,
                }
            except subprocess.TimeoutExpired:
                pass
        except (AttributeError, OSError, ValueError):
            pass

    return common_terminate_owned_process(
        proc,
        graceful_timeout_seconds=graceful_timeout_seconds,
        force_timeout_seconds=force_timeout_seconds,
    )


def spawn_owned_process(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> subprocess.Popen[Any]:
    """Spawn a managed serving child with argv array (never shell=True)."""
    if not command:
        raise ValueError("empty command")
    kwargs: dict[str, Any] = {
        "args": list(command),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.PIPE,
        "env": env,
        "cwd": cwd,
        "shell": False,
    }
    if os.name == "nt":
        # New process group for CTRL_BREAK / tree kill.
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        kwargs["creationflags"] = creationflags
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(**kwargs)


def drain_pipe_bounded(pipe: Any, *, max_bytes: int = 64_000) -> str:
    """Read residual stderr/stdout without unbounded growth."""
    if pipe is None:
        return ""
    try:
        raw = pipe.read(max_bytes) if hasattr(pipe, "read") else b""
    except Exception:  # noqa: BLE001
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)[:max_bytes]


class WorkerLogBuffer:
    """Bounded ring buffer for worker diagnostics (no secrets/prompts)."""

    def __init__(self, *, max_lines: int = 200, max_line_chars: int = 500) -> None:
        self.max_lines = max_lines
        self.max_line_chars = max_line_chars
        self._lines: list[str] = []

    def append(self, line: str) -> None:
        text = (line or "").rstrip("\n")
        if len(text) > self.max_line_chars:
            text = text[: self.max_line_chars] + "…"
        self._lines.append(text)
        if len(self._lines) > self.max_lines:
            self._lines = self._lines[-self.max_lines :]

    def recent(self, limit: int = 50) -> list[str]:
        if limit <= 0:
            return []
        return list(self._lines[-limit:])


def wait_until(
    predicate: Any,
    *,
    timeout_seconds: float,
    poll_seconds: float = 0.1,
) -> bool:
    deadline = time.monotonic() + float(timeout_seconds)
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(max(0.01, float(poll_seconds)))
    return bool(predicate())
