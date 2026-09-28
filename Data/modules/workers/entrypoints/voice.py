"""Voice pool entrypoint — singleton realtime voice session ownership outside FastAPI.

Do NOT create one JobRuntime job per audio frame. Durable jobs are session /
transcribe / synthesize / barge-in / preprocess / postprocess units.
"""

from __future__ import annotations

import atexit
import os
from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool

_CAP_TO_ACTION = {
    "voice.start_session": "START_SESSION",
    "voice.transcribe": "STREAM_ASR",
    "voice.synthesize": "STREAM_TTS",
    "voice.barge_in": "BARGE_IN",
    "voice.preprocess": "PREPROCESS",
    "voice.postprocess": "POSTPROCESS",
}


def _get_voice_service(ctx: dict[str, Any]) -> Any:
    service = ctx.get("voice_service")
    if service is not None:
        return service
    from Data.modules.voice.service import VoiceService

    allow_fixture = os.environ.get("LEVIATHAN_VOICE_ALLOW_FIXTURE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    # Pytest / explicit test harness may enable fixture backends.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        allow_fixture = True
    service = VoiceService(allow_fixture=allow_fixture)
    service.refresh_readiness()
    ctx["voice_service"] = service
    atexit.register(lambda: service.expire_idle_sessions())
    return service


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    cap = str(getattr(job, "capability_id", "") or "")
    args = dict(getattr(job, "arguments", None) or {})
    action = _CAP_TO_ACTION.get(cap)
    if action is None:
        fenced_transition(
            ctx["job_store"],
            job.job_id,
            JobState.FAILED,
            error=f"Unsupported voice capability: {cap}",
            error_code="VOICE_UNSUPPORTED",
            worker_id=str(ctx.get("worker_id") or ""),
            ctx=ctx,
        )
        return {"error": f"unsupported:{cap}"}

    try:
        service = _get_voice_service(ctx)
        ctx["worker_id"] = ctx.get("worker_id") or os.environ.get("LEVIATHAN_WORKER_ID") or (
            f"voice-{os.getpid()}"
        )
        result = service.execute(
            action=action,
            arguments=args,
            run_id=getattr(job, "run_id", None) or args.get("run_id"),
            request_id=job.job_id,
        )
        result = dict(result or {})
        result["executed_via"] = "voice_worker"
        result["worker_generation"] = getattr(service, "worker_generation", None)
        status = str(result.get("status") or "").upper()
        error_code = result.get("error_code")
        if status in {"FAILED", "REJECTED", "UNSUPPORTED"} or error_code in {
            "VOICE_ASR_UNAVAILABLE",
            "VOICE_TTS_UNAVAILABLE",
            "VOICE_SESSION_LOST",
            "VOICE_SESSION_EXPIRED",
            "VOICE_AUDIO_TOO_LARGE",
            "VOICE_AUDIO_INVALID",
            "VOICE_BACKPRESSURE",
        }:
            # Unavailable backends complete the job with structured failure in result
            # (fail-closed honesty) rather than crashing the worker lease.
            fenced_transition(
                ctx["job_store"],
                job.job_id,
                JobState.COMPLETED,
                result=result,
                worker_id=str(ctx.get("worker_id") or ""),
                ctx=ctx,
            )
            return result
        fenced_transition(
            ctx["job_store"],
            job.job_id,
            JobState.COMPLETED,
            result=result,
            worker_id=str(ctx.get("worker_id") or ""),
            ctx=ctx,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        fenced_transition(
            ctx["job_store"],
            job.job_id,
            JobState.FAILED,
            error=str(exc)[:500],
            error_code="VOICE_ASR_FAILED",
            worker_id=str(ctx.get("worker_id") or ""),
            ctx=ctx,
        )
        return {"error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    return main_for_pool("voice", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
