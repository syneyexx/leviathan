"""Coding/build HTTP family extracted from capability_routes (Wave 29).

Preserves URLs, payloads, status codes and auth/policy behavior.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Body, HTTPException, Query, status
from pydantic import BaseModel

import fastapi_nested_annotations  # noqa: F401 — nested PEP 563 OpenAPI fix


def _publish_route_models(models: dict[str, type[BaseModel]]) -> None:
    """Expose nested-route Pydantic types on this module.

    `from __future__ import annotations` stores parameter types as strings.
    FastAPI/Pydantic resolve those strings via the function's *module* globals,
    not the enclosing `register_coding_build_routes` locals. Unresolved
    ForwardRefs are treated as Query params and `/openapi.json` raises
    `PydanticUserError: TypeAdapter[Annotated[ForwardRef('BuildPlanInput'), Query(...)]]`.
    """
    module = sys.modules[__name__]
    for name, cls in models.items():
        setattr(module, name, cls)


def register_coding_build_routes(
    router: APIRouter,
    *,
    s: Any,
    models: dict[str, type[BaseModel]],
    enforce_subprocess_policy: Callable[..., None],
    project_service_factory: Callable[[], Any],
) -> None:
    _publish_route_models(models)
    BuildPlanInput = models["BuildPlanInput"]
    BuildRunInput = models["BuildRunInput"]
    BuildEdit = models["BuildEdit"]
    CodingGoalInput = models["CodingGoalInput"]
    CodingJobStartInput = models["CodingJobStartInput"]
    CodingJobRedirectInput = models["CodingJobRedirectInput"]
    BuildApplyInput = models["BuildApplyInput"]

    def _project_service():
        return project_service_factory()

    def _base_lm_chat_fn(*, run_id: str | None = None) -> Any:
        factory = s.get("lm_client")
        if not callable(factory):
            return None
        try:
            from lm_studio import attach_lm_run

            client = factory()
            if run_id:
                attach_lm_run(client, str(run_id))
            return getattr(client, "chat", None)
        except Exception:
            return None

    def _bind_coding_chat_fn(run_params: dict[str, Any] | None = None, *, use_omniroute: bool = False) -> Any:
        from coding_omniroute import OmniRouteCodingChat, wrap_coding_chat_fn
        from coding_model_runtime import is_coding_run_cancelled, new_coding_run_id

        params = run_params or {}
        requested = bool(params.get("use_omniroute") if "use_omniroute" in params else use_omniroute)
        job_id = params.get("job_id")
        # Canonical cancel identity: job_id for async jobs; ephemeral for sync routes.
        run_id = str(job_id or params.get("model_run_id") or "").strip() or None
        if not run_id:
            run_id = new_coding_run_id(prefix="coding-sync")
            params = {**params, "model_run_id": run_id}
        progress = params.get("progress")
        base = _base_lm_chat_fn(run_id=run_id)

        def cancel_check() -> bool:
            if is_coding_run_cancelled(run_id):
                return True
            if not job_id:
                return False
            try:
                rec = _coding_job_store().get(str(job_id))
            except Exception:
                return False
            return bool(rec.get("cancel_requested") or str(rec.get("status") or "") in {"cancelled", "cancel_requested"})

        def on_snapshot(snap: dict[str, Any]) -> None:
            if callable(progress):
                progress("MODEL_ROUTING", snap)

        def settings() -> dict[str, Any]:
            getter = s.get("runtime_values")
            if callable(getter):
                try:
                    return dict(getter() or {})
                except Exception:
                    return {}
            return {}

        wrapped = wrap_coding_chat_fn(
            base,
            use_omniroute=requested,
            plugin_manager=s.get("plugin_manager"),
            settings=settings,
            explicit_model=params.get("model_id"),
            cancel_check=cancel_check,
            on_snapshot=on_snapshot if (job_id and callable(progress)) else None,
        )
        # Stash run identity for callers that need it (sync goal attaches via params).
        try:
            setattr(wrapped, "_hades_coding_run_id", run_id)
            setattr(wrapped, "_hades_coding_cancel_check", cancel_check)
        except Exception:
            pass
        return wrapped

    def _attach_omniroute_result(result: dict[str, Any], chat_fn: Any, *, requested: bool) -> dict[str, Any]:
        from coding_omniroute import OmniRouteCodingChat, public_routing_snapshot

        if not requested:
            return result
        payload = dict(result or {})
        coding = dict(payload.get("coding") or {})
        snap = None
        if isinstance(chat_fn, OmniRouteCodingChat):
            snap = chat_fn.last_snapshot
        coding["omniroute"] = public_routing_snapshot(snap or {"omniroute_requested": True, "omniroute_used": False})
        payload["coding"] = coding
        payload["omniroute"] = coding["omniroute"]
        return payload


    @router.post("/build/plan")
    async def build_plan(values: BuildPlanInput = Body()) -> dict[str, Any]:
        from build_agent import FileEdit, plan_multi_file_edits

        edits = [
            FileEdit(
                path=item.path,
                action=item.action,
                content=item.content,
                old_content=item.old_content,
                start_line=item.start_line,
                end_line=item.end_line,
            )
            for item in values.edits
        ]
        try:
            return plan_multi_file_edits(edits, goal=values.goal)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/build/run")
    async def build_run(values: BuildRunInput = Body()) -> dict[str, Any]:
        from build_agent import FileEdit

        def _to_edits(items: list[BuildEdit]) -> list[FileEdit]:
            return [
                FileEdit(
                    path=item.path,
                    action=item.action,
                    content=item.content,
                    old_content=item.old_content,
                    start_line=item.start_line,
                    end_line=item.end_line,
                )
                for item in items
            ]

        edits = _to_edits(values.edits)
        repair_waves = [_to_edits(wave) for wave in values.repair_waves]
        try:
            if values.goal and not edits and values.auto_repair:
                from coding_agent import CodingAgentService

                requested = bool(getattr(values, "use_omniroute", False))
                chat_fn = _bind_coding_chat_fn({"use_omniroute": requested, "model_id": getattr(values, "model_id", None)})
                coding = CodingAgentService(s.build_service)
                run_id = str(getattr(chat_fn, "_hades_coding_run_id", "") or "")
                cancel_check = getattr(chat_fn, "_hades_coding_cancel_check", None)
                payload = coding.run_from_goal(
                    Path(values.source_repo),
                    values.goal,
                    test_suite=values.test_suite,
                    test_args=values.test_args,
                    max_attempts=values.max_attempts,
                    repair_waves=repair_waves,
                    auto_repair=True,
                    chat_fn=chat_fn,
                    model_id=getattr(values, "model_id", None),
                    model_run_id=run_id or None,
                    cancel_check=cancel_check,
                )
                return _attach_omniroute_result(payload, chat_fn, requested=requested)
            result = s.build_service.run_repair_loop(
                Path(values.source_repo),
                edits,
                test_suite=values.test_suite,
                test_args=values.test_args,
                max_attempts=values.max_attempts,
                repair_waves=repair_waves,
                goal=values.goal,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result.to_dict()

    @router.post("/build/goal")
    async def build_from_goal(values: CodingGoalInput = Body()) -> dict[str, Any]:
        """Natural-language coding run: explore → edit → test → auto-repair → reviewable diff.

        Runs the same CodingAgentService off the event loop so status/chat stay responsive.
        For fire-and-forget with reconnect, prefer POST /build/goal/async.
        """
        enforce_subprocess_policy(values.approved_subprocess, "coding/build goal uitvoeren")
        from build_agent import FileEdit
        from coding_agent import CodingAgentService

        def _to_edits(items: list[BuildEdit]) -> list[FileEdit]:
            return [
                FileEdit(
                    path=item.path,
                    action=item.action,
                    content=item.content,
                    old_content=item.old_content,
                    start_line=item.start_line,
                    end_line=item.end_line,
                )
                for item in items
            ]

        def _resolve_goal_model_id(explicit: str | None) -> tuple[str | None, dict[str, Any]]:
            from coding_model_resolve import resolve_coding_model_from_runtime

            inventory = None
            try:
                factory = s.get("lm_client")
                if callable(factory):
                    client = factory()
                    lister = getattr(client, "list_models", None) or getattr(client, "models", None)
                    if callable(lister):
                        inventory_fn = lister
                    else:
                        inventory_fn = None
                else:
                    inventory_fn = None
            except Exception:
                inventory_fn = None

            def _profile() -> Any:
                db = s.get("database")
                if db is None:
                    return {}
                try:
                    return db.active_profile()
                except Exception:
                    return {}

            def _runtime() -> dict[str, Any]:
                getter = s.get("runtime_values")
                if callable(getter):
                    try:
                        return dict(getter() or {})
                    except Exception:
                        return {}
                return {}

            resolved = resolve_coding_model_from_runtime(
                explicit_model_id=explicit,
                use_omniroute=False,
                runtime_values=_runtime(),
                list_models=inventory_fn,
                active_profile=_profile,
            )
            return resolved.model_id, resolved.to_dict()

        def _run() -> dict[str, Any]:
            requested = bool(getattr(values, "use_omniroute", False))
            resolved_id, model_meta = _resolve_goal_model_id(values.model_id)
            effective_model = values.model_id or resolved_id
            chat_fn = _bind_coding_chat_fn({"use_omniroute": requested, "model_id": effective_model})
            coding = CodingAgentService(s.build_service)
            run_id = str(getattr(chat_fn, "_hades_coding_run_id", "") or "")
            cancel_check = getattr(chat_fn, "_hades_coding_cancel_check", None)
            snapshot = {
                "use_omniroute": requested,
                "model_resolved": model_meta,
                "active_model": effective_model,
                "profile_model_id": model_meta.get("details", {}).get("profile_model_id"),
                "job_id": run_id,
            }
            payload = coding.run_from_goal(
                Path(values.source_repo),
                values.goal,
                test_suite=values.test_suite,
                test_args=values.test_args,
                max_attempts=values.max_attempts,
                edits=_to_edits(values.edits) or None,
                repair_waves=[_to_edits(wave) for wave in values.repair_waves] or None,
                chat_fn=chat_fn,
                model_id=effective_model,
                auto_repair=values.auto_repair,
                strategy=values.strategy,
                autonomy_profile=values.autonomy_profile,
                task_type=values.task_type,
                config_snapshot=snapshot,
                model_run_id=run_id or None,
                cancel_check=cancel_check,
            )
            coding_block = dict(payload.get("coding") or {})
            coding_block["model_resolved"] = model_meta
            payload["coding"] = coding_block
            return _attach_omniroute_result(payload, chat_fn, requested=requested)

        try:
            return await asyncio.to_thread(_run)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _coding_job_store():
        from coding_jobs import get_coding_job_store

        data_root = s.get("data_root")
        store = get_coding_job_store(data_root)

        def factory(params: dict[str, Any]):
            # Rebuild runner from persisted params (edits/repair_waves included).
            from build_agent import FileEdit
            from coding_agent import CodingAgentService

            def _to_edits(items: list[Any] | None) -> list[FileEdit]:
                out: list[FileEdit] = []
                for item in items or []:
                    if isinstance(item, FileEdit):
                        out.append(item)
                        continue
                    if isinstance(item, dict):
                        out.append(
                            FileEdit(
                                path=str(item.get("path") or ""),
                                action=str(item.get("action") or "replace"),  # type: ignore[arg-type]
                                content=item.get("content"),
                                old_content=item.get("old_content"),
                                start_line=item.get("start_line"),
                                end_line=item.get("end_line"),
                            )
                        )
                return out

            def runner(run_params: dict[str, Any]) -> dict[str, Any]:
                merged = {**params, **run_params}
                chat_fn = _bind_coding_chat_fn(merged)
                coding = CodingAgentService(s.build_service)
                continuity = None
                try:
                    continuity = _project_service()
                except Exception:
                    continuity = None
                run_id = str(merged.get("job_id") or getattr(chat_fn, "_hades_coding_run_id", "") or "")
                cancel_check = getattr(chat_fn, "_hades_coding_cancel_check", None)
                payload = coding.run_from_goal(
                    Path(merged.get("source_repo") or ""),
                    str(merged.get("goal") or ""),
                    test_suite=str(merged.get("test_suite") or "unittest"),
                    test_args=list(merged.get("test_args") or []),
                    max_attempts=int(merged.get("max_attempts") or 3),
                    edits=_to_edits(merged.get("edits")) or None,
                    repair_waves=[_to_edits(wave) for wave in (merged.get("repair_waves") or [])] or None,
                    chat_fn=chat_fn,
                    model_id=merged.get("model_id"),
                    auto_repair=bool(merged.get("auto_repair", True)),
                    strategy=str(merged.get("strategy") or "fast"),
                    progress=merged.get("progress"),
                    redirect_notes=merged.get("redirect_notes"),
                    instructions=merged.get("instructions"),
                    fetch_instructions=merged.get("fetch_instructions"),
                    apply_instructions=merged.get("apply_instructions"),
                    job_checkpoint=merged.get("job_checkpoint"),
                    selector_mode=str(merged.get("selector_mode") or "deterministic"),
                    config_snapshot={**(merged.get("config_snapshot") or {}), "job_id": run_id},
                    autonomy_profile=str(merged.get("autonomy_profile") or "reviewable_result"),
                    task_type=merged.get("task_type"),
                    project_id=merged.get("project_id"),
                    continuity=continuity,
                    model_run_id=run_id or None,
                    cancel_check=cancel_check,
                )
                return _attach_omniroute_result(payload, chat_fn, requested=bool(merged.get("use_omniroute") or False))

            return runner

        store.set_runner_factory(factory)
        return store

    def _make_coding_runner(values: CodingGoalInput):
        from build_agent import FileEdit
        from coding_agent import CodingAgentService

        def _to_edits(items: list[BuildEdit]) -> list[FileEdit]:
            return [
                FileEdit(
                    path=item.path,
                    action=item.action,
                    content=item.content,
                    old_content=item.old_content,
                    start_line=item.start_line,
                    end_line=item.end_line,
                )
                for item in items
            ]

        def runner(params: dict[str, Any]) -> dict[str, Any]:
            merged = {
                "use_omniroute": params.get("use_omniroute", getattr(values, "use_omniroute", False)),
                "model_id": params.get("model_id") or values.model_id,
                **params,
            }
            chat_fn = _bind_coding_chat_fn(merged)
            coding = CodingAgentService(s.build_service)
            continuity = None
            try:
                continuity = _project_service()
            except Exception:
                continuity = None
            run_id = str(merged.get("job_id") or getattr(chat_fn, "_hades_coding_run_id", "") or "")
            cancel_check = getattr(chat_fn, "_hades_coding_cancel_check", None)
            payload = coding.run_from_goal(
                Path(params.get("source_repo") or values.source_repo),
                str(params.get("goal") or values.goal),
                test_suite=str(params.get("test_suite") or values.test_suite),
                test_args=list(params.get("test_args") or values.test_args),
                max_attempts=int(params.get("max_attempts") or values.max_attempts),
                edits=_to_edits(values.edits) or None,
                repair_waves=[_to_edits(wave) for wave in values.repair_waves] or None,
                chat_fn=chat_fn,
                model_id=params.get("model_id") or values.model_id,
                auto_repair=bool(params.get("auto_repair", values.auto_repair)),
                strategy=str(params.get("strategy") or values.strategy),
                progress=params.get("progress"),
                redirect_notes=params.get("redirect_notes"),
                instructions=params.get("instructions"),
                fetch_instructions=params.get("fetch_instructions"),
                apply_instructions=params.get("apply_instructions"),
                job_checkpoint=params.get("job_checkpoint"),
                selector_mode=str(params.get("selector_mode") or getattr(values, "selector_mode", "deterministic") or "deterministic"),
                config_snapshot={**(params.get("config_snapshot") or {}), "job_id": run_id},
                autonomy_profile=str(
                    params.get("autonomy_profile")
                    or getattr(values, "autonomy_profile", None)
                    or "reviewable_result"
                ),
                task_type=params.get("task_type") or getattr(values, "task_type", None),
                project_id=params.get("project_id"),
                continuity=continuity,
                model_run_id=run_id or None,
                cancel_check=cancel_check,
            )
            return _attach_omniroute_result(payload, chat_fn, requested=bool(merged.get("use_omniroute") or False))

        return runner

    @router.post("/build/goal/async", status_code=status.HTTP_202_ACCEPTED)
    async def build_from_goal_async(values: CodingJobStartInput = Body()) -> dict[str, Any]:
        """Start a coding run in the background; returns job id immediately."""
        enforce_subprocess_policy(values.approved_subprocess, "async coding/build goal starten")
        store = _coding_job_store()
        store.recover_stale()
        # Persist serializable edits for recovery (not only the closure).
        edits_payload = [item.model_dump() for item in values.edits]
        waves_payload = [[item.model_dump() for item in wave] for wave in values.repair_waves]
        from coding_model_resolve import resolve_coding_model_from_runtime

        def _profile() -> Any:
            db = s.get("database")
            if db is None:
                return {}
            try:
                return db.active_profile()
            except Exception:
                return {}

        def _runtime() -> dict[str, Any]:
            getter = s.get("runtime_values")
            if callable(getter):
                try:
                    return dict(getter() or {})
                except Exception:
                    return {}
            return {}

        inventory_fn = None
        try:
            factory = s.get("lm_client")
            if callable(factory):
                client = factory()
                inventory_fn = getattr(client, "list_models", None) or getattr(client, "models", None)
        except Exception:
            inventory_fn = None

        resolved = resolve_coding_model_from_runtime(
            explicit_model_id=values.model_id,
            use_omniroute=bool(getattr(values, "use_omniroute", False)),
            runtime_values=_runtime(),
            list_models=inventory_fn if callable(inventory_fn) else None,
            active_profile=_profile,
        )
        effective_model = values.model_id or resolved.model_id
        config_snapshot = {
            "strategy": values.strategy,
            "model_id": effective_model,
            "use_omniroute": bool(getattr(values, "use_omniroute", False)),
            "max_attempts": values.max_attempts,
            "test_suite": values.test_suite,
            "autonomy_profile": values.autonomy_profile,
            "task_type": values.task_type,
            "selector_mode": getattr(values, "selector_mode", "deterministic"),
            "model_resolved": resolved.to_dict(),
            "active_model": effective_model,
        }
        job = store.start(
            runner=_make_coding_runner(values),
            params={
                "source_repo": values.source_repo,
                "goal": values.goal,
                "original_goal": values.goal,
                "test_suite": values.test_suite,
                "test_args": values.test_args,
                "max_attempts": values.max_attempts,
                "strategy": values.strategy,
                "model_id": effective_model,
                "use_omniroute": bool(getattr(values, "use_omniroute", False)),
                "auto_repair": values.auto_repair,
                "edits": edits_payload,
                "repair_waves": waves_payload,
                "selector_mode": getattr(values, "selector_mode", "deterministic"),
                "config_snapshot": config_snapshot,
                "autonomy_profile": values.autonomy_profile,
                "task_type": values.task_type,
            },
        )
        return {
            "job_id": job["id"],
            "status": job["status"],
            "created_at": job.get("created_at"),
            "poll": f"/build/jobs/{job['id']}",
            "model_id": effective_model,
        }

    @router.post("/conversations/{conversation_id}/coding-jobs", status_code=status.HTTP_202_ACCEPTED)
    async def conversation_start_coding_job(conversation_id: str, values: CodingJobStartInput = Body()) -> dict[str, Any]:
        """Thin Chat-scoped coding start — delegates to CodingJobStore / CodingAgentService."""
        database = getattr(s, "database", None) or s.get("database")
        platform = getattr(s, "platform_db", None) or s.get("platform_db")
        if database is None or not database.get_conversation(conversation_id):
            raise HTTPException(status_code=404, detail="Gesprek niet gevonden.")
        enforce_subprocess_policy(values.approved_subprocess, "chat coding-job starten")
        started = await build_from_goal_async(values)
        job_id = str(started.get("job_id") or "")
        if job_id and platform is not None:
            try:
                from conversation_runs import bind_conversation_run

                link = bind_conversation_run(
                    platform,
                    conversation_id=conversation_id,
                    run_id=job_id,
                    run_type="coding",
                    status=str(started.get("status") or "queued"),
                    title=(values.goal or "")[:200],
                    metadata={
                        "source_repo": values.source_repo,
                        "poll": started.get("poll"),
                        "strategy": values.strategy,
                    },
                )
                started = {**started, "conversation_id": conversation_id, "conversation_run": link}
            except Exception:
                started = {**started, "conversation_id": conversation_id}
        return started

    @router.get("/build/jobs")
    async def build_jobs_list(limit: int = Query(default=40, ge=1, le=200), include_terminal: bool = True) -> dict[str, Any]:
        from api_contracts import CodingJobsListResponse, PageMeta

        store = _coding_job_store()
        jobs = await asyncio.to_thread(store.list_jobs, limit=limit, include_terminal=include_terminal)
        payload = CodingJobsListResponse(
            jobs=jobs,
            page=PageMeta(limit=limit, offset=0, returned=len(jobs), truncated=len(jobs) >= limit),
        )
        return payload.model_dump()

    @router.get("/build/jobs/control-contract")
    async def build_jobs_control_contract() -> dict[str, Any]:
        return await asyncio.to_thread(_coding_job_store().control_contract)

    @router.get("/build/omniroute/status")
    async def build_omniroute_status() -> dict[str, Any]:
        """Plugin-registry OmniRoute readiness for the Coding toggle. Never infers from disk."""
        from coding_omniroute import availability_from_plugin_manager, omniroute_enabled_by_default

        availability = await asyncio.to_thread(availability_from_plugin_manager, s.get("plugin_manager"))
        return {
            **availability,
            "enabled_by_default": omniroute_enabled_by_default(),
            "toggle_enabled": bool(availability.get("usable")),
            "explanation": "Route coding model calls through available OmniRoute models.",
        }

    @router.get("/build/jobs/{job_id}")
    async def build_job_get(job_id: str) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(_coding_job_store().get, job_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/build/jobs/{job_id}/events")
    async def build_job_events(
        job_id: str,
        limit: int = Query(default=100, ge=1, le=500),
        after_seq: int | None = Query(default=None, ge=0),
    ) -> dict[str, Any]:
        store = _coding_job_store()

        def _load() -> dict[str, Any]:
            store.get(job_id)
            events = store.list_events(job_id, limit=limit, after_seq=after_seq)
            next_cursor = events[-1]["seq"] if events else after_seq
            return {"job_id": job_id, "events": events, "after_seq": after_seq, "next_cursor": next_cursor}

        try:
            return await asyncio.to_thread(_load)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/build/jobs/{job_id}/cancel")
    async def build_job_cancel(job_id: str) -> dict[str, Any]:
        """Fence cancel + cancel active Coding model Tasks, then cooperative job cancel."""
        from coding_model_runtime import cancel_coding_run
        from lm_studio import remember_cancelled_run

        # 1) Fence first so no NEW model call may start.
        remember_cancelled_run(job_id)
        model_cancel = await asyncio.to_thread(cancel_coding_run, job_id, wait_s=5.0)
        # 2) Record durable job cancellation (honest cancel_requested → cancelled).
        try:
            result = await asyncio.to_thread(_coding_job_store().request_cancel, job_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        result = dict(result or {})
        result["model_cancel"] = model_cancel
        return result

    @router.post("/build/jobs/{job_id}/pause")
    async def build_job_pause(job_id: str) -> dict[str, Any]:
        try:
            return _coding_job_store().request_pause(job_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/build/jobs/{job_id}/resume")
    async def build_job_resume(job_id: str) -> dict[str, Any]:
        try:
            return _coding_job_store().resume(job_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/build/jobs/{job_id}/redirect")
    async def build_job_redirect(job_id: str, values: CodingJobRedirectInput = Body()) -> dict[str, Any]:
        try:
            return _coding_job_store().redirect(job_id, values.note)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/build/jobs/recover")
    async def build_jobs_recover(auto_resume: bool = False) -> dict[str, Any]:
        return _coding_job_store().recover_stale(auto_resume=auto_resume)

    @router.get("/build/{run_id}")
    async def build_get(run_id: str) -> dict[str, Any]:
        try:
            return s.build_service.get_run(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/build/{run_id}/conflicts")
    async def build_conflicts(run_id: str) -> dict[str, Any]:
        try:
            return {"conflicts": s.build_service.check_apply_conflicts(run_id)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/build/{run_id}/preview")
    async def build_preview(run_id: str) -> dict[str, Any]:
        try:
            return s.build_service.preview_apply(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/build/{run_id}/apply")
    async def build_apply(run_id: str, values: BuildApplyInput = Body()) -> dict[str, Any]:
        try:
            return s.build_service.apply_to_source(run_id, approved=values.approved)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/build/{run_id}/restore")
    async def build_restore(run_id: str) -> dict[str, Any]:
        try:
            return s.build_service.restore_backup(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


