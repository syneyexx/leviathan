"""Artifact store HTTP routes (+ thin run lookup)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


class ArtifactWrite(BaseModel):
    content: str = Field(min_length=1, max_length=2_000_000)
    filename: str = Field(min_length=1, max_length=180)
    artifact_type: str = Field(default="text", min_length=1, max_length=80)
    run_id: str | None = None
    producer: str = Field(default="api", min_length=1, max_length=120)


def build_artifacts_router(*, artifacts: Any, runs: Any) -> APIRouter:
    router = APIRouter(tags=["artifacts"])

    @router.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        run = runs.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return {
            "run": run.public_dict(),
            "events": [
                {
                    "event_id": event.event_id,
                    "event_type": event.event_type.value,
                    "created_at": event.created_at,
                    "payload": event.payload,
                }
                for event in runs.list_events(run_id)
            ],
        }

    @router.post("/api/artifacts")
    def create_artifact(payload: ArtifactWrite) -> dict:
        if "/" in payload.filename or "\\" in payload.filename:
            raise HTTPException(status_code=422, detail="filename must be a basename")
        if payload.run_id and not runs.get_run(payload.run_id):
            raise HTTPException(status_code=404, detail="Run not found")
        record = artifacts.create_from_bytes(
            data=payload.content.encode("utf-8"),
            artifact_type=payload.artifact_type.strip(),
            producer=payload.producer.strip(),
            filename=payload.filename.strip(),
            run_id=payload.run_id,
        )
        return {"artifact": record.public_dict()}

    @router.get("/api/artifacts/{artifact_id}")
    def get_artifact(artifact_id: str) -> dict:
        record = artifacts.get(artifact_id)
        if not record:
            raise HTTPException(status_code=404, detail="Artifact not found")
        return {"artifact": record.public_dict()}

    @router.post("/api/artifacts/{artifact_id}/verify")
    def verify_artifact(artifact_id: str) -> dict:
        try:
            ok = artifacts.verify_hash(artifact_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Artifact not found") from exc
        record = artifacts.get(artifact_id)
        assert record is not None
        return {"ok": ok, "artifact": record.public_dict()}

    return router
