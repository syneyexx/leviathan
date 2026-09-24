"""Process spawn / terminate — argv arrays, shell=False, owned identity only."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from Data.modules.common.process import pid_is_alive


# Only these module entrypoints may be spawned by the generic supervisor.
ALLOWED_ENTRYPOINT_PREFIX = "Data.modules.workers.entrypoints."


@dataclass
class OwnedProcess:
    worker_id: str
    pool_id: str
    slot: int
    pid: int
    process_start_identity: str
    popen: subprocess.Popen[Any] | None
    started_at: float = field(default_factory=time.time)
    restart_count: int = 0
    draining: bool = False
    log_path: Path | None = None


def process_start_identity_for(pid: int) -> str:
    """Best-effort creation identity to defeat PID reuse."""
    if os.name != "nt":
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            # starttime is field 22 (1-indexed) after comm.
            close = stat.rfind(")")
            fields = stat[close + 2 :].split()
            starttime = fields[19] if len(fields) > 19 else "0"
            return f"linux:{pid}:{starttime}"
        except OSError:
            pass
    return f"pid:{pid}:{time.time_ns()}"


def spawn_worker_process(
    *,
    worker_id: str,
    pool_id: str,
    slot: int,
    entrypoint: str,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    log_dir: Path | None = None,
) -> OwnedProcess:
    if not entrypoint.startswith(ALLOWED_ENTRYPOINT_PREFIX):
        raise ValueError(f"Refusing unknown worker entrypoint: {entrypoint}")
    root = cwd or Path(__file__).resolve().parents[3]
    child_env = os.environ.copy()
    if env:
        child_env.update(env)
    child_env["LEVIATHAN_WORKER_ID"] = worker_id
    child_env["LEVIATHAN_WORKER_POOL"] = pool_id
    child_env["LEVIATHAN_WORKER_SLOT"] = str(slot)
    child_env.setdefault("PYTHONUNBUFFERED", "1")

    log_path = None
    stdout: Any = subprocess.DEVNULL
    stderr: Any = subprocess.DEVNULL
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{pool_id}-{slot}-{worker_id[:8]}.log"
        # Bound growth: open truncate; workers should keep logs modest.
        handle = open(log_path, "w", encoding="utf-8")  # noqa: SIM115
        stdout = handle
        stderr = subprocess.STDOUT

    popen = subprocess.Popen(  # noqa: S603 — argv list, shell=False, allowlisted entrypoint
        [sys.executable, "-m", entrypoint],
        cwd=str(root),
        env=child_env,
        shell=False,
        stdout=stdout,
        stderr=stderr,
    )
    identity = process_start_identity_for(int(popen.pid))
    return OwnedProcess(
        worker_id=worker_id,
        pool_id=pool_id,
        slot=slot,
        pid=int(popen.pid),
        process_start_identity=identity,
        popen=popen,
        log_path=log_path,
    )


def verify_owned(proc: OwnedProcess) -> bool:
    """Confirm the live PID still matches our recorded creation identity."""
    if not pid_is_alive(proc.pid):
        return False
    current = process_start_identity_for(proc.pid)
    # On platforms without starttime, identity prefix pid: may drift — require popen still running.
    if proc.popen is not None and proc.popen.poll() is not None:
        return False
    if current.startswith("linux:") and proc.process_start_identity.startswith("linux:"):
        return current == proc.process_start_identity
    return True


def terminate_owned(
    proc: OwnedProcess,
    *,
    grace_seconds: float = 10.0,
    force: bool = True,
) -> None:
    """Graceful terminate then kill only LEVIATHAN-owned process tree."""
    if not verify_owned(proc):
        # PID reuse or already dead — never kill unknown PID.
        return
    popen = proc.popen
    if popen is None:
        return
    if popen.poll() is not None:
        return
    try:
        if os.name == "nt":
            popen.terminate()
        else:
            popen.send_signal(signal.SIGTERM)
    except OSError:
        return
    deadline = time.time() + max(0.5, float(grace_seconds))
    while time.time() < deadline:
        if popen.poll() is not None:
            return
        time.sleep(0.1)
    if force and verify_owned(proc) and popen.poll() is None:
        try:
            popen.kill()
        except OSError:
            pass
        try:
            popen.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass
