"""Supervise an owned trainer subprocess for its FULL lifetime.

The training_control JobRuntime job remains RUNNING (GPU reservation held)
until the trainer exits, cancellation completes, or a terminal failure is
recorded. Do not mark control COMPLETED merely because Popen succeeded.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from Data.modules.common.process import pid_fingerprint, pid_is_alive

from .store import utc_now
from .types import DurableTrainingStatus


def resolve_resume_checkpoint_path(raw: str | Path | None) -> str | None:
    """Normalize stored checkpoint path for HF / fixture resume semantics.

    - Directory path → use as-is (HF ``resume_from_checkpoint`` expects the dir).
    - File path (e.g. ``checkpoint-N/state.json``) → use parent directory.
    """
    if raw is None:
        return None
    path = Path(str(raw))
    if not str(path):
        return None
    if path.is_dir() or (not path.suffix and not path.exists()):
        # Prefer directory semantics; if missing, still return the given path.
        return str(path)
    if path.is_file() or path.suffix:
        return str(path.parent)
    return str(path)


def kill_trainer_tree(proc: Any, *, grace_seconds: float = 2.0) -> bool:
    """Terminate the trainer and its children (Windows-safe process tree)."""
    poll = getattr(proc, "poll", None)
    if callable(poll) and poll() is not None:
        return False
    # Real Popen: use coding process-tree killer.
    if isinstance(proc, subprocess.Popen):
        try:
            from Data.modules.coding.process import kill_process_tree

            return bool(kill_process_tree(proc, grace_seconds=grace_seconds))
        except Exception:  # noqa: BLE001
            pass
    pid = getattr(proc, "pid", None)
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=15,
                check=False,
            )
        else:
            import signal

            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                os.kill(pid, signal.SIGKILL)
        return True
    except Exception:  # noqa: BLE001
        return False


def supervise_trainer(
    *,
    store: Any,
    job_id: str,
    proc: subprocess.Popen[Any],
    launch_generation: int,
    pid_fp: str,
    cancel_check: Callable[[], bool] | None = None,
    poll_seconds: float = 0.5,
    cancel_grace_seconds: float = 15.0,
) -> dict[str, Any]:
    """Block until trainer exits; honor cancel; return terminal summary.

    Caller (training_control handler) owns JobRuntime lease heartbeats via the
    worker loop while this function runs — GPU_EXCLUSIVE stays reserved.
    """
    started = time.monotonic()
    cancel_sent = False
    cancel_requested_at: float | None = None

    while True:
        code = proc.poll()
        if code is not None:
            break

        # Stale-generation / PID-reuse protection.
        if proc.pid and not pid_is_alive(int(proc.pid)):
            # Process gone but not reaped yet — poll again.
            code = proc.poll()
            if code is not None:
                break

        job = store.get_job(job_id)
        if job is not None:
            meta = dict(job.environment or {})
            gen = int(meta.get("launch_generation") or launch_generation)
            if gen != launch_generation:
                return {
                    "terminal": "stale_generation",
                    "status": DurableTrainingStatus.INTERRUPTED.value,
                    "launch_generation": launch_generation,
                    "current_generation": gen,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                }
            stored_fp = str(meta.get("pid_fingerprint") or "")
            if stored_fp and proc.pid:
                live_fp = pid_fingerprint(int(proc.pid))
                if live_fp and stored_fp != live_fp:
                    return {
                        "terminal": "pid_reuse",
                        "status": DurableTrainingStatus.INTERRUPTED.value,
                        "error": "TRAINER_DIED: pid fingerprint mismatch",
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                    }

            if bool(job.cancel_requested) or (
                job.status == DurableTrainingStatus.CANCELLING
            ):
                if not cancel_sent:
                    cancel_sent = True
                    cancel_requested_at = time.monotonic()
                    # Soft: durable cancel flag already set; trainer should stop.
                    # Hard after grace: terminate process tree.
                elif cancel_requested_at is not None and (
                    time.monotonic() - cancel_requested_at
                ) >= cancel_grace_seconds:
                    kill_trainer_tree(proc, grace_seconds=2.0)

        if cancel_check is not None and cancel_check():
            if not cancel_sent:
                cancel_sent = True
                cancel_requested_at = time.monotonic()
                try:
                    store.request_cancel(job_id)
                except Exception:  # noqa: BLE001
                    pass
            elif cancel_requested_at is not None and (
                time.monotonic() - cancel_requested_at
            ) >= cancel_grace_seconds:
                kill_trainer_tree(proc, grace_seconds=2.0)

        time.sleep(max(0.05, float(poll_seconds)))

    exit_code = int(proc.returncode if proc.returncode is not None else -1)
    elapsed = round(time.monotonic() - started, 3)
    job = store.get_job(job_id)
    # Trainer worker finalizes durable status itself on clean paths. Supervisor
    # reconciles only when the domain row is still non-terminal.
    if job is not None and job.status not in {
        DurableTrainingStatus.COMPLETED,
        DurableTrainingStatus.FAILED,
        DurableTrainingStatus.CANCELLED,
        DurableTrainingStatus.INTERRUPTED,
    }:
        if cancel_sent or (job.cancel_requested):
            store.update_job(
                job_id,
                status=DurableTrainingStatus.CANCELLED,
                phase="cancelled",
                finished_at=utc_now(),
                error=job.error or "Cancelled (supervisor)",
                worker_pid=None,
            )
            status = DurableTrainingStatus.CANCELLED.value
            terminal = "cancelled"
        elif exit_code == 0:
            # Trainer exited 0 but did not finalize — mark interrupted for recovery.
            store.update_job(
                job_id,
                status=DurableTrainingStatus.INTERRUPTED,
                phase="interrupted",
                finished_at=utc_now(),
                error="Trainer exited without durable finalization",
                worker_pid=None,
            )
            status = DurableTrainingStatus.INTERRUPTED.value
            terminal = "exit_without_finalize"
        else:
            store.update_job(
                job_id,
                status=DurableTrainingStatus.FAILED,
                phase="failed",
                finished_at=utc_now(),
                error=f"TRAINER_DIED: exit_code={exit_code}",
                worker_pid=None,
            )
            status = DurableTrainingStatus.FAILED.value
            terminal = "trainer_died"
    else:
        status = job.status.value if job is not None else "unknown"
        terminal = "trainer_exit"

    return {
        "terminal": terminal,
        "status": status,
        "exit_code": exit_code,
        "launch_generation": launch_generation,
        "pid": proc.pid,
        "pid_fingerprint": pid_fp,
        "elapsed_seconds": elapsed,
        "cancel_sent": cancel_sent,
    }
