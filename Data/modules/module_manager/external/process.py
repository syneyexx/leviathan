"""Owned-process supervision for PROCESS_SERVICE adapters.

Reuses LEVIATHAN process-ownership patterns: track PID + fingerprint, reconcile
on restart, never kill unrelated PID-reuse processes. Not a second WorkerSupervisor.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def process_fingerprint(pid: int, command: list[str], cwd: str | None) -> str:
    """Platform-assisted identity for PID-reuse safety."""
    from Data.modules.common.process import pid_fingerprint

    parts = [str(pid), "|".join(command), cwd or "", pid_fingerprint(pid)]
    try:
        # Prefer create time when available (Linux /proc).
        stat_path = Path(f"/proc/{pid}")
        if stat_path.exists():
            parts.append(str(int(stat_path.stat().st_ctime)))
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="replace")
            parts.append(cmdline.strip())
    except OSError:
        pass
    return "|".join(parts)


def pid_matches_fingerprint(pid: int, fingerprint: str | None, command: list[str], cwd: str | None) -> bool:
    if pid <= 0 or not fingerprint:
        return False
    if not _pid_alive(pid):
        return False
    return process_fingerprint(pid, command, cwd) == fingerprint


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


@dataclass
class BoundedLogBuffer:
    """Ring buffer that drains pipes so subprocesses cannot deadlock."""

    max_lines: int = 500
    max_bytes: int = 256_000
    lines: list[str] = field(default_factory=list)
    byte_count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def append(self, line: str) -> None:
        with self._lock:
            encoded = line.encode("utf-8", errors="replace")
            self.lines.append(line)
            self.byte_count += len(encoded)
            while len(self.lines) > self.max_lines or self.byte_count > self.max_bytes:
                if not self.lines:
                    break
                dropped = self.lines.pop(0)
                self.byte_count -= len(dropped.encode("utf-8", errors="replace"))

    def snapshot(self, limit: int = 200) -> list[str]:
        with self._lock:
            return list(self.lines)[-max(1, min(limit, self.max_lines)) :]


@dataclass
class OwnedProcess:
    module_id: str
    command: list[str]
    cwd: str | None
    env: dict[str, str]
    pid: int | None = None
    fingerprint: str | None = None
    started_at: str | None = None
    exit_code: int | None = None
    restart_count: int = 0
    launch_generation: int = 0
    proc: subprocess.Popen[bytes] | None = field(default=None, repr=False)
    stdout_buf: BoundedLogBuffer = field(default_factory=BoundedLogBuffer)
    stderr_buf: BoundedLogBuffer = field(default_factory=BoundedLogBuffer)
    _drain_threads: list[threading.Thread] = field(default_factory=list, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def start(self) -> int:
        with self._lock:
            if self.proc is not None and self.proc.poll() is None:
                return int(self.proc.pid)
            from Data.modules.common.process_control import (
                owned_child_popen_kwargs,
                scrub_child_environment,
            )

            # Never inherit ambient API secrets into external module processes.
            # Explicit module env is applied as extras; secret-shaped keys still
            # require an explicit permit list (none by default).
            env = scrub_child_environment(
                extras=dict(self.env or {}),
                permit_secret_extras=False,
            )
            popen_kwargs = owned_child_popen_kwargs()
            self.proc = subprocess.Popen(
                self.command,
                cwd=self.cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                shell=False,
                **popen_kwargs,
            )
            self.pid = int(self.proc.pid)
            self.started_at = utc_now()
            self.exit_code = None
            if self.launch_generation <= 0:
                self.launch_generation = 1
            self.fingerprint = process_fingerprint(self.pid, self.command, self.cwd)
            self._start_drainers()
            return self.pid

    def _start_drainers(self) -> None:
        assert self.proc is not None

        def _drain(stream: Any, buf: BoundedLogBuffer) -> None:
            try:
                while True:
                    raw = stream.readline()
                    if not raw:
                        break
                    try:
                        line = raw.decode("utf-8", errors="replace").rstrip("\n")
                    except Exception:  # noqa: BLE001
                        line = repr(raw)
                    buf.append(line)
            except Exception:  # noqa: BLE001
                return

        threads: list[threading.Thread] = []
        if self.proc.stdout is not None:
            t = threading.Thread(target=_drain, args=(self.proc.stdout, self.stdout_buf), daemon=True)
            t.start()
            threads.append(t)
        if self.proc.stderr is not None:
            t = threading.Thread(target=_drain, args=(self.proc.stderr, self.stderr_buf), daemon=True)
            t.start()
            threads.append(t)
        self._drain_threads = threads

    def poll(self) -> int | None:
        with self._lock:
            if self.proc is None:
                return self.exit_code
            code = self.proc.poll()
            if code is not None:
                self.exit_code = int(code)
            return code

    def is_alive(self) -> bool:
        with self._lock:
            if self.proc is not None:
                return self.proc.poll() is None
            if self.pid and self.fingerprint:
                return pid_matches_fingerprint(self.pid, self.fingerprint, self.command, self.cwd)
            return False

    def stop(self, *, grace_seconds: float = 5.0, force: bool = True) -> int | None:
        from Data.modules.common.process import pid_fingerprint
        from Data.modules.common.process_control import (
            kill_process_tree,
            terminate_owned_pid,
            terminate_owned_process,
        )

        with self._lock:
            if self.proc is None:
                # Reconcile orphaned PID only when fingerprint matches.
                if self.pid and pid_matches_fingerprint(self.pid, self.fingerprint, self.command, self.cwd):
                    expected = pid_fingerprint(self.pid)
                    result = terminate_owned_pid(
                        int(self.pid),
                        expected_fingerprint=expected,
                        grace_seconds=grace_seconds,
                        force=force,
                    )
                    if result.get("code") == "OWNERSHIP_UNPROVEN":
                        return self.exit_code
                return self.exit_code
            if self.proc.poll() is not None:
                self.exit_code = int(self.proc.returncode)
                return self.exit_code
            outcome = terminate_owned_process(
                self.proc,
                graceful_timeout_seconds=grace_seconds,
                force_timeout_seconds=3.0 if force else 0.1,
            )
            if force and outcome.get("stillAlive"):
                kill_process_tree(self.proc, grace_seconds=0.1)
            self.exit_code = int(self.proc.returncode) if self.proc.returncode is not None else None
            return self.exit_code

    def public_dict(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "pid": self.pid,
            "fingerprint": self.fingerprint,
            "command": list(self.command),
            "cwd": self.cwd,
            "started_at": self.started_at,
            "exit_code": self.exit_code,
            "restart_count": self.restart_count,
            "launch_generation": self.launch_generation,
            "alive": self.is_alive(),
            "stdout_tail": self.stdout_buf.snapshot(50),
            "stderr_tail": self.stderr_buf.snapshot(50),
        }


def wait_for_probe(
    probe: dict[str, Any] | None,
    *,
    timeout_seconds: float,
    is_alive: Callable[[], bool],
) -> tuple[bool, str]:
    """HTTP or command ready/health probe. Returns (ok, detail)."""
    if probe is None:
        # No probe → process liveness is enough.
        return (is_alive(), "alive" if is_alive() else "not_alive")
    kind = str(probe.get("kind") or "http").lower()
    deadline = time.monotonic() + max(0.5, timeout_seconds)
    last = "probe_pending"
    while time.monotonic() < deadline:
        if not is_alive():
            return False, "process_exited"
        if kind == "http":
            url = str(probe.get("url") or "")
            if not url:
                return False, "probe_url_missing"
            try:
                import urllib.request

                req = urllib.request.Request(url, method=str(probe.get("method") or "GET"))
                with urllib.request.urlopen(req, timeout=float(probe.get("timeout") or 2.0)) as resp:
                    code = int(getattr(resp, "status", 200) or 200)
                    expect = int(probe.get("expect_status") or 200)
                    if code == expect:
                        return True, f"http_{code}"
                    last = f"http_{code}"
            except Exception as exc:  # noqa: BLE001
                last = f"http_error:{exc}"
        elif kind == "command":
            cmd = probe.get("command")
            if not isinstance(cmd, (list, tuple)) or not cmd:
                return False, "probe_command_missing"
            try:
                completed = subprocess.run(
                    [str(x) for x in cmd],
                    capture_output=True,
                    timeout=float(probe.get("timeout") or 5.0),
                    check=False,
                    shell=False,
                )
                if completed.returncode == int(probe.get("expect_exit") or 0):
                    return True, "command_ok"
                last = f"command_exit_{completed.returncode}"
            except Exception as exc:  # noqa: BLE001
                last = f"command_error:{exc}"
        else:
            return False, f"unknown_probe_kind:{kind}"
        time.sleep(float(probe.get("interval") or 0.5))
    return False, f"probe_timeout:{last}"
