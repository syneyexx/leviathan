"""Job runtime HTTP routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from Data.modules.jobs import JobState


class JobCreateRequest(BaseModel):
    capability_id: str = Field(min_length=1, max_length=120)
    arguments: dict = Field(default_factory=dict)
    approval_id: str | None = None
    run_id: str | None = None
    requested_by: str = "api"


def build_jobs_router(
    *,
    settings: Any,
    job_runtime: Any,
    job_store: Any,
) -> APIRouter:
    router = APIRouter(tags=["jobs"])

    @router.get("/api/jobs")
    def list_jobs(
        state: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> dict:
        parsed = None
        if state:
            try:
                parsed = JobState(state.upper())
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"Invalid job state: {state}") from exc
        return {"jobs": [item.public_dict() for item in job_runtime.list(state=parsed, limit=limit)]}

    @router.post("/api/jobs")
    def create_job(payload: JobCreateRequest) -> dict:
        try:
            job = job_runtime.enqueue(
                capability_id=payload.capability_id,
                arguments=payload.arguments,
                approval_id=payload.approval_id,
                run_id=payload.run_id,
                requested_by=payload.requested_by,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"job": job.public_dict()}

    @router.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        job = job_runtime.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"job": job.public_dict()}

    @router.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict:
        try:
            job = job_runtime.cancel(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"job": job.public_dict()}

    @router.get("/api/jobs/{job_id}/children")
    def list_job_children(job_id: str) -> dict:
        parent = job_runtime.get(job_id)
        if parent is None:
            raise HTTPException(status_code=404, detail="Job not found")
        children = []
        if hasattr(job_store, "list_children"):
            children = [c.public_dict() for c in job_store.list_children(job_id)]
        return {"job_id": job_id, "children": children}

    @router.post("/api/jobs/{job_id}/retry")
    def retry_job(job_id: str) -> dict:
        job = job_runtime.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.state not in {JobState.FAILED, JobState.CANCELLED}:
            raise HTTPException(status_code=409, detail=f"Cannot retry job in state {job.state.value}")
        try:
            if hasattr(job_store, "schedule_retry"):
                job = job_store.schedule_retry(job_id, delay_seconds=0.0, error="manual_retry")
            else:
                job = job_store.transition(job_id, JobState.QUEUED)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"job": job.public_dict()}

    @router.get("/api/jobs/{job_id}/provider-stream")
    def provider_job_stream(
        job_id: str,
        after: Annotated[int, Query()] = 0,
        limit: Annotated[int, Query()] = 100,
    ) -> dict:
        """Poll ordered provider_io stream events (deltas) for a job."""
        job = job_runtime.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Unknown job")
        from Data.modules.provider_io.stream_store import ProviderStreamStore

        store = ProviderStreamStore(settings.database_path)
        store.initialize()
        events = store.read_after(job_id, after, limit=limit)
        return {
            "job_id": job_id,
            "job_state": job.state.value,
            "events": [e.public_dict() for e in events],
            "truth": {
                "live_transport_is_not_durable_final_result": True,
                "provider_health_is_not_worker_health": True,
            },
        }

    return router
