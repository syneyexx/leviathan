"""Windows Job Object Tier-2 sandbox lifecycle.

On Windows this module can create a Job Object, apply resource limits, spawn a
process already associated with the job (or attach before user work), and tear
down the process tree on close/timeout.

Job Objects provide process/resource management (memory/CPU/active-process
limits, kill-on-close for the process tree). They are NOT full filesystem or
network isolation — do not advertise AppContainer/FS/net jail from Tier 2 alone.

On non-Windows hosts the APIs are absent: callers must treat status as
UNVERIFIED_ON_HOST / unavailable — never operationally_tested=True from mere
import success.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable


# Win32 constants (values are stable across Windows 10/11).
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_JOB_TIME = 0x00000004
JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x1
JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP = 0x4

JobObjectExtendedLimitInformation = 9
JobObjectCpuRateControlInformation = 15

PROCESS_ALL_ACCESS = 0x1F0FFF
CREATE_SUSPENDED = 0x00000004
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

# Portable fail-closed reasons (unit-tested on Linux via mock hooks).
REASON_CREATE_SUSPENDED_FAILED = "create_suspended_failed"
REASON_ASSIGN_FAILED = "assign_failed"
REASON_RESUME_FAILED = "resume_failed"
REASON_NOT_WINDOWS = "not_windows"
REASON_TIMEOUT = "timeout"


@dataclass
class JobSandboxResult:
    ok: bool
    available: bool
    reason: str | None = None
    pid: int | None = None
    exit_code: int | None = None
    killed_on_close: bool = False
    limits_applied: dict[str, Any] = field(default_factory=dict)
    operationally_tested: bool = False
    enforcement: str = "none"
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_public(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "available": self.available,
            "reason": self.reason,
            "pid": self.pid,
            "exit_code": self.exit_code,
            "killed_on_close": self.killed_on_close,
            "limits_applied": self.limits_applied,
            "operationally_tested": self.operationally_tested,
            "enforcement": self.enforcement,
            "evidence": self.evidence,
        }


def job_object_api_present() -> bool:
    if os.name != "nt" and not sys.platform.startswith("win"):
        return False
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        return bool(hasattr(kernel32, "CreateJobObjectW") and hasattr(kernel32, "AssignProcessToJobObject"))
    except Exception:
        return False


def restricted_token_api_present() -> bool:
    if os.name != "nt" and not sys.platform.startswith("win"):
        return False
    try:
        import ctypes

        advapi = ctypes.windll.advapi32  # type: ignore[attr-defined]
        return bool(hasattr(advapi, "CreateRestrictedToken"))
    except Exception:
        return False


def configure_job_object_ctypes(kernel32: Any, ntdll: Any | None = None) -> None:
    """Bind Win32 signatures so HANDLE/BOOL mistakes cannot silently succeed.

    Safe to call repeatedly. On non-Windows hosts this is unused but kept as the
    single source of truth for argtypes/restype documentation.
    """
    import ctypes
    from ctypes import wintypes

    # CreateJobObjectW(LPSECURITY_ATTRIBUTES, LPCWSTR) -> HANDLE
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE

    # SetInformationJobObject(HANDLE, JOBOBJECTINFOCLASS, LPVOID, DWORD) -> BOOL
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL

    # AssignProcessToJobObject(HANDLE, HANDLE) -> BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL

    # OpenProcess(DWORD, BOOL, DWORD) -> HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE

    # CloseHandle(HANDLE) -> BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    # TerminateJobObject(HANDLE, UINT) -> BOOL
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateJobObject.restype = wintypes.BOOL

    # ResumeThread(HANDLE) -> DWORD (previous suspend count, or -1 on failure)
    if hasattr(kernel32, "ResumeThread"):
        kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel32.ResumeThread.restype = wintypes.DWORD

    if ntdll is not None and hasattr(ntdll, "NtResumeProcess"):
        # NTSTATUS NtResumeProcess(HANDLE ProcessHandle)
        ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
        ntdll.NtResumeProcess.restype = ctypes.c_long


def fail_closed_result(
    *,
    reason: str,
    pid: int | None = None,
    exit_code: int | None = None,
    killed: bool = False,
    limits_applied: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    available: bool = True,
) -> JobSandboxResult:
    """Portable fail-closed outcome: ok=False, never claims success."""
    return JobSandboxResult(
        ok=False,
        available=available,
        reason=reason,
        pid=pid,
        exit_code=exit_code,
        killed_on_close=killed,
        limits_applied=dict(limits_applied or {}),
        operationally_tested=False,
        enforcement="windows_job_object" if available else "none",
        evidence=dict(evidence or {}),
    )


def kill_process_tree_best_effort(
    proc: Any,
    *,
    terminate_job: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Fail-closed cleanup for an unconstrained or partially attached child.

    Portable: works with any Popen-like object (mockable on Linux). Prefer Job
    terminate when available, then escalate to kill().
    """
    evidence: dict[str, Any] = {"cleanup_attempted": True}
    if terminate_job is not None:
        try:
            terminate_job()
            evidence["terminate_job"] = True
        except Exception as exc:  # noqa: BLE001 — cleanup must continue
            evidence["terminate_job_error"] = str(exc)
    try:
        if proc is not None and getattr(proc, "poll", lambda: None)() is None:
            proc.kill()
            evidence["proc_kill"] = True
    except Exception as exc:  # noqa: BLE001
        evidence["proc_kill_error"] = str(exc)
    try:
        if proc is not None:
            proc.wait(timeout=5)
            evidence["wait_exit_code"] = getattr(proc, "returncode", None)
    except Exception as exc:  # noqa: BLE001
        evidence["wait_error"] = str(exc)
    return evidence


