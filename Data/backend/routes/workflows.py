"""Workflow runtime HTTP routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from Data.modules.workflows import WorkflowStepDef


class WorkflowCreateRequest(BaseModel):
    name: str = Field(default="workflow", min_length=1, max_length=120)
    run_id: str | None = None
    steps: list[dict] = Field(default_factory=list)


def build_workflows_router(
    *,
    workflow_store: Any,
    workflow_runtime: Any,
) -> APIRouter:
    router = APIRouter(tags=["workflows"])

    @router.get("/api/workflows")
    def list_workflows(limit: Annotated[int, Query(ge=1, le=500)] = 100) -> dict:
        return {"workflows": [item.public_dict() for item in workflow_store.list(limit=limit)]}

    @router.post("/api/workflows")
    def create_workflow(payload: WorkflowCreateRequest) -> dict:
        steps: list[WorkflowStepDef] = []
        for idx, raw in enumerate(payload.steps):
            capability_id = raw.get("capability_id")
            if not capability_id:
                raise HTTPException(status_code=422, detail=f"Step {idx} missing capability_id")
            steps.append(
                WorkflowStepDef(
                    step_id=str(raw.get("step_id") or f"step-{idx}"),
                    capability_id=str(capability_id),
                    arguments=dict(raw.get("arguments") or {}),
                    approval_id=raw.get("approval_id"),
                )
            )
        try:
            record = workflow_runtime.create(name=payload.name, steps=steps, run_id=payload.run_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"workflow": record.public_dict()}

    @router.get("/api/workflows/{workflow_id}")
    def get_workflow(workflow_id: str) -> dict:
        record = workflow_store.get(workflow_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return {"workflow": record.public_dict()}

    @router.post("/api/workflows/{workflow_id}/run")
    def run_workflow(workflow_id: str) -> dict:
        """Start a workflow. When workers are externalized, enqueue workflow.advance
        instead of blocking the API on the full step sequence.
        """
        try:
            from Data.modules.workers.settings import load_worker_settings

            externalize = bool(load_worker_settings().externalize_api_runners)
        except Exception:  # noqa: BLE001
            externalize = False
        try:
            if externalize and getattr(workflow_runtime, "job_runtime", None) is not None:
                job = workflow_runtime.enqueue_advance(workflow_id, requested_by="api")
                record = workflow_store.get(workflow_id)
                if record is None:
                    raise KeyError(workflow_id)
                return {
                    "workflow": record.public_dict(),
                    "job": job.public_dict(),
                    "mode": "enqueued",
                }
            record = workflow_runtime.run(workflow_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Workflow not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"workflow": record.public_dict(), "mode": "foreground"}

    @router.post("/api/workflows/{workflow_id}/cancel")
    def cancel_workflow(workflow_id: str) -> dict:
        try:
            record = workflow_runtime.cancel(workflow_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Workflow not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"workflow": record.public_dict()}

    return router
