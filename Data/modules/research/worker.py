"""Durable research job handler — framework-executed, LLM-guided continuation."""

from __future__ import annotations

from typing import Any


def _fail(store: Any, job: Any, error: str, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    from Data.modules.jobs.states import JobState

    try:
        store.transition(
            job.job_id,
            JobState.FAILED,
            error=error,
            metadata_update=metadata or {},
        )
    except Exception:  # noqa: BLE001
        pass
    return {"error": error}


def _complete(store: Any, job: Any, result: dict[str, Any]) -> dict[str, Any]:
    from Data.modules.jobs.states import JobState

    store.transition(job.job_id, JobState.COMPLETED, result=result)
    return result


def _public(value: Any) -> dict[str, Any]:
    if value is None:
        return {"ok": True}
    if isinstance(value, dict):
        return value
    if hasattr(value, "public_dict"):
        try:
            return dict(value.public_dict())
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "repr": type(value).__name__}


def _construct_research_service(ctx: dict[str, Any]) -> Any:
    """Build ResearchService from worker context / env — never import backend.main."""
    bound = ctx.get("research_service")
    if bound is not None:
        return bound

    from Data.modules.research.worker_context import build_research_worker_context

    built = build_research_worker_context(
        settings=ctx.get("settings"),
        job_runtime=ctx.get("job_runtime"),
    )
    # Cache on ctx for subsequent jobs in this process.
    ctx["research_service"] = built["research_service"]
    ctx.setdefault("knowledge", built.get("knowledge"))
    ctx.setdefault("observability", built.get("observability"))
    ctx.setdefault("model_caller", built.get("model_caller"))
    return built["research_service"]


def process_research_job(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    """Advance one research job without blocking on all children.

    Job arguments:
      action: advance|plan|retrieve|synthesize|verify|resume|deepen
      project_id: research project id
    """
    store = ctx["job_store"]
    args = dict(getattr(job, "arguments", None) or {})
    capability = str(getattr(job, "capability_id", "") or "")
    if capability == "research.fetch_url":
        action = "fetch_url"
    elif capability == "research.report.generate":
        action = "regenerate_report"
    else:
        action = str(
            args.get("action")
            or (capability.rsplit(".", 1)[-1] if capability.startswith("research.") else "")
            or "advance"
        ).strip().lower()
    if args.get("action") and capability not in {
        "research.fetch_url",
        "research.report.generate",
    }:
        action = str(args.get("action") or action).strip().lower()
    project_id = str(args.get("project_id") or "")
    if not project_id:
        return _fail(store, job, "missing project_id")

    try:
        service = _construct_research_service(ctx)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            store,
            job,
            f"ResearchService not constructible: {type(exc).__name__}: {exc}",
            metadata={"research_action": action, "project_id": project_id},
        )

    cancel_check = ctx.get("job_cancel_check")
    lease_lost = ctx.get("lease_lost")
    worker_id = ctx.get("worker_id") or getattr(job, "lease_owner", None)

    def _fence() -> bool:
        if callable(cancel_check) and cancel_check():
            return True
        if lease_lost is not None and getattr(lease_lost, "is_set", lambda: False)():
            return True
        return False

    try:
        deepen = bool(args.get("deepen"))
        extra_rounds = int(args.get("extra_rounds") or 0)
        resume = bool(args.get("resume"))

        if action in {"advance", "run"}:
            # Worker owns the kernel lease — execute claimed QUEUED run.
            # Never call service.run(background=False): QUEUED is ACTIVE and
            # would no-op (the 1% freeze bug).
            if _fence():
                return _fail(
                    store,
                    job,
                    "lease_lost_or_cancel_before_execution",
                    metadata={"research_action": action, "project_id": project_id},
                )
            result = service.execute_queued_run(
                project_id,
                deepen=deepen,
                extra_rounds=max(0, extra_rounds),
                resume=resume,
                job_id=getattr(job, "job_id", None),
                worker_id=str(worker_id) if worker_id else None,
                cancel_check=_fence,
            )
            if _fence() and getattr(result, "status", None) is not None:
                status_val = getattr(getattr(result, "status", None), "value", None) or str(
                    getattr(result, "status", "")
                )
                if status_val not in {"completed", "cancelled", "failed"}:
                    return _fail(
                        store,
                        job,
                        "lease_lost_during_execution",
                        metadata={
                            "research_action": action,
                            "project_id": project_id,
                            "project_status": status_val,
                        },
                    )
        elif action == "plan":
            edits = args.get("edits") if isinstance(args.get("edits"), dict) else None
            result = service.plan(project_id, edits=edits)
        elif action == "resume":
            result = service.execute_queued_run(
                project_id,
                resume=True,
                job_id=getattr(job, "job_id", None),
                worker_id=str(worker_id) if worker_id else None,
                cancel_check=_fence,
            )
        elif action == "deepen":
            result = service.execute_queued_run(
                project_id,
                deepen=True,
                extra_rounds=max(1, extra_rounds),
                job_id=getattr(job, "job_id", None),
                worker_id=str(worker_id) if worker_id else None,
                cancel_check=_fence,
            )
        elif action == "verify":
            # Prefer real service methods when present; otherwise honest failure.
            if hasattr(service, "citation_audit"):
                audit = service.citation_audit(project_id)
                scorecard = (
                    service.quality_scorecard(project_id)
                    if hasattr(service, "quality_scorecard")
                    else None
                )
                result = {
                    "action": "verify",
                    "project_id": project_id,
                    "citation_audit": _public(audit),
                    "quality_scorecard": _public(scorecard) if scorecard is not None else None,
                }
            else:
                return _fail(
                    store,
                    job,
                    "research.verify not supported by ResearchService",
                    metadata={"research_action": action, "project_id": project_id},
                )
        elif action in {"fetch_url", "url"}:
            url = str(args.get("url") or "").strip()
            if not url:
                return _fail(store, job, "missing url", metadata={"research_action": action})
            source_id = str(args.get("source_id") or "") or None
            result = service.execute_fetch_url(project_id, url, source_id=source_id)
        elif action in {"regenerate_report", "report", "report.generate"}:
            result = service._regenerate_report_inline(project_id)
        elif action in {"retrieve", "synthesize"}:
            # These are coordinator-internal phases; durable entry is research.advance.
            return _fail(
                store,
                job,
                (
                    f"research.{action} is not a standalone ResearchService method; "
                    "enqueue research.advance to run the orchestration loop"
                ),
                metadata={"research_action": action, "project_id": project_id},
            )
        else:
            return _fail(
                store,
                job,
                f"unsupported research action: {action}",
                metadata={"research_action": action, "project_id": project_id},
            )

        payload = _public(result)
        payload.setdefault("action", action)
        payload.setdefault("project_id", project_id)
        return _complete(store, job, payload)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            store,
            job,
            f"{type(exc).__name__}: {exc}",
            metadata={"research_action": action, "project_id": project_id},
        )
