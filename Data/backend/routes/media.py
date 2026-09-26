"""Media capability HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from Data.modules.execution import CapabilityRequest, CapabilityStatus
from Data.modules.media import MediaAction


class MediaRequest(BaseModel):
    action: str = Field(min_length=1, max_length=40)
    path: str | None = None
    prompt: str | None = None
    instruction: str | None = None
    source_artifact_id: str | None = None
    query: str | None = None
    duration_ms: float | None = None
    artifact_id: str | None = None
    width: int | None = None
    height: int | None = None
    tile: int | None = None
    limit: int | None = Field(default=None, ge=1, le=50)
    modality: str | None = None
    sync_id: str | None = None
    approval_id: str | None = None
    run_id: str | None = None
    trace_id: str | None = None
    via_job: bool = False


_MEDIA_ACTION_TO_CAPABILITY = {
    "PROBE": "media.probe",
    "THUMBNAIL": "media.thumbnail",
    "IMAGE_GENERATE": "media.image_generate",
    "IMAGE_EDIT": "media.image_edit",
    "VIDEO_INGEST": "media.video_ingest",
    "VISION_INSPECT": "media.vision_inspect",
    "CROSS_MODAL_SEARCH": "media.cross_modal_search",
}


def build_media_router(
    *,
    settings: Any,
    media_stub: Any,
    execution_gateway: Any,
    job_runtime: Any,
    observability: Any,
) -> APIRouter:
    router = APIRouter(tags=["media"])

    @router.post("/api/media/request")
    def media_request(payload: MediaRequest) -> dict:
        """Media actions go through ExecutionGateway when multimodal_realtime is on."""
        try:
            action = MediaAction(payload.action.upper())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid media action: {payload.action}") from exc

        if not settings.features.multimodal_realtime:
            job = media_stub.request(action=action, path=payload.path)
            status = 501 if job.status.value == "UNSUPPORTED" else (422 if job.status.value == "REJECTED" else 200)
            if status != 200:
                raise HTTPException(status_code=status, detail=job.public_dict())
            return {"job": job.public_dict(), "truth": {"multimodal_realtime_disabled": True}}

        capability_id = _MEDIA_ACTION_TO_CAPABILITY.get(action.value)
        if capability_id is None:
            raise HTTPException(status_code=422, detail=f"No capability mapping for action {action.value}")

        arguments: dict = {}
        for key in (
            "path",
            "prompt",
            "instruction",
            "source_artifact_id",
            "query",
            "duration_ms",
            "artifact_id",
            "width",
            "height",
            "tile",
            "limit",
            "modality",
            "sync_id",
        ):
            value = getattr(payload, key)
            if value is not None:
                arguments[key] = value

        if payload.via_job:
            job = job_runtime.enqueue(
                capability_id=capability_id,
                arguments=arguments,
                run_id=payload.run_id,
                approval_id=payload.approval_id,
                requested_by="api.media",
                trace_id=payload.trace_id,
                metadata={"media_action": action.value},
            )
            processed = job_runtime.process_next()
            final = job_runtime.get(job.job_id) or processed or job
            return {
                "job": final.public_dict(),
                "capability_id": capability_id,
                "truth": {
                    "requires_capability_gateway": True,
                    "no_private_media_bypass": True,
                    "routed_via_job": True,
                    "fixture_is_not_ffmpeg": True,
                },
            }

        result = execution_gateway.execute(
            CapabilityRequest(
                capability_id=capability_id,
                arguments=arguments,
                approval_id=payload.approval_id,
                run_id=payload.run_id,
                requested_by="api.media",
                trace_id=payload.trace_id,
            )
        )
        observability.emit(
            "media",
            "request",
            payload={
                "capability_id": capability_id,
                "status": result.status.value,
                "request_id": result.request_id,
                "run_id": payload.run_id,
            },
            level="info" if result.status.value == "COMPLETED" else "warn",
        )
        status_code = 200
        if result.status == CapabilityStatus.REJECTED:
            reason = (result.telemetry or {}).get("reason")
            status_code = 403 if reason in {"approval_required", "approval_denied"} else 422
        elif result.status == CapabilityStatus.FAILED:
            status_code = 500
        if status_code != 200:
            raise HTTPException(status_code=status_code, detail=result.public_dict())
        return {
            "result": result.public_dict(),
            "capability_id": capability_id,
            "truth": {
                "requires_capability_gateway": True,
                "no_private_media_bypass": True,
                "fixture_is_not_ffmpeg": True,
            },
        }

    return router
