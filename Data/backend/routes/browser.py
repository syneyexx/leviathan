"""Browser request + legacy Browser QA journey HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from Data.modules.browser import BrowserAction
from Data.modules.execution import CapabilityRequest, CapabilityStatus


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
    via_job: bool = False


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


class BrowserQaJourneyRef(BaseModel):
    journey_id: str = Field(min_length=1, max_length=120)
    seed: int | None = None
    approval_id: str | None = None
    run_id: str | None = None
    trace_id: str | None = None
    via_job: bool = False


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


def build_browser_router(
    *,
    settings: Any,
    browser_stub: Any,
    browser_qa_crawler: Any,
    execution_gateway: Any,
    job_runtime: Any,
    observability: Any,
) -> APIRouter:
    """Legacy `/api/browser/request` + `/api/browser/qa/{journey_id}/*` surfaces.

    Newer crawl control-plane routes live in ``browser_qa.py``
    (``/api/browser/qa/crawls``).
    """
    router = APIRouter(tags=["browser"])

    def _browser_qa_via_gateway(
        *,
        capability_id: str,
        arguments: dict,
        approval_id: str | None,
        run_id: str | None,
        trace_id: str | None,
        via_job: bool,
    ) -> dict:
        if not settings.features.capability_world:
            raise HTTPException(status_code=501, detail="capability_world disabled")
        if via_job:
            job = job_runtime.enqueue(
                capability_id=capability_id,
                arguments=arguments,
                run_id=run_id,
                approval_id=approval_id,
                requested_by="api.browser.qa",
                trace_id=trace_id,
                metadata={"browser_qa": capability_id},
            )
            return {
                "job": job.public_dict(),
                "capability_id": capability_id,
                "truth": {
                    "requires_capability_gateway": True,
                    "job_runtime_cancel_checkpoint_resume": "EXTERNAL_REQUIRED",
                    "routed_via_job": True,
                },
            }
        result = execution_gateway.execute(
            CapabilityRequest(
                capability_id=capability_id,
                arguments=arguments,
                approval_id=approval_id,
                run_id=run_id,
                requested_by="api.browser.qa",
                trace_id=trace_id,
            )
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
                "job_runtime_cancel_checkpoint_resume": "EXTERNAL_REQUIRED",
                "localhost_scoped_by_default": True,
                "no_stealth_anti_bot": True,
            },
        }

    @router.post("/api/browser/request")
    def browser_request(payload: BrowserRequest) -> dict:
        """Browser actions go through ExecutionGateway (no private bypass)."""
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

        if payload.via_job:
            job = job_runtime.enqueue(
                capability_id=capability_id,
                arguments=arguments,
                run_id=payload.run_id,
                approval_id=payload.approval_id,
                requested_by="api.browser",
                trace_id=payload.trace_id,
                metadata={"browser_action": action.value},
            )
            processed = job_runtime.process_next()
            final = job_runtime.get(job.job_id) or processed or job
            return {
                "job": final.public_dict(),
                "capability_id": capability_id,
                "truth": {
                    "requires_capability_gateway": True,
                    "no_private_browser_bypass": True,
                    "routed_via_job": True,
                },
            }

        result = execution_gateway.execute(
            CapabilityRequest(
                capability_id=capability_id,
                arguments=arguments,
                approval_id=payload.approval_id,
                run_id=payload.run_id,
                requested_by="api.browser",
                trace_id=payload.trace_id,
            )
        )
        observability.emit(
            "browser",
            "request",
            payload={
                "capability_id": capability_id,
                "status": result.status.value,
                "request_id": result.request_id,
                "run_id": payload.run_id,
                "trace_id": payload.trace_id,
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
                "no_private_browser_bypass": True,
                "fixture_is_not_chromium": True,
            },
        }

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
        if payload.via_job:
            return _browser_qa_via_gateway(
                capability_id="browser.qa.crawl",
                arguments=arguments,
                approval_id=payload.approval_id,
                run_id=payload.run_id,
                trace_id=payload.trace_id,
                via_job=True,
            )
        # Direct control-plane path for local/dev (worker path remains via_job=True).
        from Data.modules.browser import JourneyPersona

        persona_raw = str(payload.persona or "DESKTOP_MOUSE")
        try:
            persona = JourneyPersona(persona_raw.upper())
        except ValueError:
            persona = JourneyPersona.DESKTOP_MOUSE
        if payload.allowed_hosts:
            browser_qa_crawler.allowed_hosts = tuple(str(h).lower() for h in payload.allowed_hosts)
        if payload.budgets:
            from Data.modules.browser import CrawlBudget

            b = payload.budgets
            browser_qa_crawler.budget = CrawlBudget(
                max_pages=int(b.get("max_pages", browser_qa_crawler.budget.max_pages)),
                max_actions=int(b.get("max_actions", browser_qa_crawler.budget.max_actions)),
                max_wall_time_seconds=float(
                    b.get(
                        "max_wall_time_seconds",
                        b.get("max_wall_time_s", browser_qa_crawler.budget.max_wall_time_seconds),
                    )
                ),
            )
        browser_qa_crawler.allow_destructive = bool(payload.allow_destructive_test_actions)
        report = browser_qa_crawler.run(
            start_url=payload.seed_url,
            persona=persona,
            seed=int(payload.seed),
            run_id=payload.run_id,
        )
        return {
            "report": report.public_dict(),
            "capability_id": "browser.qa.crawl",
            "truth": {
                "requires_capability_gateway": False,
                "direct_crawler_control_plane": True,
                "job_runtime_cancel_checkpoint_resume": "EXTERNAL_REQUIRED",
                "localhost_scoped_by_default": True,
                "no_stealth_anti_bot": True,
            },
        }

    @router.get("/api/browser/qa/{journey_id}/status")
    def browser_qa_status(journey_id: str) -> dict:
        if not bool(getattr(settings.browser_qa, "enabled", True)):
            raise HTTPException(status_code=503, detail="browser.qa disabled")
        try:
            report = browser_qa_crawler.status(journey_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown QA journey: {journey_id}") from exc
        return {
            "journey_id": journey_id,
            "report": report.public_dict(),
            "truth": {
                "job_runtime_cancel_checkpoint_resume": "EXTERNAL_REQUIRED",
                "direct_crawler_control_plane": True,
            },
        }

    @router.post("/api/browser/qa/{journey_id}/cancel")
    def browser_qa_cancel(journey_id: str, payload: BrowserQaJourneyRef | None = None) -> dict:
        if not bool(getattr(settings.browser_qa, "enabled", True)):
            raise HTTPException(status_code=503, detail="browser.qa disabled")
        body = payload or BrowserQaJourneyRef(journey_id=journey_id)
        if body.via_job and body.run_id:
            try:
                job_runtime.request_cancel(body.run_id, reason="browser.qa.cancel")
            except Exception:  # noqa: BLE001
                pass
        try:
            report = browser_qa_crawler.cancel(journey_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown QA journey: {journey_id}") from exc
        return {
            "journey_id": journey_id,
            "report": report.public_dict(),
            "truth": {
                "cancelled_is_not_success": True,
                "job_runtime_cancel_checkpoint_resume": "EXTERNAL_REQUIRED",
            },
        }

    @router.post("/api/browser/qa/{journey_id}/replay")
    def browser_qa_replay(journey_id: str, payload: BrowserQaJourneyRef | None = None) -> dict:
        body = payload or BrowserQaJourneyRef(journey_id=journey_id)
        arguments: dict = {"journey_id": journey_id}
        if body.seed is not None:
            arguments["seed"] = body.seed
        return _browser_qa_via_gateway(
            capability_id="browser.qa.replay",
            arguments=arguments,
            approval_id=body.approval_id,
            run_id=body.run_id,
            trace_id=body.trace_id,
            via_job=body.via_job,
        )

    @router.get("/api/browser/qa/{journey_id}/report")
    def browser_qa_report(journey_id: str) -> dict:
        if not bool(getattr(settings.browser_qa, "enabled", True)):
            raise HTTPException(status_code=503, detail="browser.qa disabled")
        try:
            payload = browser_qa_crawler.report_artifact(journey_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown QA journey: {journey_id}") from exc
        return {
            "journey_id": journey_id,
            **payload,
            "truth": {"direct_crawler_control_plane": True},
        }

    return router
