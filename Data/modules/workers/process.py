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

from .crash_diagnostics import generation_log_filename, retain_pool_logs


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
    log_handle: Any = None
    if log_dir is not None:
        pool_log_dir = Path(log_dir) / pool_id
        pool_log_dir.mkdir(parents=True, exist_ok=True)
        # Retention before spawn so crash history stays bounded but never
        # truncates the generation we are about to create.
        try:
            retain_pool_logs(pool_log_dir)
        except Exception:  # noqa: BLE001 — never block spawn on retention
            pass
        # Filename is finalized after Popen so it includes the real PID.
        # Use a provisional open after fork via a pipe would lose the path;
        # create unique path once PID is known, then reopen — for spawn we
        # pre-open with a placeholder and rename is unsafe across open FDs.
        # Instead: open DEVNULL first, then after Popen open unique file and
        # leave stdout redirected... Actually Popen needs the handle at start.
        # Solution: allocate unique name with worker_id + nanosecond timestamp
        # before spawn; include pid after via a companion sidecar, OR include
        # pid estimate. Spec wants pid in filename — we spawn with
        # start_new_session and use a pre-created unique name that includes
        # worker suffix + timestamp; then after Popen we hardlink/rename to
        # include pid if the OS allows (handle stays open on inode).
        started = time.time()
        provisional = pool_log_dir / generation_log_filename(
            pool_id=pool_id,
            slot=slot,
            worker_id=worker_id,
            pid=0,
            started_at=started,
        )
        log_handle = open(provisional, "x", encoding="utf-8")  # noqa: SIM115 — exclusive create
        log_path = provisional
        stdout = log_handle
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

    # Rename log to include real PID while keeping the open FD (same inode).
    if log_path is not None and log_handle is not None:
        final_name = pool_log_dir / generation_log_filename(
            pool_id=pool_id,
            slot=slot,
            worker_id=worker_id,
            pid=int(popen.pid),
            started_at=started,
        )
        if final_name != log_path:
            try:
                log_path.rename(final_name)
                log_path = final_name
            except OSError:
                # Keep provisional path; still unique per generation.
                pass
        child_env_note = f"# worker_id={worker_id} pid={popen.pid} pool={pool_id} slot={slot}\n"
        try:
            log_handle.write(child_env_note)
            log_handle.flush()
        except Exception:  # noqa: BLE001
            pass

    return OwnedProcess(
        worker_id=worker_id,
        pool_id=pool_id,
        slot=slot,
        pid=int(popen.pid),
        process_start_identity=identity,
        popen=popen,
        log_path=log_path,
        started_at=time.time(),
    )


def verify_owned(proc: OwnedProcess) -> bool:
    """Confirm the live PID still matches our recorded creation identity."""
    if not pid_is_alive(proc.pid):
        return False
    current = process_start_identity_for(proc.pid)
    # On platforms without starttime, identity prefix pid: may drift — require popen still running.
    if proc.popen is not None and proc.popen.poll() is not None:
        return False
    if current.startswith("linux:") and proc.process_start_identity.startswith("linux:"
    ):
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