def run_lifecycle_fail_closed(
    *,
    create_suspended_ok: bool,
    assign_ok: bool,
    resume_ok: bool,
    create_error: str = "create_suspended rejected",
    assign_error: str = "assign rejected",
    resume_error: str = "resume rejected",
    pid: int = 4242,
    terminate_job: Callable[[], None] | None = None,
    kill_child: Callable[[], None] | None = None,
) -> JobSandboxResult:
    """Mockable CREATE_SUSPENDED → assign → resume sequence (Linux unit tests).

    Mirrors WindowsJobSandbox.run fail-closed branches without Win32 APIs.
    """

    class _StubProc:
        def __init__(self, stub_pid: int) -> None:
            self.pid = stub_pid
            self.returncode: int | None = None
            self._alive = True

        def poll(self):
            return None if self._alive else self.returncode

        def kill(self) -> None:
            self._alive = False
            self.returncode = 9
            if kill_child is not None:
                kill_child()

        def wait(self, timeout=None):
            return self.returncode

    if not create_suspended_ok:
        # No unconstrained fallback — never spawn without suspension when required.
        return fail_closed_result(
            reason=REASON_CREATE_SUSPENDED_FAILED,
            evidence={"error": create_error, "unconstrained_spawn": False},
        )

    proc = _StubProc(pid)
    if not assign_ok:
        cleanup = kill_process_tree_best_effort(proc, terminate_job=terminate_job)
        return fail_closed_result(
            reason=REASON_ASSIGN_FAILED,
            pid=proc.pid,
            exit_code=proc.returncode,
            killed=True,
            evidence={"error": assign_error, "cleanup": cleanup, "suspended": True},
        )
    if not resume_ok:
        cleanup = kill_process_tree_best_effort(proc, terminate_job=terminate_job)
        return fail_closed_result(
            reason=REASON_RESUME_FAILED,
            pid=proc.pid,
            exit_code=proc.returncode,
            killed=True,
            evidence={"error": resume_error, "cleanup": cleanup},
        )
    return JobSandboxResult(
        ok=True,
        available=True,
        reason=None,
        pid=proc.pid,
        exit_code=0,
        operationally_tested=False,
        enforcement="mock_lifecycle",
        evidence={"note": "mock success path for unit tests only"},
    )


def decide_selftest_status(
    *,
    on_windows: bool,
    result_ok: bool,
    result_reason: str | None,
    cleanup_verified: bool,
    explicitly_testing_timeout: bool = False,
) -> dict[str, Any]:
    """Honest selftest verdict — timeout alone is never PASS.

    Timeout may PASS only when the probe is explicitly a timeout/cleanup test
    AND descendant cleanup evidence is verified.
    """
    if not on_windows:
        return {
            "status": "UNVERIFIED_ON_HOST",
            "operationally_tested": False,
            "failure_reason": "not_windows_or_job_api_absent",
        }
    if result_ok and cleanup_verified:
        return {"status": "PASS", "operationally_tested": True, "failure_reason": None}
    if (
        explicitly_testing_timeout
        and result_reason == REASON_TIMEOUT
        and cleanup_verified
    ):
        return {
            "status": "PASS",
            "operationally_tested": True,
            "failure_reason": None,
            "note": "timeout_with_verified_cleanup",
        }
    if result_reason == REASON_TIMEOUT and not cleanup_verified:
        return {
            "status": "FAIL",
            "operationally_tested": True,
            "failure_reason": "timeout_without_cleanup_evidence",
        }
    return {
        "status": "FAIL",
        "operationally_tested": True,
        "failure_reason": result_reason or "selftest_failed",
    }


