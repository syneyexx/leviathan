"""Launcher lifecycle helpers — process-tree ownership, not filesystem sandboxing.

Job Objects (when available on Windows) are used only for lifecycle management:
KILL_ON_JOB_CLOSE so failed readiness leaves zero orphan HADES children.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LauncherLifecycle:
    """Track HADES-owned startup processes and tear them down on failure."""

    processes: list[tuple[str, subprocess.Popen[Any]]] = field(default_factory=list)
    _job: Any = None
    _kernel32: Any = None
    job_object_used: bool = False
    note: str = "lifecycle_only_not_sandbox"

    def track(self, name: str, popen: subprocess.Popen[Any]) -> None:
        self.processes.append((name, popen))
        if self._job and self._kernel32 and popen.pid:
            try:
                handle = self._kernel32.OpenProcess(0x1F0FFF, False, int(popen.pid))
                if handle:
                    self._kernel32.AssignProcessToJobObject(self._job, handle)
                    self._kernel32.CloseHandle(handle)
            except Exception:
                pass

    def open_job_object_if_available(self) -> bool:
        """Best-effort Windows Job Object with kill-on-close. Never claims sandboxing."""
        if os.name != "nt":
            return False
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            job = kernel32.CreateJobObjectW(None, None)
            if not job:
                return False

            class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD),
                ]

            class IO_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong),
                ]

            class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t),
                ]

            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
            JobObjectExtendedLimitInformation = 9
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            ok = kernel32.SetInformationJobObject(
                job,
                JobObjectExtendedLimitInformation,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            if not ok:
                kernel32.CloseHandle(job)
                return False
            self._job = job
            self._kernel32 = kernel32
            self.job_object_used = True
            return True
        except Exception:
            self._job = None
            self._kernel32 = None
            self.job_object_used = False
            return False

    def terminate_all(self, *, grace_seconds: float = 2.0) -> list[dict[str, Any]]:
        """Terminate every tracked HADES child. Prefer Job Object terminate when open."""
        results: list[dict[str, Any]] = []
        if self._job and self._kernel32:
            try:
                self._kernel32.TerminateJobObject(self._job, 1)
                results.append({"via": "job_object", "ok": True})
            except Exception as exc:
                results.append({"via": "job_object", "ok": False, "error": str(exc)})
        for name, proc in list(self.processes):
            entry: dict[str, Any] = {"name": name, "pid": proc.pid}
            try:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=grace_seconds)
                    except Exception:
                        proc.kill()
                        try:
                            proc.wait(timeout=1.0)
                        except Exception:
                            pass
                entry["returncode"] = proc.poll()
                entry["alive"] = proc.poll() is None
            except Exception as exc:
                entry["error"] = str(exc)
                entry["alive"] = True
            results.append(entry)
        if self._job and self._kernel32:
            try:
                self._kernel32.CloseHandle(self._job)
            except Exception:
                pass
            self._job = None
        return results

    def any_alive(self) -> bool:
        return any(proc.poll() is None for _, proc in self.processes)


def transactional_startup_failed(
    lifecycle: LauncherLifecycle,
    *,
    reason: str,
) -> dict[str, Any]:
    """Canonical failure path: stop owned tree, report residual aliveness."""
    stopped = lifecycle.terminate_all()
    # Brief settle for process table updates.
    time.sleep(0.05)
    return {
        "ok": False,
        "reason": reason,
        "stopped": stopped,
        "orphan_alive": lifecycle.any_alive(),
        "job_object_used": lifecycle.job_object_used,
        "note": lifecycle.note,
    }
