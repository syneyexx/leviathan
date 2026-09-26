"""Thin FastAPI routes for localhost Browser QA crawler (GI9/GI14)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


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


def build_browser_qa_router(browser_worker: Any) -> APIRouter:
    """Compose thin routes — business logic stays in browser.qa_crawler."""
    router = APIRouter(tags=["browser-qa"])

    def _crawler():
        return browser_worker.get_qa_crawler()

    @router.post("/api/browser/qa/crawls")
    def start_crawl(payload: QaCrawlRequest) -> dict:
        try:
            result = browser_worker.execute(
                action="QA_CRAWL",
                arguments=payload.model_dump(),
                run_id=payload.run_id,
                request_id=payload.trace_id,
            )
            return result
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "error_code", None) or type(exc).__name__
            status = 403 if code == "CRAWLER_TARGET_NOT_ALLOWED" else 400
            raise HTTPException(
                status_code=status,
                detail={"error": code, "message": str(exc)},
            ) from exc

    @router.get("/api/browser/qa/crawls/{journey_id}")
    def crawl_status(journey_id: str) -> dict:
        result = browser_worker.execute(
            action="QA_STATUS",
            arguments={"journey_id": journey_id},
        )
        if result.get("status") == "NOT_FOUND" or result.get("error_code") == "CRAWLER_NOT_FOUND":
            raise HTTPException(status_code=404, detail=result)
        return result

    @router.post("/api/browser/qa/crawls/{journey_id}/cancel")
    def crawl_cancel(journey_id: str) -> dict:
        return browser_worker.execute(
            action="QA_CANCEL",
            arguments={"journey_id": journey_id},
        )

    @router.post("/api/browser/qa/crawls/{journey_id}/replay")
    def crawl_replay(journey_id: str, seed: int | None = None) -> dict:
        return browser_worker.execute(
            action="QA_REPLAY",
            arguments={"journey_id": journey_id, "seed": seed},
        )

    @router.get("/api/browser/qa/crawls/{journey_id}/report")
    def crawl_report(journey_id: str) -> dict:
        return browser_worker.execute(
            action="QA_REPORT",
            arguments={"journey_id": journey_id},
        )

    return router