class WindowsJobSandbox:
    """Managed Job Object lifecycle for Tier-2 subprocess containment."""

    def __init__(
        self,
        *,
        memory_limit_mb: int | None = 1024,
        process_limit: int | None = 8,
        cpu_rate_percent: int | None = 50,
        kill_on_job_close: bool = True,
    ) -> None:
        self.memory_limit_mb = memory_limit_mb
        self.process_limit = process_limit
        self.cpu_rate_percent = cpu_rate_percent
        self.kill_on_job_close = kill_on_job_close
        self._job = None
        self._kernel32 = None
        self._ntdll = None
        self._limits_applied: dict[str, Any] = {}

    def available(self) -> bool:
        return job_object_api_present()

    def _ensure_windows(self) -> None:
        if not self.available():
            raise RuntimeError("Windows Job Objects not available on this host")

    def open(self) -> None:
        """Create Job Object and apply limits before any child work starts."""
        self._ensure_windows()
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        ntdll = ctypes.windll.ntdll  # type: ignore[attr-defined]
        configure_job_object_ctypes(kernel32, ntdll)
        self._kernel32 = kernel32
        self._ntdll = ntdll
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise OSError("CreateJobObjectW failed")
        self._job = job

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

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        flags = 0
        if self.kill_on_job_close:
            flags |= JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            self._limits_applied["kill_on_job_close"] = True
        if self.process_limit is not None and self.process_limit > 0:
            flags |= JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            info.BasicLimitInformation.ActiveProcessLimit = int(self.process_limit)
            self._limits_applied["active_process_limit"] = int(self.process_limit)
        if self.memory_limit_mb is not None and self.memory_limit_mb > 0:
            flags |= JOB_OBJECT_LIMIT_JOB_MEMORY | JOB_OBJECT_LIMIT_PROCESS_MEMORY
            mem = int(self.memory_limit_mb) * 1024 * 1024
            info.JobMemoryLimit = mem
            info.ProcessMemoryLimit = mem
            self._limits_applied["memory_limit_mb"] = int(self.memory_limit_mb)
        info.BasicLimitInformation.LimitFlags = flags
        ok = kernel32.SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            self.close()
            raise OSError("SetInformationJobObject extended limits failed")

        if self.cpu_rate_percent is not None and 1 <= int(self.cpu_rate_percent) <= 100:
            class JOBOBJECT_CPU_RATE_CONTROL_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("ControlFlags", wintypes.DWORD),
                    ("CpuRate", wintypes.DWORD),
                ]

            cpu = JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
            cpu.ControlFlags = JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
            # CpuRate is percent * 100 (e.g. 5000 = 50%).
            cpu.CpuRate = int(self.cpu_rate_percent) * 100
            cpu_ok = kernel32.SetInformationJobObject(
                job,
                JobObjectCpuRateControlInformation,
                ctypes.byref(cpu),
                ctypes.sizeof(cpu),
            )
            self._limits_applied["cpu_rate_percent"] = int(self.cpu_rate_percent)
            self._limits_applied["cpu_rate_applied"] = bool(cpu_ok)

    def assign_pid(self, pid: int) -> None:
        self._ensure_windows()
        if self._job is None or self._kernel32 is None:
            raise RuntimeError("Job Object not open")
        from ctypes import wintypes

        process = self._kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, wintypes.DWORD(pid))
        if not process:
            raise OSError(f"OpenProcess failed for pid={pid}")
        try:
            if not self._kernel32.AssignProcessToJobObject(self._job, process):
                raise OSError("AssignProcessToJobObject failed")
        finally:
            self._kernel32.CloseHandle(process)

    def _resume_process(self, pid: int) -> None:
        """Resume a CREATE_SUSPENDED child. Errors propagate (no silent swallow)."""
        if self._kernel32 is None:
            raise OSError("kernel32 unavailable for resume")
        from ctypes import wintypes

        handle = self._kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, wintypes.DWORD(pid))
        if not handle:
            raise OSError(f"OpenProcess for resume failed pid={pid}")
        try:
            if self._ntdll is not None and hasattr(self._ntdll, "NtResumeProcess"):
                status = int(self._ntdll.NtResumeProcess(handle))
                # NTSTATUS: 0 = STATUS_SUCCESS
                if status != 0:
                    raise OSError(f"NtResumeProcess failed status=0x{status & 0xFFFFFFFF:08X}")
                return
            # Fallback: ResumeThread requires a thread handle; without it we fail closed.
            raise OSError("NtResumeProcess unavailable; cannot safely resume suspended process")
        finally:
            self._kernel32.CloseHandle(handle)

    def run(
        self,
        argv: list[str],
        *,
        cwd: str | None = None,
        timeout_seconds: float | None = 30.0,
        env: dict[str, str] | None = None,
        require_create_suspended: bool = True,
    ) -> JobSandboxResult:
        """Spawn argv inside the Job Object.

        Prefer create-suspended + assign + resume to avoid a race where the child
        runs unconstrained before attach. Fail closed: if CREATE_SUSPENDED,
        assign, or resume fails, kill/cleanup the child and return ok=False.
        """
        if not self.available():
            return fail_closed_result(
                reason=REASON_NOT_WINDOWS,
                available=False,
                evidence={"note": "Job Objects absent on this host"},
            )
        if self._job is None:
            self.open()

        proc = None
        suspended = False
        try:
            proc = subprocess.Popen(  # noqa: S603 — argv list, shell=False
                argv,
                cwd=cwd,
                env=env,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=CREATE_SUSPENDED,
            )
            suspended = True
        except (TypeError, ValueError, OSError) as exc:
            if require_create_suspended:
                # Fail closed: do not fall back to unconstrained spawn.
                if proc is not None:
                    cleanup = kill_process_tree_best_effort(proc, terminate_job=self.terminate_tree)
                    self.close()
                    return fail_closed_result(
                        reason=REASON_CREATE_SUSPENDED_FAILED,
                        pid=getattr(proc, "pid", None),
                        exit_code=getattr(proc, "returncode", None),
                        killed=True,
                        limits_applied=self._limits_applied,
                        evidence={"error": str(exc), "cleanup": cleanup},
                    )
                return fail_closed_result(
                    reason=REASON_CREATE_SUSPENDED_FAILED,
                    limits_applied=self._limits_applied,
                    evidence={"error": str(exc)},
                )

        assert proc is not None
        try:
            try:
                self.assign_pid(proc.pid)
            except Exception as exc:
                cleanup = kill_process_tree_best_effort(proc, terminate_job=self.terminate_tree)
                return fail_closed_result(
                    reason=REASON_ASSIGN_FAILED,
                    pid=proc.pid,
                    exit_code=getattr(proc, "returncode", None),
                    killed=True,
                    limits_applied=self._limits_applied,
                    evidence={"error": str(exc), "cleanup": cleanup, "suspended": suspended},
                )

            if suspended:
                try:
                    self._resume_process(proc.pid)
                except Exception as exc:
                    cleanup = kill_process_tree_best_effort(proc, terminate_job=self.terminate_tree)
                    return fail_closed_result(
                        reason=REASON_RESUME_FAILED,
                        pid=proc.pid,
                        exit_code=getattr(proc, "returncode", None),
                        killed=True,
                        limits_applied=self._limits_applied,
                        evidence={"error": str(exc), "cleanup": cleanup},
                    )

            try:
                stdout, stderr = proc.communicate(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                self.terminate_tree()
                cleanup = kill_process_tree_best_effort(proc, terminate_job=None)
                try:
                    stdout, stderr = proc.communicate(timeout=5)
                except Exception:
                    stdout, stderr = b"", b""
                return JobSandboxResult(
                    ok=False,
                    available=True,
                    reason=REASON_TIMEOUT,
                    pid=proc.pid,
                    exit_code=proc.returncode,
                    killed_on_close=True,
                    limits_applied=dict(self._limits_applied),
                    operationally_tested=True,
                    enforcement="windows_job_object",
                    evidence={
                        "stdout": (stdout or b"")[:2000].decode("utf-8", errors="replace"),
                        "stderr": (stderr or b"")[:2000].decode("utf-8", errors="replace"),
                        "timeout_seconds": timeout_seconds,
                        "cleanup": cleanup,
                    },
                )
            return JobSandboxResult(
                ok=proc.returncode == 0,
                available=True,
                reason=None if proc.returncode == 0 else f"exit_{proc.returncode}",
                pid=proc.pid,
                exit_code=proc.returncode,
                limits_applied=dict(self._limits_applied),
                operationally_tested=True,
                enforcement="windows_job_object",
                evidence={
                    "stdout": (stdout or b"")[:2000].decode("utf-8", errors="replace"),
                    "stderr": (stderr or b"")[:2000].decode("utf-8", errors="replace"),
                },
            )
        finally:
            # Closing the job handle kills remaining children when KILL_ON_JOB_CLOSE is set.
            self.close()

    def terminate_tree(self) -> None:
        if self._job is None or self._kernel32 is None:
            return
        try:
            self._kernel32.TerminateJobObject(self._job, 1)
        except Exception:
            pass

    def close(self) -> None:
        if self._job is not None and self._kernel32 is not None:
            try:
                self._kernel32.CloseHandle(self._job)
            except Exception:
                pass
        self._job = None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def run_tier2_selftest() -> dict[str, Any]:
    """Host operational probe. Never marks PASS on non-Windows.

    On Windows this deliberately times out a job that spawned a descendant and
    requires cleanup evidence (descendant dead) before PASS. Timeout alone is
    not sufficient.
    """
    if not job_object_api_present():
        verdict = decide_selftest_status(
            on_windows=False,
            result_ok=False,
            result_reason=REASON_NOT_WINDOWS,
            cleanup_verified=False,
        )
        return {
            "capability": "sandbox_tier2_job_object",
            "implemented": True,
            "available_on_host": False,
            "simulated": False,
            "operationally_tested": verdict["operationally_tested"],
            "quality_evaluated": False,
            "status": verdict["status"],
            "failure_reason": verdict["failure_reason"],
            "evidence": {
                "restricted_token_api": restricted_token_api_present(),
                "isolation_scope": (
                    "Job Objects = process/resource management "
                    "(limits + kill-on-close). Not full FS/network isolation."
                ),
            },
            "timestamp": time.time(),
        }

    sandbox = WindowsJobSandbox(memory_limit_mb=256, process_limit=4, cpu_rate_percent=40)
    # Child prints grandchild PID then sleeps; Job close/timeout must kill both.
    code = (
        "import subprocess, sys, time, os\n"
        "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "print('GRANDCHILD_PID=' + str(g.pid), flush=True)\n"
        "print('child-started', flush=True)\n"
        "time.sleep(30)\n"
    )
    result = sandbox.run([sys.executable, "-c", code], timeout_seconds=5.0)
    stdout = str((result.evidence or {}).get("stdout") or "")
    grandchild_pid: int | None = None
    for line in stdout.splitlines():
        if line.startswith("GRANDCHILD_PID="):
            try:
                grandchild_pid = int(line.split("=", 1)[1].strip())
            except ValueError:
                grandchild_pid = None
            break

    # Allow brief settle after job terminate/close.
    time.sleep(0.5)
    descendant_alive = bool(grandchild_pid and _pid_alive(grandchild_pid))
    cleanup_verified = bool(
        grandchild_pid is not None
        and not descendant_alive
        and result.killed_on_close
    )
    verdict = decide_selftest_status(
        on_windows=True,
        result_ok=bool(result.ok),
        result_reason=result.reason,
        cleanup_verified=cleanup_verified,
        explicitly_testing_timeout=True,
    )
    return {
        "capability": "sandbox_tier2_job_object",
        "implemented": True,
        "available_on_host": True,
        "simulated": False,
        "operationally_tested": bool(verdict["operationally_tested"] and result.available),
        "quality_evaluated": False,
        "status": verdict["status"],
        "failure_reason": verdict.get("failure_reason") or result.reason,
        "evidence": {
            **result.to_public(),
            "grandchild_pid": grandchild_pid,
            "descendant_alive_after_cleanup": descendant_alive,
            "cleanup_verified": cleanup_verified,
            "isolation_scope": (
                "Job Objects = process/resource management "
                "(limits + kill-on-close). Not full FS/network isolation."
            ),
        },
        "notes": (
            "Tier 2 enforces Job Object limits + KILL_ON_JOB_CLOSE for process trees. "
            "This is not AppContainer FS/network isolation. "
            "Restricted Token API presence is reported separately. "
            "Selftest PASS requires verified descendant cleanup, not timeout alone."
        ),
        "restricted_token_api": restricted_token_api_present(),
        "timestamp": time.time(),
    }
