"""Browser pool entrypoint — singleton Playwright / BrowserWorker owner.

Retains BrowserWorker + QA crawler for the process lifetime. FastAPI never
starts Playwright or launches Chromium; this worker owns that lifecycle.
"""

from __future__ import annotations

import atexit
import os
from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool


def _build_browser_executor(ctx: dict[str, Any]) -> Any:
    from Data.modules.browser import BrowserJourneyCrawler, BrowserWorker, CrawlBudget
    from Data.modules.browser.readiness import BrowserReadinessCache

    settings = ctx.get("settings")
    artifact_store = ctx.get("artifact_store")
    backend_kind = (
        os.environ.get("LEVIATHAN_BROWSER_BACKEND")
        or getattr(getattr(settings, "browser", None), "backend", None)
        or "local_dom"
    )
    # Production worker must never default to fixture as "ready".
    if str(backend_kind).lower() == "fixture":
        backend_kind = "local_dom"

    filesystem_root = getattr(settings, "project_root", None) or getattr(
        getattr(settings, "coding", None), "workspace", None
    )
    session_ttl = float(
        getattr(getattr(settings, "browser", None), "session_ttl_seconds", 900.0) or 900.0
    )
    worker = BrowserWorker(
        artifact_store=artifact_store,
        backend_kind=str(backend_kind),
        filesystem_root=str(filesystem_root) if filesystem_root else None,
        allow_network=True,
        session_ttl_seconds=session_ttl,
        worker_generation=str(
            os.environ.get("LEVIATHAN_WORKER_SUPERVISOR_GENERATION")
            or os.environ.get("LEVIATHAN_WORKER_ID")
            or f"browser-{os.getpid()}"
        ),
    )
    qa_hosts = tuple(
        h.strip().lower()
        for h in str(
            getattr(getattr(settings, "browser_qa", None), "allowed_hosts", "localhost,127.0.0.1,::1")
        ).split(",")
        if h.strip()
    )
    crawler = BrowserJourneyCrawler(
        browser_worker=BrowserWorker(
            artifact_store=artifact_store,
            backend_kind=str(backend_kind),
            filesystem_root=str(filesystem_root) if filesystem_root else None,
            allow_network=True,
            qa_crawler=False,  # type: ignore[arg-type]
            session_ttl_seconds=session_ttl,
            worker_generation=worker.worker_generation,
        ),
        artifact_store=artifact_store,
        allowed_hosts=qa_hosts or ("localhost", "127.0.0.1", "::1"),
        budget=CrawlBudget(
            max_pages=int(getattr(getattr(settings, "browser_qa", None), "max_pages", 50) or 50),
            max_actions=int(getattr(getattr(settings, "browser_qa", None), "max_actions", 200) or 200),
        ),
        allow_destructive=bool(
            getattr(getattr(settings, "browser_qa", None), "allow_destructive_test_actions", False)
        ),
        slice_max_actions=int(
            getattr(getattr(settings, "browser_qa", None), "slice_max_actions", 12) or 12
        ),
        slice_max_seconds=float(
            getattr(getattr(settings, "browser_qa", None), "slice_max_seconds", 12.0) or 12.0
        ),
    )
    worker._qa_crawler = crawler
    readiness = BrowserReadinessCache()
    # Lazy Chromium: measure readiness on first probe / status, not necessarily at boot.
    ctx["browser_readiness"] = readiness
    ctx["browser_worker"] = worker
    ctx["browser_qa_crawler"] = crawler

    gateway = ctx.get("gateway")
    if gateway is not None:
        gateway.browser_executor = worker

    def _shutdown() -> None:
        try:
            closer = getattr(getattr(worker, "backend", None), "close", None)
            if callable(closer):
                closer()
        except Exception:  # noqa: BLE001
            pass
        try:
            worker.shutdown()
        except Exception:  # noqa: BLE001
            pass

    atexit.register(_shutdown)
    return worker


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState
    from Data.modules.workers.loop import _default_gateway_execute

    worker_id = str(ctx.get("worker_id") or os.environ.get("LEVIATHAN_WORKER_ID") or "")
    if ctx.get("browser_worker") is None:
        try:
            _build_browser_executor(ctx)
        except Exception as exc:  # noqa: BLE001
            fenced_transition(
                ctx["job_store"],
                job.job_id,
                JobState.FAILED,
                worker_id=worker_id,
                ctx=ctx,
                error=f"BROWSER_WORKER_UNAVAILABLE: {exc}",
                result={
                    "error_code": "BROWSER_WORKER_UNAVAILABLE",
                    "capability_id": getattr(job, "capability_id", None),
                },
            )
            return {"error": "BROWSER_WORKER_UNAVAILABLE", "detail": str(exc)}

    # Expire idle sessions between jobs.
    try:
        ctx["browser_worker"].expire_idle_sessions()
    except Exception:  # noqa: BLE001
        pass

    capability = str(getattr(job, "capability_id", "") or "")
    # QA continuation: after a crawl slice that needs more work, enqueue advance.
    result = _default_gateway_execute(
        ctx["job_runtime"],
        ctx["job_store"],
        job,
        worker_id,
        float(getattr(ctx.get("worker_settings"), "lease_ttl_seconds", 60.0) or 60.0),
        ctx=ctx,
    )
    if capability in {"browser.qa.crawl", "browser.qa.advance"} and isinstance(result, dict):
        report = result.get("report") if isinstance(result.get("report"), dict) else result
        if isinstance(report, dict) and report.get("needs_continuation"):
            try:
                from Data.modules.execution.browser_dispatch import enqueue_browser_job

                enqueue_browser_job(
                    ctx["job_runtime"],
                    capability_id="browser.qa.advance",
                    arguments={
                        "journey_id": report.get("journey_id") or (job.arguments or {}).get("journey_id"),
                        "run_id": report.get("run_id") or getattr(job, "run_id", None),
                        "checkpoint": report.get("checkpoint") or {},
                    },
                    requested_by="browser.worker.continuation",
                    run_id=getattr(job, "run_id", None),
                    metadata={
                        "parent_job_id": job.job_id,
                        "continuation": True,
                    },
                    domain_entity_type="browser_qa",
                    domain_entity_id=str(report.get("journey_id") or ""),
                    timeout_seconds=300.0,
                )
            except Exception:  # noqa: BLE001 — continuation failure surfaces on next status
                pass
    return result or {}


def main(argv=None):
    return main_for_pool("browser", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
