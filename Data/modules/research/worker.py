"""Durable research job handler — framework-executed, LLM-guided continuation."""

from __future__ import annotations

from typing import Any


def _fail(store: Any, job: Any, error: str, *, metadata: dict[str, Any] | None = None, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    worker_id = str((ctx or {}).get("worker_id") or getattr(job, "lease_owner", None) or "")
    try:
        fenced_transition(
            store,
            job.job_id,
            JobState.FAILED,
            worker_id=worker_id,
            ctx=ctx,
            error=error,
            metadata_update=metadata or {},
        )
    except Exception:  # noqa: BLE001
        pass
    return {"error": error}


def _complete(store: Any, job: Any, result: dict[str, Any], *, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    worker_id = str((ctx or {}).get("worker_id") or getattr(job, "lease_owner", None) or "")
    fenced_transition(
        store,
        job.job_id,
        JobState.COMPLETED,
        worker_id=worker_id,
        ctx=ctx,
        result=result,
    )
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


def _cancel_job(
    store: Any,
    job: Any,
    *,
    reason: str,
    metadata: dict[str, Any] | None = None,
    ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    worker_id = str((ctx or {}).get("worker_id") or getattr(job, "lease_owner", None) or "")
    target = JobState.CANCELLED
    # Prefer ack_cancel when kernel already asked for cancel.
    try:
        current = store.get(job.job_id) if hasattr(store, "get") else job
        state = getattr(current, "state", None)
        state_val = state.value if hasattr(state, "value") else str(state or "")
        if state_val == JobState.CANCEL_REQUESTED.value and hasattr(store, "ack_cancel"):
            store.ack_cancel(job.job_id, worker_id=worker_id, reason=reason)
            return {"cancelled": True, "reason": reason, "state": "CANCELLED"}
    except Exception:  # noqa: BLE001
        pass
    try:
        fenced_transition(
            store,
            job.job_id,
            target,
            worker_id=worker_id,
            ctx=ctx,
            error=reason,
            metadata_update=metadata or {},
        )
    except Exception:  # noqa: BLE001
        pass
    return {"cancelled": True, "reason": reason, "state": "CANCELLED"}


def _interrupt_job(
    store: Any,
    job: Any,
    *,
    reason: str,
    metadata: dict[str, Any] | None = None,
    ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Lease loss / fencing — not user cancellation. Prefer retryable FAILED/INTERRUPTED."""
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    worker_id = str((ctx or {}).get("worker_id") or getattr(job, "lease_owner", None) or "")
    # Use FAILED with explicit LEASE_LOST code when INTERRUPTED job state is unavailable.
    target = JobState.FAILED
    meta = {"interrupt_kind": "LEASE_LOST", "retryable": True, **(metadata or {})}
    try:
        fenced_transition(
            store,
            job.job_id,
            target,
            worker_id=worker_id,
            ctx=ctx,
            error=reason,
            error_code="LEASE_LOST",
            metadata_update=meta,
        )
    except Exception:  # noqa: BLE001
        pass
    return {"interrupted": True, "reason": reason, "code": "LEASE_LOST", "state": "FAILED"}


def _fence_reason(ctx: dict[str, Any]) -> str | None:
    """Return 'cancel' | 'lease_lost' | None — never conflate the two."""
    cancel_check = ctx.get("job_cancel_check")
    lease_lost = ctx.get("lease_lost")
    cancel_hit = bool(callable(cancel_check) and cancel_check())
    lease_hit = bool(lease_lost is not None and getattr(lease_lost, "is_set", lambda: False)())
    if cancel_hit and not lease_hit:
        return "cancel"
    if lease_hit and not cancel_hit:
        return "lease_lost"
    if cancel_hit and lease_hit:
        # Prefer explicit cancel when both are set in the same tick.
        return "cancel"
    return None


def process_research_job(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    """Advance one research job without blocking on all children.

    Job arguments:
      action: advance|plan|retrieve|synthesize|verify|resume|deepen|web_probe|fetch_url
      project_id: research project id (not required for web_probe)
    """
    store = ctx["job_store"]
    args = dict(getattr(job, "arguments", None) or {})
    capability = str(getattr(job, "capability_id", "") or "")
    if capability == "research.fetch_url":
        action = "fetch_url"
    elif capability == "research.report.generate":
        action = "regenerate_report"
    elif capability == "research.web.probe":
        action = "web_probe"
    else:
        action = str(
            args.get("action")
            or (capability.rsplit(".", 1)[-1] if capability.startswith("research.") else "")
            or "advance"
        ).strip().lower()
    if args.get("action") and capability not in {
        "research.fetch_url",
        "research.report.generate",
        "research.web.probe",
    }:
        action = str(args.get("action") or action).strip().lower()

    # Web probe has no project_id.
    if action in {"web_probe", "probe"}:
        try:
            service = _construct_research_service(ctx)
        except Exception as exc:  # noqa: BLE001
            return _fail(
                store,
                job,
                f"ResearchService not constructible: {type(exc).__name__}: {exc}",
                metadata={"research_action": action},
                ctx=ctx,
            )
        try:
            probe = service.execute_web_probe(
                query=str(args.get("query") or "SQLite WAL mode"),
                limit=int(args.get("limit") or 3),
            )
            payload = {"action": "web_probe", "probe": probe}
            return _complete(store, job, payload, ctx=ctx)
        except Exception as exc:  # noqa: BLE001
            return _fail(
                store,
                job,
                f"{type(exc).__name__}: {exc}",
                metadata={"research_action": action},
                ctx=ctx,
            )

    project_id = str(args.get("project_id") or "")
    if not project_id:
        return _fail(store, job, "missing project_id", ctx=ctx)

    try:
        service = _construct_research_service(ctx)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            store,
            job,
            f"ResearchService not constructible: {type(exc).__name__}: {exc}",
            metadata={"research_action": action, "project_id": project_id},
            ctx=ctx,
        )

    worker_id = ctx.get("worker_id") or getattr(job, "lease_owner", None)

    def _fence() -> bool:
        return _fence_reason(ctx) is not None

    try:
        deepen = bool(args.get("deepen"))
        extra_rounds = int(args.get("extra_rounds") or 0)
        resume = bool(args.get("resume"))

        if action in {"advance", "run"}:
            reason = _fence_reason(ctx)
            if reason == "cancel":
                try:
                    service.cancel(project_id)
                except Exception:  # noqa: BLE001
                    pass
                return _cancel_job(
                    store,
                    job,
                    reason="RESEARCH_CANCELLED",
                    metadata={"research_action": action, "project_id": project_id},
                    ctx=ctx,
                )
            if reason == "lease_lost":
                return _interrupt_job(
                    store,
                    job,
                    reason="LEASE_LOST before execution",
                    metadata={"research_action": action, "project_id": project_id},
                    ctx=ctx,
                )
            result = service.execute_queued_run(
                project_id,
                deepen=deepen,
                extra_rounds=max(0, extra_rounds),
                resume=resume,
                job_id=getattr(job, "job_id", None),
                worker_id=str(worker_id) if worker_id else None,
                cancel_check=lambda: _fence_reason(ctx) == "cancel",
            )
            reason = _fence_reason(ctx)
            if reason == "cancel":
                status_val = getattr(getattr(result, "status", None), "value", None) or str(
                    getattr(result, "status", "")
                )
                if status_val not in {"completed", "cancelled", "failed"}:
                    try:
                        service.cancel(project_id)
                    except Exception:  # noqa: BLE001
                        pass
                    return _cancel_job(
                        store,
                        job,
                        reason="RESEARCH_CANCELLED during execution",
                        metadata={
                            "research_action": action,
                            "project_id": project_id,
                            "project_status": status_val,
                        },
                        ctx=ctx,
                    )
            if reason == "lease_lost":
                status_val = getattr(getattr(result, "status", None), "value", None) or str(
                    getattr(result, "status", "")
                )
                if status_val not in {"completed", "cancelled", "failed"}:
                    # Domain must stop mutating; mark interrupted when possible.
                    try:
                        from Data.modules.research.types import ResearchPhase, ResearchStatus
                        from Data.modules.research.store import utc_now

                        latest = service.get_project(project_id)
                        if latest.status not in {
                            ResearchStatus.COMPLETED,
                            ResearchStatus.CANCELLED,
                            ResearchStatus.FAILED,
                        }:
                            latest.status = ResearchStatus.INTERRUPTED
                            latest.phase = ResearchPhase.FAILED
                            latest.error = "LEASE_LOST"
                            latest.finished_at = utc_now()
                            service.store.save_project(latest)
                    except Exception:  # noqa: BLE001
                        pass
                    return _interrupt_job(
                        store,
                        job,
                        reason="LEASE_LOST during execution",
                        metadata={
                            "research_action": action,
                            "project_id": project_id,
                            "project_status": status_val,
                        },
                        ctx=ctx,
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
                cancel_check=lambda: _fence_reason(ctx) == "cancel",
            )
        elif action == "deepen":
            result = service.execute_queued_run(
                project_id,
                deepen=True,
                extra_rounds=max(1, extra_rounds),
                job_id=getattr(job, "job_id", None),
                worker_id=str(worker_id) if worker_id else None,
                cancel_check=lambda: _fence_reason(ctx) == "cancel",
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
                    ctx=ctx,
                )
        elif action in {"fetch_url", "url"}:
            url = str(args.get("url") or "").strip()
            if not url:
                return _fail(store, job, "missing url", metadata={"research_action": action}, ctx=ctx)
            source_id = str(args.get("source_id") or "") or None
            result = service.execute_fetch_url(project_id, url, source_id=source_id)
        elif action in {"regenerate_report", "report", "report.generate"}:
            result = service._regenerate_report_inline(project_id)
        elif action in {"retrieve", "synthesize", "synth"}:
            # Coordinator-internal phases — not standalone public capabilities.
            # Fail with CAPABILITY_UNSUPPORTED so catalogs must not advertise AVAILABLE.
            return _fail(
                store,
                job,
                (
                    f"CAPABILITY_UNSUPPORTED: research.{action} is not a standalone "
                    "execution capability; use research.advance"
                ),
                metadata={
                    "research_action": action,
                    "project_id": project_id,
                    "error_code": "CAPABILITY_UNSUPPORTED",
                    "canonical_capability": "research.advance",
                },
                ctx=ctx,
            )
        else:
            return _fail(
                store,
                job,
                f"unsupported research action: {action}",
                metadata={"research_action": action, "project_id": project_id},
                ctx=ctx,
            )

        payload = _public(result)
        payload.setdefault("action", action)
        payload.setdefault("project_id", project_id)
        return _complete(store, job, payload, ctx=ctx)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            store,
            job,
            f"{type(exc).__name__}: {exc}",
            metadata={"research_action": action, "project_id": project_id},
            ctx=ctx,
        )
