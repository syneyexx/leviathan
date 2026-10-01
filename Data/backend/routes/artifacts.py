"""Artifact store HTTP routes (+ thin run lookup)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


class ArtifactWrite(BaseModel):
    # Plain text capped lower; base64 binary may be larger (server enforces byte cap).
    content: str = Field(min_length=1, max_length=35_000_000)
    filename: str = Field(min_length=1, max_length=180)
    artifact_type: str = Field(default="text", min_length=1, max_length=80)
    run_id: str | None = None
    producer: str = Field(default="api", min_length=1, max_length=120)
    # When true, ``content`` is base64 — used for binary chat attachments.
    content_base64: bool = False
    mime_type: str | None = Field(default=None, max_length=180)
    conversation_id: str | None = None


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
        # Basename only — block path traversal / absolute paths.
        name = payload.filename.strip().replace("\\", "/").split("/")[-1]
        if not name or name in {".", ".."} or "/" in name or "\\" in name:
            raise HTTPException(status_code=422, detail="filename must be a safe basename")
        if ".." in name:
            raise HTTPException(status_code=422, detail="filename must be a safe basename")
        if payload.run_id and not runs.get_run(payload.run_id):
            raise HTTPException(status_code=404, detail="Run not found")
        if payload.content_base64:
            import base64

            try:
                data = base64.b64decode(payload.content, validate=True)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=422, detail="invalid base64 content") from exc
            if len(data) > 8 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="artifact too large")
        else:
            data = payload.content.encode("utf-8")
        # Never trust client MIME alone — store as declared metadata; type remains controlled.
        artifact_type = payload.artifact_type.strip() or "file"
        if payload.mime_type:
            mime = payload.mime_type.strip().lower()
            if mime.startswith("image/"):
                artifact_type = "image"
            elif mime.startswith("audio/"):
                artifact_type = "audio"
            elif mime.startswith("text/") or mime in {
                "application/json",
                "application/xml",
            }:
                artifact_type = "text"
            else:
                artifact_type = "file"
        record = artifacts.create_from_bytes(
            data=data,
            artifact_type=artifact_type,
            producer=payload.producer.strip(),
            filename=name,
            run_id=payload.run_id,
            metadata={
                "filename": name,
                "declared_mime_type": payload.mime_type,
                "conversation_id": payload.conversation_id,
                "content_base64": bool(payload.content_base64),
            },
        )
        public = record.public_dict()
        if payload.conversation_id:
            public = {**public, "conversation_id": payload.conversation_id}
        if payload.mime_type:
            public = {**public, "declared_mime_type": payload.mime_type}
        return {"artifact": public}

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
