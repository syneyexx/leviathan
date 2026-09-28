"""Media capability HTTP routes.

Production topology:
  FastAPI → JobRuntime enqueue → media worker → FFmpeg / transforms / MCP
Never: process_next(), MediaService heavy execution, fixture SVG as production.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from Data.modules.execution.media_dispatch import (
    DEFAULT_INTERACTIVE_WAIT_SECONDS,
    enqueue_and_maybe_await_media,
)
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
    container: str | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    paths: list[str] | None = None
    approval_id: str | None = None
    run_id: str | None = None
    trace_id: str | None = None
    # Compatibility only — ignored for execution topology (always external).
    via_job: bool = False
    wait_seconds: float | None = Field(default=None, ge=0, le=120)


_MEDIA_ACTION_TO_CAPABILITY = {
    "PROBE": "media.probe",
    "THUMBNAIL": "media.thumbnail",
    "IMAGE_GENERATE": "media.image_generate",
    "IMAGE_EDIT": "media.image_edit",
    "VIDEO_INGEST": "media.video_ingest",
    "VISION_INSPECT": "media.vision_inspect",
    "CROSS_MODAL_SEARCH": "media.cross_modal_search",
    "TRANSCODE": "media.transcode",
    "CONVERT": "media.convert",
    "AUDIO_PROCESS": "media.audio.process",
    "VIDEO_PROCESS": "media.video.process",
    "IMAGE_BATCH": "media.image.batch",
}


def _job_http_status(payload: dict[str, Any]) -> int:
    state = str(payload.get("state") or "").upper()
    job = payload.get("job") or {}
    error = str(job.get("error") or "")
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    code = str(result.get("error_code") or "")
    combined = f"{error} {code}".upper()
    if state == "FAILED":
        if "UNAVAILABLE" in combined:
            return 503
        if "BLOCKED" in combined or "DENIED" in combined:
            return 403
        if "TIMEOUT" in combined:
            return 408
        if "TOO_LARGE" in combined or "LIMIT_EXCEEDED" in combined:
            return 413
        if "DISK_FULL" in combined:
            return 507
        return 422
    if state == "CANCELLED":
        return 409
    if payload.get("queued"):
        return 202
    return 200


def build_media_router(
    *,
    settings: Any,
    media_stub: Any,
    execution_gateway: Any,
    job_runtime: Any,
    observability: Any,
    media_status_reader: Any | None = None,
) -> APIRouter:
    router = APIRouter(tags=["media"])
    _ = execution_gateway  # authority remains; live work is external

    @router.get("/api/media/status")
    def media_status() -> dict:
        """Independent backend truth — never runs FFmpeg."""
        if media_status_reader is not None and callable(media_status_reader):
            snap = media_status_reader()
            return snap if isinstance(snap, dict) else {"truth": {"cached_only": True}}
        return {
            "worker": "UNKNOWN",
            "ffmpeg": "UNKNOWN",
            "ffprobe": "UNKNOWN",
            "generation": "UNKNOWN",
            "vision": "UNKNOWN",
            "truth": {
                "cached_status_does_not_run_ffmpeg": True,
                "worker_ready_is_not_generation_ready": True,
                "stale": True,
            },
        }

    @router.post("/api/media/request")
    def media_request(payload: MediaRequest) -> dict:
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
            "container",
            "video_codec",
            "audio_codec",
            "paths",
        ):
            value = getattr(payload, key, None)
            if value is not None:
                arguments[key] = value

        wait = (
            float(payload.wait_seconds)
            if payload.wait_seconds is not None
            else DEFAULT_INTERACTIVE_WAIT_SECONDS
        )
        result = enqueue_and_maybe_await_media(
            job_runtime,
            capability_id=capability_id,
            arguments=arguments,
            approval_id=payload.approval_id,
            requested_by="api.media",
            run_id=payload.run_id,
            trace_id=payload.trace_id,
            metadata={"media_action": action.value, "via_job_compat": bool(payload.via_job)},
            wait_seconds=wait,
        )
        observability.emit(
            "media",
            "request",
            payload={
                "capability_id": capability_id,
                "job_id": result.get("job_id"),
                "state": result.get("state"),
                "queued": result.get("queued"),
                "run_id": payload.run_id,
            },
            level="info",
        )
        http = _job_http_status(result)
        body = {
            **result,
            "result": result.get("job"),
            "truth": {
                **(result.get("truth") or {}),
                "no_private_media_bypass": True,
                "via_job_ignored_for_topology": True,
                "fixture_is_not_ffmpeg": True,
            },
        }
        if http >= 400:
            raise HTTPException(status_code=http, detail=body)
        return body

    return router
