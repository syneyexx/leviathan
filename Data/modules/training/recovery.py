"""Reconcile training jobs after process/backend restarts."""

from __future__ import annotations

from Data.modules.common.process import pid_is_alive

from .store import TrainingStore, utc_now
from .types import DurableTrainingStatus


def reconcile_active_jobs(store: TrainingStore, *, processes: dict | None = None) -> list[dict]:
    """Mark dead workers interrupted/cancelled — never leave phantom 'running'."""
    results: list[dict] = []
    tracked = processes or {}
    for job in store.list_active_jobs():
        pid = job.worker_pid
        proc = tracked.get(job.job_id)
        if proc is not None:
            try:
                proc.poll()
            except Exception:  # noqa: BLE001
                pass
        if job.status == DurableTrainingStatus.QUEUED and pid is None:
            continue
        if job.status == DurableTrainingStatus.CANCELLING:
            if pid is None or not pid_is_alive(pid):
                updated = store.update_job(
                    job.job_id,
                    status=DurableTrainingStatus.CANCELLED,
                    phase="cancelled",
                    finished_at=utc_now(),
                    error=job.error or "Cancelled (worker not alive)",
                    worker_pid=None,
                )
                results.append(
                    {
                        "jobId": updated.job_id,
                        "from": job.status.value,
                        "to": updated.status.value,
                        "reason": "cancelling_worker_dead",
                    }
                )
            continue
        if pid is None:
            # Active without pid — treat as interrupted so UI can resume.
            updated = store.update_job(
                job.job_id,
                status=DurableTrainingStatus.INTERRUPTED,
                phase="interrupted",
                finished_at=utc_now(),
                error="Worker identity missing after restart",
            )
            results.append(
                {
                    "jobId": updated.job_id,
                    "from": job.status.value,
                    "to": updated.status.value,
                    "reason": "missing_pid",
                }
            )
            continue
        if not pid_is_alive(pid):
            updated = store.update_job(
                job.job_id,
                status=DurableTrainingStatus.INTERRUPTED,
                phase="interrupted",
                finished_at=utc_now(),
                error=f"Worker pid {pid} is not alive",
                worker_pid=None,
            )
            results.append(
                {
                    "jobId": updated.job_id,
                    "from": job.status.value,
                    "to": updated.status.value,
                    "reason": "pid_dead",
                    "pid": pid,
                }
            )
    return results
