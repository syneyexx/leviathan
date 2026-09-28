"""Media pool entrypoint — FFmpeg / media orchestration owner.

Retains MediaService + configured backends for the process lifetime.
FastAPI never runs FFmpeg/ffprobe or heavy media transforms.
"""

from __future__ import annotations

import atexit
import os
from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool


def _build_media_executor(ctx: dict[str, Any]) -> Any:
    from Data.modules.media.service import MediaService

    settings = ctx.get("settings")
    artifact_store = ctx.get("artifact_store")
    media_settings = getattr(settings, "media", None)
    # Production path: never use fixture backend unless explicitly forced for tests.
    backend_mode = (
        os.environ.get("LEVIATHAN_MEDIA_BACKEND")
        or getattr(media_settings, "backend", None)
        or "ffmpeg"
    )
    service = MediaService(
        artifact_store=artifact_store,
        backend_mode=str(backend_mode),
        ffmpeg_path=getattr(media_settings, "ffmpeg_path", None),
        ffprobe_path=getattr(media_settings, "ffprobe_path", None),
        filesystem_root=str(
            getattr(settings, "project_root", None)
            or getattr(getattr(settings, "coding", None), "workspace", None)
            or ""
        )
        or None,
        allow_fixture_in_production=False,
    )
    ctx["media_service"] = service
    gateway = ctx.get("gateway")
    if gateway is not None:
        gateway.media_executor = service

    def _shutdown() -> None:
        try:
            service.shutdown()
        except Exception:  # noqa: BLE001
            pass

    atexit.register(_shutdown)
    return service


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState
    from Data.modules.workers.loop import _default_gateway_execute

    worker_id = str(ctx.get("worker_id") or os.environ.get("LEVIATHAN_WORKER_ID") or "")
    if ctx.get("media_service") is None:
        try:
            _build_media_executor(ctx)
        except Exception as exc:  # noqa: BLE001
            fenced_transition(
                ctx["job_store"],
                job.job_id,
                JobState.FAILED,
                worker_id=worker_id,
                ctx=ctx,
                error=f"MEDIA_WORKER_UNAVAILABLE: {exc}",
                result={
                    "error_code": "MEDIA_WORKER_UNAVAILABLE",
                    "capability_id": getattr(job, "capability_id", None),
                },
            )
            return {"error": "MEDIA_WORKER_UNAVAILABLE", "detail": str(exc)}

    return (
        _default_gateway_execute(
            ctx["job_runtime"],
            ctx["job_store"],
            job,
            worker_id,
            float(getattr(ctx.get("worker_settings"), "lease_ttl_seconds", 60.0) or 60.0),
            ctx=ctx,
        )
        or {}
    )


def main(argv=None):
    return main_for_pool("media", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
