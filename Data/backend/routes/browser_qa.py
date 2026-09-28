"""Thin FastAPI routes for localhost Browser QA crawler (GI9/GI14).

Production: enqueue JobRuntime browser.qa.* work. Never call
BrowserWorker.execute() or crawler.run() from the API process.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from Data.modules.execution.browser_dispatch import (
    DEFAULT_QA_WAIT_SECONDS,
    enqueue_and_maybe_await_browser,
)
from Data.modules.jobs.states import JobState


class QaCrawlRequest(BaseModel):
    seed_url: str = Field(..., min_length=1)
    persona: str = "DESKTOP_MOUSE"
    seed: int = 42
    budgets: dict[str, Any] = Field(default_factory=dict)
    allow_destructive_test_actions: bool = False
    allowed_hosts: list[str] | None = None
    journey_id: str | None = None
    run_id: str | None = None
    trace_id: str | None = None
    approval_id: str | None = None
    wait_seconds: float | None = Field(default=None, ge=0, le=60)


def build_browser_qa_router(
    browser_worker: Any = None,
    *,
    job_runtime: Any = None,
    settings: Any = None,
) -> APIRouter:
    """Compose thin routes — live work is JobRuntime → browser worker.

    ``browser_worker`` is retained for signature compatibility with older
    ``main.py`` wiring but must not be used for production execution.
    """
    router = APIRouter(tags=["browser-qa"])
    _ = browser_worker  # intentionally unused in production path

    def _require_runtime() -> Any:
        if job_runtime is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "BROWSER_WORKER_UNAVAILABLE",
                    "message": "JobRuntime not configured for browser QA",
                },
            )
        return job_runtime

    def _jobs_for_journey(runtime: Any, journey_id: str) -> list[Any]:
        jobs: list[Any] = []
        try:
            store = getattr(runtime, "store", None)
            if store is not None and hasattr(store, "list"):
                for job in store.list(limit=50):
                    if getattr(job, "domain_entity_id", None) == journey_id or journey_id in {
                        str((getattr(job, "arguments", None) or {}).get("journey_id") or ""),
                        str(getattr(job, "job_id", "") or ""),
                        str(getattr(job, "run_id", "") or ""),
                    }:
                        jobs.append(job)
        except Exception:  # noqa: BLE001
            return []
        return jobs

    @router.post("/api/browser/qa/crawls")
    def start_crawl(payload: QaCrawlRequest) -> dict:
        if settings is not None and not bool(getattr(getattr(settings, "browser_qa", None), "enabled", True)):
            raise HTTPException(status_code=503, detail="browser.qa disabled")
        runtime = _require_runtime()
        arguments = payload.model_dump()
        wait = (
            float(payload.wait_seconds)
            if payload.wait_seconds is not None
            else DEFAULT_QA_WAIT_SECONDS
        )
        try:
            result = enqueue_and_maybe_await_browser(
                runtime,
                capability_id="browser.qa.crawl",
                arguments=arguments,
                approval_id=payload.approval_id,
                requested_by="api.browser.qa.crawls",
                run_id=payload.run_id,
                trace_id=payload.trace_id,
                metadata={"browser_qa": "browser.qa.crawl"},
                wait_seconds=wait,
                timeout_seconds=300.0,
                domain_entity_type="browser_qa",
                domain_entity_id=payload.journey_id or payload.run_id,
            )
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "error_code", None) or type(exc).__name__
            status = 403 if code == "CRAWLER_TARGET_NOT_ALLOWED" else 400
            raise HTTPException(
                status_code=status,
                detail={"error": code, "message": str(exc)},
            ) from exc
        return result

    @router.get("/api/browser/qa/crawls/{journey_id}")
    def crawl_status(journey_id: str) -> dict:
        runtime = _require_runtime()
        jobs = _jobs_for_journey(runtime, journey_id)
        if not jobs:
            one = runtime.get(journey_id) if hasattr(runtime, "get") else None
            if one is None:
                raise HTTPException(
                    status_code=404,
                    detail={"status": "NOT_FOUND", "error_code": "CRAWLER_NOT_FOUND"},
                )
            jobs = [one]
        latest = jobs[0]
        public = latest.public_dict() if hasattr(latest, "public_dict") else {}
        result_payload = getattr(latest, "result", None) or {}
        return {
            "status": "COMPLETED",
            "action": "QA_STATUS",
            "journey_id": journey_id,
            "job": public,
            "report": result_payload.get("report") if isinstance(result_payload, dict) else None,
            "truth": {"status_does_not_invoke_browser": True},
        }

    @router.post("/api/browser/qa/crawls/{journey_id}/cancel")
    def crawl_cancel(journey_id: str) -> dict:
        runtime = _require_runtime()
        cancelled = []
        targets = [journey_id]
        for job in _jobs_for_journey(runtime, journey_id):
            targets.append(getattr(job, "job_id", None))
        for job_id in {t for t in targets if t}:
            try:
                runtime.request_cancel(str(job_id), reason="browser.qa.cancel")
                cancelled.append(str(job_id))
            except Exception:  # noqa: BLE001
                continue
        return {
            "status": "COMPLETED",
            "action": "QA_CANCEL",
            "journey_id": journey_id,
            "cancelled_job_ids": cancelled,
            "truth": {"durable_cancel": True, "cancelled_is_not_success": True},
        }

    @router.post("/api/browser/qa/crawls/{journey_id}/replay")
    def crawl_replay(journey_id: str, seed: int | None = None) -> dict:
        runtime = _require_runtime()
        arguments: dict[str, Any] = {"journey_id": journey_id}
        if seed is not None:
            arguments["seed"] = seed
        return enqueue_and_maybe_await_browser(
            runtime,
            capability_id="browser.qa.replay",
            arguments=arguments,
            requested_by="api.browser.qa.crawls",
            metadata={"browser_qa": "browser.qa.replay"},
            wait_seconds=DEFAULT_QA_WAIT_SECONDS,
            timeout_seconds=300.0,
            domain_entity_type="browser_qa",
            domain_entity_id=journey_id,
        )

    @router.get("/api/browser/qa/crawls/{journey_id}/report")
    def crawl_report(journey_id: str) -> dict:
        runtime = _require_runtime()
        jobs = _jobs_for_journey(runtime, journey_id)
        completed = None
        for job in jobs:
            state = getattr(job, "state", None)
            if state == JobState.COMPLETED or str(state).upper() == "COMPLETED":
                completed = job
                break
        if completed is None and jobs:
            completed = jobs[0]
        if completed is None:
            raise HTTPException(status_code=404, detail={"error_code": "CRAWLER_NOT_FOUND"})
        result_payload = getattr(completed, "result", None) or {}
        return {
            "status": "COMPLETED",
            "action": "QA_REPORT",
            "journey_id": journey_id,
            "report": result_payload.get("report") if isinstance(result_payload, dict) else None,
            "artifact_refs": (
                result_payload.get("artifact_refs") if isinstance(result_payload, dict) else []
            ),
            "truth": {"report_from_jobruntime_artifact": True},
        }

    return router
