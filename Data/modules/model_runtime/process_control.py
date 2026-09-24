"""Cross-platform owned-process termination for managed model workers."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from typing import Any


def terminate_owned_process(
    proc: subprocess.Popen[Any],
    *,
    graceful_timeout_seconds: float = 5.0,
    force_timeout_seconds: float = 3.0,
) -> dict[str, Any]:
    """Gracefully stop a LEVIATHAN-owned subprocess, then force-kill if needed.

    Never targets an arbitrary PID — only the Popen we own.
    """
    if proc.poll() is not None:
        return {
            "alreadyExited": True,
            "returncode": proc.returncode,
            "forced": False,
        }

    forced = False
    try:
        if os.name == "nt":
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
        return {"alreadyExited": False, "returncode": proc.returncode, "forced": False}
    except subprocess.TimeoutExpired:
        forced = True

    try:
        if os.name == "nt":
            proc.kill()
        else:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                proc.kill()
    except Exception:  # noqa: BLE001
        pass

    try:
        proc.wait(timeout=max(0.1, float(force_timeout_seconds)))
    except subprocess.TimeoutExpired:
        # Process still alive — report honestly.
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
