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
    """Return True if the OS still has a *live* process with this PID.

    Uses signal 0 / OpenProcess existence checks. Never terminates.
    Zombie (defunct) processes are treated as not alive so callers can
    reconcile after SIGKILL when the parent has not yet reaped the child.
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
    # Linux: zombies still accept signal 0 — treat them as dead for recovery.
    try:
        with open(f"/proc/{int(pid)}/stat", encoding="utf-8") as handle:
            stat = handle.read()
        # Format: pid (comm) state ...
        close = stat.rfind(")")
        if close != -1 and close + 2 < len(stat):
            state = stat[close + 2]
            if state == "Z":
                return False
    except FileNotFoundError:
        return False
    except OSError:
        pass
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


def pid_fingerprint(pid: int | None) -> str:
    """Best-effort process identity for PID-reuse detection (Windows + Linux).

    Never kills. Prefer OS creation-time / starttime over bare PID numbers.
    """
    if not isinstance(pid, int) or pid <= 0:
        return ""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not handle:
                return f"{pid}:"
            try:
                creation = wintypes.FILETIME()
                exit_time = wintypes.FILETIME()
                kernel = wintypes.FILETIME()
                user = wintypes.FILETIME()
                ok = kernel32.GetProcessTimes(
                    handle,
                    ctypes.byref(creation),
                    ctypes.byref(exit_time),
                    ctypes.byref(kernel),
                    ctypes.byref(user),
                )
                if not ok:
                    return f"{pid}:"
                stamp = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
                return f"{pid}:{stamp}"
            finally:
                kernel32.CloseHandle(handle)
        except Exception:  # noqa: BLE001
            return f"{pid}:"
    try:
        # Linux: starttime from /proc/<pid>/stat field 22.
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        after = stat.rsplit(")", 1)[-1].strip().split()
        starttime = after[19] if len(after) > 19 else ""
        return f"{pid}:{starttime}"
    except OSError:
        return f"{pid}:"
