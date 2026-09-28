"""Browser request + legacy Browser QA journey HTTP routes.

Production topology:
  FastAPI (control plane) → JobRuntime enqueue → browser worker singleton
Never: process_next(), BrowserWorker.execute(), crawler.run(), Playwright launch.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from Data.modules.browser import BrowserAction
from Data.modules.execution.browser_dispatch import (
    DEFAULT_INTERACTIVE_WAIT_SECONDS,
    DEFAULT_QA_WAIT_SECONDS,
    enqueue_and_maybe_await_browser,
)
from Data.modules.jobs.states import JobState


class BrowserRequest(BaseModel):
    action: str = Field(min_length=1, max_length=40)
    url: str | None = None
    session_id: str | None = None
    selector: str | None = None
    text: str | None = None
    path: str | None = None
    fields: dict | None = None
    predicates: list | None = None
    contains_text: str | None = None
    approval_id: str | None = None
    run_id: str | None = None
    trace_id: str | None = None
    # Compatibility only — ignored for execution topology (always external).
    via_job: bool = False
    wait_seconds: float | None = Field(default=None, ge=0, le=60)


class BrowserQaCrawlRequest(BaseModel):
    seed_url: str = Field(min_length=1, max_length=2000)
    persona: str = "DESKTOP_MOUSE"
    seed: int = 42
    budgets: dict | None = None
    allow_destructive_test_actions: bool = False
    allowed_hosts: list[str] | None = None
    auth_secret_ref: str | None = None
    auth_lease_id: str | None = None
    journey_id: str | None = None
    run_id: str | None = None
    trace_id: str | None = None
    approval_id: str | None = None
    via_job: bool = False
    wait_seconds: float | None = Field(default=None, ge=0, le=60)


class BrowserQaJourneyRef(BaseModel):
    journey_id: str = Field(min_length=1, max_length=120)
    seed: int | None = None
    approval_id: str | None = None
    run_id: str | None = None
    trace_id: str | None = None
    via_job: bool = False
    wait_seconds: float | None = Field(default=None, ge=0, le=60)


_BROWSER_ACTION_TO_CAPABILITY = {
    "NAVIGATE": "browser.navigate",
    "EXTRACT_TEXT": "browser.extract_text",
    "SCREENSHOT": "browser.screenshot",
    "CLICK": "browser.click",
    "TYPE": "browser.type",
    "FORM_FILL": "browser.form_fill",
    "DOWNLOAD": "browser.download",
    "UPLOAD": "browser.upload",
    "VERIFY_STATE": "browser.verify_state",
    "SCROLL": "browser.scroll",
    "WAIT": "browser.wait",
    "KEYPRESS": "browser.keypress",
}


def _job_http_status(payload: dict[str, Any]) -> int:
    state = str(payload.get("state") or "").upper()
    job = payload.get("job") or {}
    error = str(job.get("error") or "")
    if state == "FAILED":
        if "UNAVAILABLE" in error.upper():
            return 503
        if "BLOCKED" in error.upper() or "DENIED" in error.upper():
            return 403
        if "TIMEOUT" in error.upper():
            return 408
        return 422
    if state == "CANCELLED":
        return 409
    if payload.get("queued"):
        return 202
    return 200


def build_browser_router(
    *,
    settings: Any,
    browser_stub: Any,
    browser_qa_crawler: Any,
    execution_gateway: Any,
    job_runtime: Any,
    observability: Any,
    browser_status_reader: Any | None = None,
) -> APIRouter:
    """Legacy `/api/browser/request` + `/api/browser/qa/{journey_id}/*` surfaces.

    ``browser_qa_crawler`` is retained for signature compatibility but must not
    be invoked for live crawl/replay from these production routes.
    """
    router = APIRouter(tags=["browser"])
    _ = (execution_gateway, browser_qa_crawler)  # control-plane authority / unused live

    @router.get("/api/browser/status")
    def browser_status() -> dict:
        """Cached readiness / worker projection — never launches Chromium."""
        if browser_status_reader is not None and callable(browser_status_reader):
            snap = browser_status_reader()
            return snap if isinstance(snap, dict) else {"truth": {"cached_only": True}}
        try:
            from Data.modules.browser.readiness import global_browser_readiness_cache

            return global_browser_readiness_cache().read().public_dict()
        except Exception:  # noqa: BLE001
            return {
                "worker": "UNAVAILABLE",
                "backend": "UNKNOWN",
                "chromium": "UNAVAILABLE",
                "truth": {
                    "cached_status_does_not_launch_chromium": True,
                    "stale": True,
                },
            }

    @router.post("/api/browser/request")
    def browser_request(payload: BrowserRequest) -> dict:
        try:
            action = BrowserAction(payload.action.upper())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid browser action: {payload.action}") from exc

        if not settings.features.capability_world:
            job = browser_stub.request(action=action, url=payload.url)
            status = 501 if job.status.value == "UNSUPPORTED" else (422 if job.status.value == "REJECTED" else 200)
            if status != 200:
                raise HTTPException(status_code=status, detail=job.public_dict())
            return {"job": job.public_dict(), "truth": {"capability_world_disabled": True}}

        capability_id = _BROWSER_ACTION_TO_CAPABILITY.get(action.value)
        if capability_id is None:
            raise HTTPException(status_code=422, detail=f"No capability mapping for action {action.value}")

        arguments: dict = {}
        if payload.url is not None:
            arguments["url"] = payload.url
        if payload.session_id is not None:
            arguments["session_id"] = payload.session_id
        if payload.selector is not None:
            arguments["selector"] = payload.selector
        if payload.text is not None:
            arguments["text"] = payload.text
        if payload.path is not None:
            arguments["path"] = payload.path
        if payload.fields is not None:
            arguments["fields"] = payload.fields
        if payload.predicates is not None:
            arguments["predicates"] = payload.predicates
        if payload.contains_text is not None:
            arguments["contains_text"] = payload.contains_text

        wait = (
            float(payload.wait_seconds)
            if payload.wait_seconds is not None
            else DEFAULT_INTERACTIVE_WAIT_SECONDS
        )
        # via_job is ignored — production always externalizes.
        result = enqueue_and_maybe_await_browser(
            job_runtime,
            capability_id=capability_id,
            arguments=arguments,
            approval_id=payload.approval_id,
            requested_by="api.browser",
            run_id=payload.run_id,
            trace_id=payload.trace_id,
            metadata={"browser_action": action.value, "via_job_compat": bool(payload.via_job)},
            wait_seconds=wait,
        )
        observability.emit(
            "browser",
            "request",
            payload={
                "capability_id": capability_id,
                "job_id": result.get("job_id"),
                "state": result.get("state"),
                "queued": result.get("queued"),
                "run_id": payload.run_id,
                "trace_id": payload.trace_id,
            },
            level="info",
        )
        http = _job_http_status(result)
        body = {
            **result,
            "result": result.get("job"),
            "truth": {
                **(result.get("truth") or {}),
                "fixture_is_not_chromium": True,
                "via_job_ignored_for_topology": True,
            },
        }
        if http >= 400:
            raise HTTPException(status_code=http, detail=body)
        return body

    @router.post("/api/browser/qa/crawl")
    def browser_qa_crawl(payload: BrowserQaCrawlRequest) -> dict:
        if not bool(getattr(settings.browser_qa, "enabled", True)):
            raise HTTPException(status_code=503, detail="browser.qa disabled")
        arguments: dict = {
            "seed_url": payload.seed_url,
            "persona": payload.persona,
            "seed": payload.seed,
            "allow_destructive_test_actions": payload.allow_destructive_test_actions,
        }
        if payload.budgets is not None:
            arguments["budgets"] = payload.budgets
        if payload.allowed_hosts is not None:
            arguments["allowed_hosts"] = payload.allowed_hosts
        if payload.auth_secret_ref is not None:
            arguments["auth_secret_ref"] = payload.auth_secret_ref
        if payload.auth_lease_id is not None:
            arguments["auth_lease_id"] = payload.auth_lease_id
        if payload.journey_id is not None:
            arguments["journey_id"] = payload.journey_id

        wait = (
            float(payload.wait_seconds)
            if payload.wait_seconds is not None
            else DEFAULT_QA_WAIT_SECONDS
        )
        result = enqueue_and_maybe_await_browser(
            job_runtime,
            capability_id="browser.qa.crawl",
            arguments=arguments,
            approval_id=payload.approval_id,
            requested_by="api.browser.qa",
            run_id=payload.run_id,
            trace_id=payload.trace_id,
            metadata={"browser_qa": "browser.qa.crawl", "via_job_compat": bool(payload.via_job)},
            wait_seconds=wait,
            timeout_seconds=300.0,
            domain_entity_type="browser_qa",
            domain_entity_id=payload.journey_id or payload.run_id,
        )
        http = _job_http_status(result)
        body = {
            **result,
            "truth": {
                **(result.get("truth") or {}),
                "localhost_scoped_by_default": True,
                "no_stealth_anti_bot": True,
                "direct_crawler_control_plane": False,
                "job_runtime_cancel_checkpoint_resume": "EXTERNAL_REQUIRED",
            },
        }
        if http >= 400:
            raise HTTPException(status_code=http, detail=body)
        return body

    @router.get("/api/browser/qa/{journey_id}/status")
    def browser_qa_status(journey_id: str) -> dict:
        """Read JobRuntime / projection — never invokes crawler/browser."""
        if not bool(getattr(settings.browser_qa, "enabled", True)):
            raise HTTPException(status_code=503, detail="browser.qa disabled")
        # Prefer durable JobRuntime projection by domain entity.
        jobs = []
        try:
            store = getattr(job_runtime, "store", None)
            if store is not None and hasattr(store, "list"):
                for job in store.list(limit=50):
                    if (
                        getattr(job, "domain_entity_id", None) == journey_id
                        or getattr(job, "domain_entity_type", None) == "browser_qa"
                        and str(getattr(job, "domain_entity_id", "") or "") == journey_id
                    ):
                        jobs.append(job)
                    elif journey_id in {
                        str((getattr(job, "arguments", None) or {}).get("journey_id") or ""),
                        str(getattr(job, "job_id", "") or ""),
                        str(getattr(job, "run_id", "") or ""),
                    }:
                        jobs.append(job)
        except Exception:  # noqa: BLE001
            jobs = []
        if not jobs and hasattr(job_runtime, "get"):
            # Fallback: treat journey_id as job_id.
            one = job_runtime.get(journey_id)
            if one is not None:
                jobs = [one]
        if not jobs:
            raise HTTPException(status_code=404, detail=f"Unknown QA journey: {journey_id}")
        latest = jobs[0]
        public = latest.public_dict() if hasattr(latest, "public_dict") else {"job_id": getattr(latest, "job_id", None)}
        result_payload = getattr(latest, "result", None) or public.get("result") or {}
        report = result_payload.get("report") if isinstance(result_payload, dict) else None
        return {
            "journey_id": journey_id,
            "job": public,
            "report": report,
            "truth": {
                "job_runtime_cancel_checkpoint_resume": "EXTERNAL_REQUIRED",
                "direct_crawler_control_plane": False,
                "status_does_not_invoke_browser": True,
            },
        }

    @router.post("/api/browser/qa/{journey_id}/cancel")
    def browser_qa_cancel(journey_id: str, payload: BrowserQaJourneyRef | None = None) -> dict:
        if not bool(getattr(settings.browser_qa, "enabled", True)):
            raise HTTPException(status_code=503, detail="browser.qa disabled")
        body = payload or BrowserQaJourneyRef(journey_id=journey_id)
        cancelled = []
        # Cancel by explicit run/job id first.
        targets = [body.run_id] if body.run_id else []
        try:
            store = getattr(job_runtime, "store", None)
            if store is not None and hasattr(store, "list"):
                for job in store.list(limit=50):
                    if getattr(job, "domain_entity_id", None) == journey_id or journey_id in {
                        str((getattr(job, "arguments", None) or {}).get("journey_id") or ""),
                        str(getattr(job, "job_id", "") or ""),
                    }:
                        targets.append(getattr(job, "job_id", None))
        except Exception:  # noqa: BLE001
            pass
        targets.append(journey_id)
        for job_id in {t for t in targets if t}:
            try:
                job_runtime.request_cancel(str(job_id), reason="browser.qa.cancel")
                cancelled.append(str(job_id))
            except Exception:  # noqa: BLE001
                continue
        if not cancelled:
            raise HTTPException(status_code=404, detail=f"Unknown QA journey: {journey_id}")
        return {
            "journey_id": journey_id,
            "cancelled_job_ids": cancelled,
            "truth": {
                "cancelled_is_not_success": True,
                "job_runtime_cancel_checkpoint_resume": "EXTERNAL_REQUIRED",
                "durable_cancel": True,
            },
        }

    @router.post("/api/browser/qa/{journey_id}/replay")
    def browser_qa_replay(journey_id: str, payload: BrowserQaJourneyRef | None = None) -> dict:
        body = payload or BrowserQaJourneyRef(journey_id=journey_id)
        arguments: dict = {"journey_id": journey_id}
        if body.seed is not None:
            arguments["seed"] = body.seed
        wait = (
            float(body.wait_seconds)
            if body.wait_seconds is not None
            else DEFAULT_QA_WAIT_SECONDS
        )
        result = enqueue_and_maybe_await_browser(
            job_runtime,
            capability_id="browser.qa.replay",
            arguments=arguments,
            approval_id=body.approval_id,
            requested_by="api.browser.qa",
            run_id=body.run_id,
            trace_id=body.trace_id,
            metadata={"browser_qa": "browser.qa.replay", "via_job_compat": bool(body.via_job)},
            wait_seconds=wait,
            timeout_seconds=300.0,
            domain_entity_type="browser_qa",
            domain_entity_id=journey_id,
        )
        http = _job_http_status(result)
        if http >= 400:
            raise HTTPException(status_code=http, detail=result)
        return result

    @router.get("/api/browser/qa/{journey_id}/report")
    def browser_qa_report(journey_id: str) -> dict:
        if not bool(getattr(settings.browser_qa, "enabled", True)):
            raise HTTPException(status_code=503, detail="browser.qa disabled")
        # Read completed job result / artifact refs — no crawler invoke.
        jobs = []
        try:
            store = getattr(job_runtime, "store", None)
            if store is not None and hasattr(store, "list"):
                for job in store.list(limit=50):
                    if getattr(job, "domain_entity_id", None) == journey_id or journey_id in {
                        str((getattr(job, "arguments", None) or {}).get("journey_id") or ""),
                        str(getattr(job, "job_id", "") or ""),
                    }:
                        jobs.append(job)
        except Exception:  # noqa: BLE001
            jobs = []
        completed = None
        for job in jobs:
            state = getattr(job, "state", None)
            if state == JobState.COMPLETED or str(state).upper() == "COMPLETED":
                completed = job
                break
        if completed is None and jobs:
            completed = jobs[0]
        if completed is None:
            raise HTTPException(status_code=404, detail=f"Unknown QA journey: {journey_id}")
        result_payload = getattr(completed, "result", None) or {}
        report = result_payload.get("report") if isinstance(result_payload, dict) else None
        artifact_id = None
        if isinstance(result_payload, dict):
            artifact_id = result_payload.get("report_artifact_id") or (
                (result_payload.get("artifact_refs") or [None])[0]
            )
        return {
            "journey_id": journey_id,
            "json": report,
            "artifact_id": artifact_id,
            "job": completed.public_dict() if hasattr(completed, "public_dict") else {},
            "truth": {
                "direct_crawler_control_plane": False,
                "report_from_jobruntime_artifact": True,
            },
        }

    return router
