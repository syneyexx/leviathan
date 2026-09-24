"""Dataset pool entrypoint — claims ``dataset.process`` kernel jobs.

When ``LEVIATHAN_DATASET_JOBS_RUNNER=external``, this pool (or
``scripts/dataset_worker.py``) is the sole runnable claim owner. Domain
``dataset_jobs`` rows remain the metadata/history store.
"""
from __future__ import annotations

from Data.modules.workers.entrypoints._cli import main_for_pool


def _handler(ctx, job):
    from Data.modules.datasets.worker import build_service_from_env
    from Data.modules.jobs.states import JobState

    service, _settings = build_service_from_env()
    # Prefer executing the already-claimed kernel job by id.
    if hasattr(service, "process_kernel_job"):
        service.process_kernel_job(job.job_id)
    else:
        service.runner.process_next()
    refreshed = ctx["job_store"].get(job.job_id)
    if refreshed is not None and refreshed.state == JobState.RUNNING:
        # Domain path may have completed without mirroring — complete conservatively.
        try:
            domain_id = refreshed.domain_entity_id or (refreshed.arguments or {}).get(
                "dataset_job_id"
            )
            result = {"delegated": True, "dataset_job_id": domain_id}
            if domain_id:
                domain = service.store.get_job(str(domain_id))
                if domain is not None:
                    result["status"] = domain.status.value
                    if domain.status.value == "failed":
                        ctx["job_store"].transition(
                            job.job_id,
                            JobState.FAILED,
                            error=domain.error,
                            result=result,
                        )
                        return {}
            ctx["job_store"].transition(job.job_id, JobState.COMPLETED, result=result)
        except Exception:
            pass
    return {}


def main(argv=None):
    return main_for_pool("dataset", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
