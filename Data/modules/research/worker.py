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

    from Data.modules.research.service import ResearchService

    settings = ctx.get("settings")
    if settings is None:
        from Data.backend.config import load_settings

        settings = load_settings()

    db_path = getattr(settings, "database_path", None)
    if db_path is None:
        raise RuntimeError("settings.database_path missing; cannot construct ResearchService")

    return ResearchService.from_settings(
        settings,
        db_path=db_path,
        job_runtime=ctx.get("job_runtime"),
    )


def process_research_job(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    """Advance one research job without blocking on all children.

    Job arguments:
      action: advance|plan|retrieve|synthesize|verify|resume|deepen
      project_id: research project id
    """
    store = ctx["job_store"]
    args = dict(getattr(job, "arguments", None) or {})
    capability = str(getattr(job, "capability_id", "") or "")
    action = str(
        args.get("action")
        or (capability.rsplit(".", 1)[-1] if capability.startswith("research.") else "")
        or "advance"
    ).strip().lower()
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

    try:
        deepen = bool(args.get("deepen"))
        extra_rounds = int(args.get("extra_rounds") or 0)
        resume = bool(args.get("resume"))

        if action in {"advance", "run"}:
            if resume:
                result = service.resume(project_id, background=False)
            elif deepen:
                result = service.deepen(
                    project_id,
                    extra_rounds=max(1, extra_rounds),
                    background=False,
                )
            else:
                result = service.run(project_id, background=False)
        elif action == "plan":
            edits = args.get("edits") if isinstance(args.get("edits"), dict) else None
            result = service.plan(project_id, edits=edits)
        elif action == "resume":
            result = service.resume(project_id, background=False)
        elif action == "deepen":
            result = service.deepen(
                project_id,
                extra_rounds=max(1, extra_rounds),
                background=False,
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
