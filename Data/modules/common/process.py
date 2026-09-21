"""Process liveness checks — Windows-safe, never kills the process."""

from __future__ import annotations

import os
from pathlib import Path

from .atomic import atomic_write_text


def write_pid_file(path: Path, pid: int) -> None:
    atomic_write_text(path, str(int(pid)))


def read_pid_file(path: Path) -> int | None:
    try:
        text = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def pid_is_alive(pid: int) -> bool:
    """Return True if the OS still has a process with this PID.

    Uses signal 0 / OpenProcess existence checks. Never terminates.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
                PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
            )
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
                return True
            return False
        except Exception:  # noqa: BLE001 — best-effort existence probe
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we cannot signal it.
        return True
    except OSError:
        return False
    return True
