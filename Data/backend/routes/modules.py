"""Module manager HTTP routes — lifecycle owner surface for modules/plugins."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from Data.modules.function_runtime.types import SideEffect
from Data.modules.module_manager import ModuleManagerError, ModuleStatus
from Data.modules.module_manager.errors import (
    http_status_for_lifecycle_error,
    scrub_error_text,
    unknown_module_error,
)

logger = logging.getLogger("leviathan.modules")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ModuleExecuteRequest(BaseModel):
    operation: str = Field(min_length=1, max_length=120)
    arguments: dict = Field(default_factory=dict)


class ModuleInstallRequest(BaseModel):
    force: bool = False
    ref: str | None = None
    activate: bool = True
    approval_id: str | None = None
    plan_hash: str | None = None
    auto_resolve_dependencies: bool = True


class ModuleInstallVersionRequest(BaseModel):
    ref: str | None = None
    activate: bool = False
    force: bool = False
    approval_id: str | None = None
    plan_hash: str | None = None
    auto_resolve_dependencies: bool = True


class ModuleInstallPlanRequest(BaseModel):
    ref: str | None = None
    force: bool = False


class ModuleActivateVersionRequest(BaseModel):
    version_id: str = Field(min_length=1, max_length=240)


class ModuleRollbackVersionRequest(BaseModel):
    version_id: str | None = None


def build_modules_router(
    *,
    module_manager: Any,
    observability: Any,
    job_runtime: Any = None,
    approval_service: Any = None,
    allow_sync_install_fallback: bool = False,
) -> APIRouter:
    router = APIRouter(tags=["modules"])

    def _require_enabled() -> None:
        if not module_manager.enabled:
            raise HTTPException(status_code=503, detail="Module manager feature flag OFF")

    def _emit(name: str, payload: dict[str, Any], *, level: str = "info") -> None:
        try:
            observability.emit("module_manager", name, payload=_safe_payload(payload), level=level)
        except Exception:  # noqa: BLE001 — observability must not hide the lifecycle result
            logger.warning("module observability emit failed name=%s", name)

    def _raise_lifecycle(exc: ModuleManagerError) -> None:
        status = http_status_for_lifecycle_error(exc)
        level = "warning" if status < 500 else "error"
        logger.warning(
            "module.lifecycle.failed module_id=%s action=%s error_code=%s error_class=%s error=%s",
            exc.module_id,
            exc.action,
            exc.code,
            type(exc).__name__,
            scrub_error_text(exc.detail, limit=300),
        )
        _emit(
            f"module.{exc.action or 'lifecycle'}.failed",
            {
                "module_id": exc.module_id,
                "action": exc.action,
                "error_code": exc.code,
                "error_class": type(exc).__name__,
                "error": exc.detail,
            },
            level=level,
        )
        raise HTTPException(status_code=status, detail=exc.public_dict()) from exc

    def _unknown(module_id: str, action: str) -> None:
        _raise_lifecycle(unknown_module_error(module_id, action=action))

    def _require_known(module_id: str, action: str) -> None:
        if module_manager.get(module_id) is None:
            _unknown(module_id, action)

    @router.get("/api/modules")
    def list_managed_modules() -> dict:
        if not module_manager.enabled:
            return {
                "enabled": False,
                "modules": [],
                "truth": {"module_manager_feature_flag_off": True},
            }
        # Hydrate persisted update evidence before projecting the snapshot.
        if hasattr(module_manager, "list"):
            for managed in module_manager.list():
                mid = getattr(getattr(managed, "manifest", None), "module_id", None)
                if mid and hasattr(module_manager, "hydrate_update_evidence"):
                    try:
                        module_manager.hydrate_update_evidence(mid)
                    except Exception:  # noqa: BLE001
                        pass
        return module_manager.public_snapshot()

    @router.post("/api/modules/discover")
    def discover_modules() -> dict:
        _require_enabled()
        manifests = module_manager.discover()
        observability.emit("module_manager", "discover", payload={"count": len(manifests)})
        return {
            "discovered": [item.public_dict() for item in manifests],
            "snapshot": module_manager.public_snapshot(),
        }

    @router.get("/api/modules/{module_id}")
    def get_module(module_id: str) -> dict:
        _require_enabled()
        managed = module_manager.get(module_id)
        if managed is None:
            _unknown(module_id, "get")
        return {"module": managed.public_dict()}

    @router.post("/api/modules/{module_id}/install-plan")
    def module_install_plan(module_id: str, payload: ModuleInstallPlanRequest | None = None) -> dict:
        _require_enabled()
        payload = payload or ModuleInstallPlanRequest()
        _require_known(module_id, "install_plan")
        try:
            plan = module_manager.plan_install(module_id, ref=payload.ref, force=payload.force)
        except ModuleManagerError as exc:
            _raise_lifecycle(exc)
        return {
            "module_id": module_id,
            "plan": plan,
            "truth": {"install_plan_is_read_only": True},
        }

    @router.get("/api/modules/{module_id}/install-state")
    def module_install_state(module_id: str) -> dict:
        _require_enabled()
        _require_known(module_id, "install_state")
        store = _external_store(module_manager, module_id)
        operation = None
        if store is not None and hasattr(store, "list_install_operations"):
            ops = store.list_install_operations(module_id)
            operation = ops[0] if ops else None
        return {
            "module_id": module_id,
            "operation": operation,
            "truth": {"latest_operation_only": True},
        }

    @router.post("/api/modules/{module_id}/install")
    def install_module(module_id: str, payload: ModuleInstallRequest | None = None) -> Any:
        _require_enabled()
        payload = payload or ModuleInstallRequest()
        _require_known(module_id, "install")
        return _run_install_http(
            module_manager=module_manager,
            job_runtime=job_runtime,
            approval_service=approval_service,
            allow_sync_install_fallback=allow_sync_install_fallback,
            module_id=module_id,
            action="install",
            ref=payload.ref,
            force=payload.force,
            activate=payload.activate,
            approval_id=payload.approval_id,
            plan_hash=payload.plan_hash,
            auto_resolve_dependencies=payload.auto_resolve_dependencies,
            requested_by="api.modules.install",
            idempotency_key=f"ext-install:{module_id}:{payload.ref or 'active'}",
            emit=_emit,
            raise_lifecycle=_raise_lifecycle,
        )

    @router.post("/api/modules/{module_id}/start")
    def start_module(module_id: str) -> dict:
        _require_enabled()
        return _queue_module_lifecycle(
            job_runtime=job_runtime,
            module_id=module_id,
            capability_id="external.module.start",
            action="start",
            emit=_emit,
            raise_lifecycle=_raise_lifecycle,
            module_manager=module_manager,
            allow_sync_fallback=allow_sync_install_fallback,
        )

    @router.post("/api/modules/{module_id}/stop")
    def stop_module(module_id: str) -> dict:
        _require_enabled()
        return _queue_module_lifecycle(
            job_runtime=job_runtime,
            module_id=module_id,
            capability_id="external.module.stop",
            action="stop",
            emit=_emit,
            raise_lifecycle=_raise_lifecycle,
            module_manager=module_manager,
            allow_sync_fallback=allow_sync_install_fallback,
        )

    @router.post("/api/modules/{module_id}/restart")
    def restart_module(module_id: str) -> dict:
        _require_enabled()
        return _queue_module_lifecycle(
            job_runtime=job_runtime,
            module_id=module_id,
            capability_id="external.module.restart",
            action="restart",
            emit=_emit,
            raise_lifecycle=_raise_lifecycle,
            module_manager=module_manager,
            allow_sync_fallback=allow_sync_install_fallback,
        )

    @router.post("/api/modules/{module_id}/ensure-ready")
    def ensure_ready_module(module_id: str) -> dict:
        _require_enabled()
        return _queue_module_lifecycle(
            job_runtime=job_runtime,
            module_id=module_id,
            capability_id="external.module.ensure_ready",
            action="ensure_ready",
            emit=_emit,
            raise_lifecycle=_raise_lifecycle,
            module_manager=module_manager,
            allow_sync_fallback=allow_sync_install_fallback,
        )

    @router.get("/api/modules/{module_id}/health")
    def module_health(module_id: str) -> dict:
        _require_enabled()
        try:
            health = module_manager.health(module_id)
        except ModuleManagerError as exc:
            _raise_lifecycle(exc)
        return {"health": health.public_dict()}

    @router.get("/api/modules/{module_id}/logs")
    def module_logs(module_id: str, limit: int = Query(default=200, ge=1, le=500)) -> dict:
        _require_enabled()
        try:
            lines = module_manager.logs(module_id, limit=limit)
        except ModuleManagerError as exc:
            _raise_lifecycle(exc)
        return {"module_id": module_id, "lines": lines, "count": len(lines)}

    @router.get("/api/modules/{module_id}/capabilities")
    def module_capabilities(module_id: str) -> dict:
        _require_enabled()
        managed = module_manager.get(module_id)
        if managed is None:
            _unknown(module_id, "capabilities")
        caps = [c.public_dict() for c in managed.manifest.capabilities]
        return {
            "module_id": module_id,
            "capabilities": caps,
            "count": len(caps),
            "truth": {"discoverable_is_not_authorized": True},
        }

    @router.get("/api/modules/{module_id}/jobs")
    def module_jobs(module_id: str, limit: int = Query(default=50, ge=1, le=200)) -> dict:
        _require_enabled()
        try:
            active_ids = module_manager.active_jobs(module_id)
        except ModuleManagerError as exc:
            _raise_lifecycle(exc)
        jobs = _project_module_jobs(
            job_runtime=job_runtime,
            module_id=module_id,
            active_ids=active_ids,
            limit=limit,
        )
        return {
            "module_id": module_id,
            "jobs": jobs,
            "active_job_ids": list(active_ids),
            "count": len(jobs),
            "truth": {
                "job_runtime_owns_durable_job_state": True,
                "module_manager_projects_active_job_ids": True,
            },
        }

    @router.get("/api/modules/{module_id}/activity")
    def module_activity(module_id: str, limit: int = Query(default=20, ge=1, le=50)) -> dict:
        """Bounded recent activity from Observability (no second event bus)."""
        _require_enabled()
        _require_known(module_id, "activity")
        events = _project_module_activity(
            observability=observability,
            module_id=module_id,
            limit=limit,
        )
        return {
            "module_id": module_id,
            "events": events,
            "count": len(events),
            "truth": {
                "observability_is_activity_source": True,
                "enqueue_is_not_completion": True,
            },
        }

    @router.post("/api/modules/check-updates")
    def check_all_module_updates(
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict:
        """Bounded update checks across eligible modules (local evidence; no remote fanout)."""
        _require_enabled()
        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        modules = list(module_manager.list())[:limit]
        for managed in modules:
            mid = managed.manifest.module_id
            if not managed._has_lifecycle_adapter():
                continue
            try:
                result = module_manager.check_update(mid)
                results.append(result if isinstance(result, dict) else {"module_id": mid, "result": result})
            except ModuleManagerError as exc:
                errors.append(
                    {
                        "module_id": mid,
                        "error_code": exc.code,
                        "detail": scrub_error_text(exc.detail, limit=200),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    {
                        "module_id": mid,
                        "error_code": "CHECK_UPDATE_FAILED",
                        "detail": scrub_error_text(str(exc), limit=200),
                    }
                )
        _emit(
            "check_updates_batch",
            {"checked": len(results), "errors": len(errors)},
        )
        return {
            "results": results,
            "errors": errors,
            "checked": len(results),
            "error_count": len(errors),
            "snapshot": module_manager.public_snapshot(),
            "truth": {
                "check_update_is_local_evidence": True,
                "no_remote_fanout_in_fastapi": True,
            },
        }

    @router.get("/api/modules/{module_id}/versions")
    def module_versions(module_id: str) -> dict:
        _require_enabled()
        try:
            versions = module_manager.list_versions(module_id)
        except ModuleManagerError as exc:
            _raise_lifecycle(exc)
        return {"module_id": module_id, "versions": versions, "count": len(versions)}

    @router.get("/api/modules/{module_id}/check-update")
    def module_check_update(module_id: str) -> dict:
        _require_enabled()
        try:
            result = module_manager.check_update(module_id)
        except ModuleManagerError as exc:
            _raise_lifecycle(exc)
        return {"result": result}

    @router.post("/api/modules/{module_id}/install-version")
    def module_install_version(module_id: str, payload: ModuleInstallVersionRequest | None = None) -> Any:
        _require_enabled()
        payload = payload or ModuleInstallVersionRequest()
        _require_known(module_id, "install_version")
        # Activation changes the live runtime and stays on the sync path when
        # active-job conflict must be reported immediately — still fail closed
        # for worker enqueue when not falling back.
        return _run_install_http(
            module_manager=module_manager,
            job_runtime=job_runtime,
            approval_service=approval_service,
            allow_sync_install_fallback=allow_sync_install_fallback,
            module_id=module_id,
            action="install_version",
            ref=payload.ref,
            force=payload.force,
            activate=payload.activate,
            approval_id=payload.approval_id,
            plan_hash=payload.plan_hash,
            auto_resolve_dependencies=payload.auto_resolve_dependencies,
            requested_by="api.modules.install_version",
            idempotency_key=f"ext-install-ver:{module_id}:{payload.ref or 'active'}",
            emit=_emit,
            raise_lifecycle=_raise_lifecycle,
            prefer_install_version=True,
        )

    @router.post("/api/modules/{module_id}/activate-version")
    def module_activate_version(module_id: str, payload: ModuleActivateVersionRequest) -> dict:
        _require_enabled()
        _require_known(module_id, "activate_version")
        return _queue_module_lifecycle(
            job_runtime=job_runtime,
            module_id=module_id,
            capability_id="external.module.activate_version",
            action="activate_version",
            emit=_emit,
            raise_lifecycle=_raise_lifecycle,
            module_manager=module_manager,
            allow_sync_fallback=allow_sync_install_fallback,
            arguments={"module_id": module_id, "version_id": payload.version_id, "action": "activate_version"},
        )

    @router.post("/api/modules/{module_id}/rollback-version")
    def module_rollback_version(module_id: str, payload: ModuleRollbackVersionRequest | None = None) -> dict:
        _require_enabled()
        payload = payload or ModuleRollbackVersionRequest()
        _require_known(module_id, "rollback_version")
        return _queue_module_lifecycle(
            job_runtime=job_runtime,
            module_id=module_id,
            capability_id="external.module.rollback_version",
            action="rollback_version",
            emit=_emit,
            raise_lifecycle=_raise_lifecycle,
            module_manager=module_manager,
            allow_sync_fallback=allow_sync_install_fallback,
            arguments={
                "module_id": module_id,
                "version_id": payload.version_id,
                "action": "rollback_version",
            },
        )

    @router.post("/api/modules/sweep-idle")
    def sweep_idle_modules() -> dict:
        _require_enabled()
        stopped = []
        if hasattr(module_manager, "sweep_idle_modules"):
            stopped = module_manager.sweep_idle_modules()
        observability.emit("module_manager", "sweep_idle", payload={"stopped": len(stopped)})
        return {"stopped": stopped, "count": len(stopped)}

    @router.post("/api/modules/{module_id}/execute")
    def execute_managed_module(module_id: str, payload: ModuleExecuteRequest) -> dict:
        _require_enabled()
        from Data.modules.module_manager.external.install_gate import allow_sync_install_for_tests

        arguments = {
            "module_id": module_id,
            "operation": payload.operation,
            "arguments": dict(payload.arguments or {}),
        }
        if job_runtime is not None and hasattr(job_runtime, "enqueue"):
            try:
                job = job_runtime.enqueue(
                    capability_id="external.module.invoke",
                    arguments=arguments,
                    requested_by="api.modules.execute",
                    idempotency_key=None,
                    worker_pool="module_runtime",
                    latency_class="interactive",
                    domain="external_capability",
                    consumer="api.modules",
                    metadata={"worker_kind": "module_runtime", "execution_class": "EXTERNAL_REQUIRED"},
                )
                observability.emit(
                    "module_manager",
                    "execute_queued",
                    payload={"module_id": module_id, "operation": payload.operation, "job_id": getattr(job, "job_id", None)},
                )
                return {
                    "queued": True,
                    "job_id": getattr(job, "job_id", None),
                    "capability_id": "external.module.invoke",
                    "worker_pool": "module_runtime",
                    "operation": "execute",
                    "module_id": module_id,
                    "accepted_at": _utc_now(),
                    "state": _job_state(job) or "QUEUED",
                    "truth": {
                        "fastapi_does_not_spawn_module_subprocess": True,
                        "enqueue_is_not_completion": True,
                    },
                }
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(
                    status_code=503,
                    detail={
                        "code": "MODULE_RUNTIME_UNAVAILABLE",
                        "message": scrub_error_text(str(exc), limit=300),
                        "module_id": module_id,
                    },
                ) from exc
        if not (allow_sync_install_fallback and allow_sync_install_for_tests()):
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "MODULE_RUNTIME_UNAVAILABLE",
                    "message": "JobRuntime unavailable for module invoke",
                    "module_id": module_id,
                },
            )
        try:
            result = module_manager.execute(module_id, payload.operation, payload.arguments)
        except ModuleManagerError as exc:
            _raise_lifecycle(exc)
        observability.emit(
            "module_manager",
            "execute",
            payload={"module_id": module_id, "operation": payload.operation, "status": result.status},
        )
        return {"result": result.public_dict(), "queued": False, "inprocess_test": True}

    return router


_ACTIVE_JOB_STATES = {"QUEUED", "RUNNING", "CREATED", "RETRY_WAIT", "CANCEL_REQUESTED"}
_HARD_BLOCKER_CODES = {
    "DEPENDENCY_UNSUPPORTED",
    "PACKAGE_MANAGER_UNAVAILABLE",
    "PRIVILEGE_REQUIRED",
    "DEPENDENCY_MISSING",
    "NETWORK_POLICY_BLOCKED",
    "SOURCE_UNAVAILABLE",
}

_MODULE_CAPABILITY_PREFIXES = (
    "external.module.",
)


def _project_module_jobs(
    *,
    job_runtime: Any,
    module_id: str,
    active_ids: list[str],
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Merge ModuleManager active job ids with JobRuntime durable history for a module."""
    by_id: dict[str, dict[str, Any]] = {}
    if job_runtime is not None and hasattr(job_runtime, "list"):
        try:
            for job in job_runtime.list(limit=max(limit * 4, 100)):
                payload = job.public_dict() if hasattr(job, "public_dict") else dict(job)
                args = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
                meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
                cap = str(payload.get("capability_id") or "")
                matches = str(args.get("module_id") or "") == module_id or str(
                    meta.get("module_id") or ""
                ) == module_id
                if not matches and any(cap.startswith(p) for p in _MODULE_CAPABILITY_PREFIXES):
                    # Some historical jobs may only carry module_id nested under arguments.
                    matches = any(
                        isinstance(v, str) and v == module_id for v in args.values()
                    )
                if not matches:
                    continue
                jid = str(payload.get("job_id") or "")
                if not jid:
                    continue
                by_id[jid] = {
                    **payload,
                    "source": "job_runtime",
                    "active": str(payload.get("state") or "").upper() in _ACTIVE_JOB_STATES,
                }
        except Exception:  # noqa: BLE001
            logger.debug("module jobs JobRuntime projection failed", exc_info=True)
    for jid in active_ids:
        if jid in by_id:
            by_id[jid]["active"] = True
            continue
        resolved = None
        if job_runtime is not None and hasattr(job_runtime, "get"):
            try:
                job = job_runtime.get(jid)
                if job is not None:
                    resolved = job.public_dict() if hasattr(job, "public_dict") else dict(job)
            except Exception:  # noqa: BLE001
                resolved = None
        by_id[jid] = {
            **(resolved or {"job_id": jid, "state": "UNKNOWN"}),
            "source": "job_runtime" if resolved else "module_manager_active",
            "active": True,
            "module_id": module_id,
        }
    # Active first, then newest by created/updated timestamps when present.
    def _sort_key(item: dict[str, Any]) -> tuple:
        active = 0 if item.get("active") else 1
        ts = str(item.get("updated_at") or item.get("created_at") or item.get("queued_at") or "")
        return (active, ts)

    ordered = sorted(by_id.values(), key=_sort_key)
    return ordered[:limit]


_ACTIVITY_LABELS = {
    "start_queued": "Start requested",
    "start": "Module started",
    "stop_queued": "Stop requested",
    "stop": "Module stopped",
    "restart_queued": "Restart requested",
    "restart": "Module restarted",
    "ensure_ready_queued": "Ensure Ready requested",
    "ensure_ready": "Ensure Ready completed",
    "execute_queued": "Execute requested",
    "execute": "Operation executed",
    "activate_version_queued": "Activate version requested",
    "activate_version": "Version activated",
    "rollback_version_queued": "Rollback requested",
    "rollback_version": "Rollback completed",
    "discover": "Discover completed",
    "check_updates_batch": "Update check completed",
}


def _activity_label(name: str) -> str:
    if name in _ACTIVITY_LABELS:
        return _ACTIVITY_LABELS[name]
    if name.endswith("_queued"):
        base = name[: -len("_queued")].replace("_", " ").strip()
        return f"{base.capitalize()} requested" if base else "Requested"
    if name.startswith("module.") and name.endswith(".failed"):
        return "Lifecycle failed"
    pretty = name.replace("_", " ").replace(".", " ").strip()
    return pretty[:1].upper() + pretty[1:] if pretty else name


def _project_module_activity(
    *,
    observability: Any,
    module_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    if observability is not None and hasattr(observability, "query_history"):
        try:
            raw = list(
                observability.query_history(
                    limit=max(limit * 3, 60),
                    category="module_manager",
                    module_id=module_id,
                    newest_first=True,
                )
                or []
            )
        except TypeError:
            # Older query_history without module_id kwarg — filter client-side.
            try:
                raw = list(
                    observability.query_history(
                        limit=max(limit * 5, 100),
                        category="module_manager",
                        newest_first=True,
                    )
                    or []
                )
            except Exception:  # noqa: BLE001
                raw = []
        except Exception:  # noqa: BLE001
            raw = []
    out: list[dict[str, Any]] = []
    for event in raw:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        eid_module = event.get("module_id") or payload.get("module_id")
        if eid_module and str(eid_module) != module_id:
            continue
        name = str(event.get("name") or "")
        status = "OK"
        if "failed" in name.lower() or event.get("success") is False:
            status = "FAILED"
        elif name.endswith("_queued") or "requested" in name.lower():
            status = "QUEUED"
        out.append(
            {
                "event_id": event.get("event_id"),
                "name": name,
                "label": _activity_label(name),
                "status": status,
                "created_at_ms": event.get("created_at_ms"),
                "level": event.get("level"),
                "message": event.get("message"),
                "job_id": event.get("job_id") or payload.get("job_id"),
                "payload": payload,
            }
        )
        if len(out) >= limit:
            break
    return out


def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, str):
            safe[key] = scrub_error_text(value, limit=240)
        elif isinstance(value, (int, float, bool)):
            safe[key] = value
        else:
            safe[key] = scrub_error_text(str(value), limit=240)
    return safe


def _job_state(job: Any) -> str:
    state = getattr(job, "state", None)
    return str(getattr(state, "value", state) or "")


def _capability_requires_approval(definition: Any) -> bool:
    effects = getattr(definition, "side_effects", ()) or ()
    for effect in effects:
        name = str(getattr(effect, "value", effect) or "").upper()
        if name and name != "READ":
            return True
    return False


def _external_store(module_manager: Any, module_id: str) -> Any | None:
    managed = module_manager.get(module_id) if module_manager is not None else None
    if managed is None:
        return None
    inst = getattr(managed, "instance", None)
    store = getattr(inst, "_store", None) if inst is not None else None
    return store


def _approval_public(record: Any) -> dict[str, Any]:
    if record is None:
        return {}
    if hasattr(record, "public_dict"):
        return dict(record.public_dict())
    return {
        "approval_id": getattr(record, "approval_id", None),
        "status": str(getattr(getattr(record, "status", None), "value", getattr(record, "status", None)) or ""),
        "capability_id": getattr(record, "capability_id", None),
        "reason": getattr(record, "reason", None),
    }


def _approval_binding_args(
    *,
    module_id: str,
    ref: str | None,
    plan: dict[str, Any],
) -> dict[str, Any]:
    return {
        "module_id": module_id,
        "ref": ref,
        "plan_hash": plan.get("plan_hash"),
        "dependency_mutations": list(plan.get("privileged_mutations") or []),
    }


def _raise_plan_blocker(module_id: str, action: str, plan: dict[str, Any]) -> None:
    blockers = list(plan.get("blockers") or [])
    hard = [b for b in blockers if str(b.get("code") or "") in _HARD_BLOCKER_CODES]
    if not hard and plan.get("installable", True):
        return
    if not hard:
        hard = blockers or [{"code": "INSTALL_FAILED", "detail": "plan not installable"}]
    code = str(hard[0].get("code") or "INSTALL_FAILED")
    # Align unknown/unsupported host packages with the installer's DEPENDENCY_MISSING contract
    # when the planner marks them MISSING_UNSUPPORTED for non-registry ids.
    if code == "DEPENDENCY_UNSUPPORTED":
        dep = hard[0].get("dependency_id")
        if dep:
            # Prefer DEPENDENCY_MISSING for unknown binary names (matches InstallationService).
            from Data.modules.module_manager.external.dependencies import LOGICAL_DEPENDENCY_REGISTRY

            if str(dep) not in LOGICAL_DEPENDENCY_REGISTRY:
                code = "DEPENDENCY_MISSING"
                detail = f"missing dependencies: {dep}"
                raise ModuleManagerError(
                    f"{code}: {detail}",
                    code=code,
                    module_id=module_id,
                    action=action,
                    detail=detail,
                )
    detail = str(hard[0].get("detail") or code)
    if code == "DEPENDENCY_MISSING" and hard[0].get("dependency_id"):
        detail = f"missing dependencies: {hard[0].get('dependency_id')}"
    raise ModuleManagerError(
        f"{code}: {detail}",
        code=code if code else "INSTALL_FAILED",
        module_id=module_id,
        action=action,
        detail=detail,
    )


def _persist_operation(
    store: Any,
    *,
    module_id: str,
    plan: dict[str, Any],
    operation_id: str,
    ref: str | None,
    approval_id: str | None = None,
    status: str = "PENDING",
    phase: str = "PLANNING",
    idempotency_key: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any] | None:
    if store is None or not hasattr(store, "create_install_operation"):
        return None
    return store.create_install_operation(
        module_id=module_id,
        plan_hash=str(plan.get("plan_hash") or ""),
        plan=plan,
        status=status,
        phase=phase,
        operation_id=operation_id,
        requested_ref=ref or plan.get("requested_ref"),
        package_manager=plan.get("package_manager"),
        approval_id=approval_id,
        job_id=job_id,
        idempotency_key=idempotency_key,
        progress=0.05,
    )


def _authorize_operator_install(
    approval_service: Any,
    capability_id: str,
    arguments: dict[str, Any],
    *,
    privileged: bool = False,
) -> str | None:
    """Record the modules API click as a single-use approval for the job path.

    Privileged host-package plans must NOT be auto-approved here — they return
    PENDING via the install route. Module-only installs may auto-approve the
    operator API click for JobRuntime gateway gating.
    """
    if privileged:
        return None
    if approval_service is None or not hasattr(approval_service, "request"):
        return None
    record = approval_service.request(
        capability_id=capability_id,
        side_effects=("READ", "EXECUTE", "WRITE", "NETWORK"),
        requested_by="api.modules",
        reason=f"operator lifecycle {capability_id}",
        single_use=True,
        arguments=arguments,
        metadata={"module_lifecycle": True, "module_id": arguments.get("module_id")},
    )
    approval_id = getattr(record, "approval_id", None)
    if not approval_id:
        return None
    if hasattr(approval_service, "approve"):
        approved = approval_service.approve(
            approval_id,
            decided_by="operator.modules_api",
            reason="explicit modules API lifecycle request",
        )
        return str(getattr(approved, "approval_id", approval_id))
    return str(approval_id)


def _observe_enqueue_failure(
    *,
    emit: Any,
    module_id: str,
    action: str,
    exc: BaseException,
) -> None:
    message = scrub_error_text(str(exc), limit=300)
    logger.warning(
        "module.install.enqueue_failed module_id=%s action=%s error_class=%s error=%s",
        module_id,
        action,
        type(exc).__name__,
        message,
    )
    emit(
        "module.install.enqueue_failed",
        {
            "module_id": module_id,
            "action": action,
            "error_class": type(exc).__name__,
            "error": message,
        },
        level="warning",
    )


def _http_install_unavailable(code: str, message: str, *, module_id: str, action: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": code,
            "message": scrub_error_text(message, limit=300),
            "module_id": module_id,
            "action": action,
        },
    )


def _queue_module_lifecycle(
    *,
    job_runtime: Any,
    module_id: str,
    capability_id: str,
    action: str,
    emit: Any,
    raise_lifecycle: Any,
    module_manager: Any,
    allow_sync_fallback: bool = False,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Queue process lifecycle (start/stop/restart/ensure_ready/version) onto module_runtime."""
    from Data.modules.module_manager.external.install_gate import allow_sync_install_for_tests

    args = dict(arguments or {"module_id": module_id, "action": action})
    accepted_at = _utc_now()
    if job_runtime is not None and hasattr(job_runtime, "enqueue"):
        try:
            job = job_runtime.enqueue(
                capability_id=capability_id,
                arguments=args,
                requested_by=f"api.modules.{action}",
                worker_pool="module_runtime",
                latency_class="interactive",
                domain="external_capability",
                consumer="api.modules",
                metadata={"worker_kind": "module_runtime", "execution_class": "EXTERNAL_REQUIRED"},
            )
            state = _job_state(job) or "QUEUED"
            job_id = getattr(job, "job_id", None)
            if job_id and hasattr(module_manager, "register_job"):
                try:
                    module_manager.register_job(module_id, str(job_id))
                except Exception:  # noqa: BLE001
                    pass
            # Project transitional desired/runtime hints without claiming completion.
            managed = module_manager.get(module_id) if hasattr(module_manager, "get") else None
            if managed is not None and action in {"start", "restart", "ensure_ready"}:
                managed.desired_state = "ACTIVE" if action != "ensure_ready" else (managed.desired_state or "ACTIVE")
            if managed is not None and action == "stop":
                managed.desired_state = "STOPPED"
            emit(
                f"{action}_queued",
                {"module_id": module_id, "job_id": job_id, "state": state},
            )
            return {
                "queued": True,
                "job_id": job_id,
                "capability_id": capability_id,
                "worker_pool": "module_runtime",
                "operation": action,
                "module_id": module_id,
                "accepted_at": accepted_at,
                "state": state,
                "module": (
                    module_manager.get(module_id).public_dict()
                    if module_manager.get(module_id) is not None
                    else None
                ),
                "truth": {
                    "fastapi_does_not_spawn_module_subprocess": True,
                    "enqueue_is_not_completion": True,
                },
            }
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "MODULE_RUNTIME_UNAVAILABLE",
                    "message": scrub_error_text(str(exc), limit=300),
                    "module_id": module_id,
                    "action": action,
                },
            ) from exc
    if not (allow_sync_fallback and allow_sync_install_for_tests()):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "MODULE_RUNTIME_UNAVAILABLE",
                "message": f"JobRuntime unavailable for module {action}",
                "module_id": module_id,
                "action": action,
            },
        )
    try:
        if action == "activate_version":
            result = module_manager.activate_version(module_id, str(args.get("version_id") or ""))
        elif action == "rollback_version":
            result = module_manager.rollback_version(
                module_id, version_id=args.get("version_id")
            )
        else:
            result = getattr(module_manager, action)(module_id)
    except ModuleManagerError as exc:
        raise_lifecycle(exc)
    emit(action, {"module_id": module_id, "inprocess_test": True})
    managed = module_manager.get(module_id)
    return {
        "queued": False,
        "inprocess_test": True,
        "operation": action,
        "module_id": module_id,
        "accepted_at": accepted_at,
        "state": "SUCCEEDED",
        "result": result,
        "module": managed.public_dict() if managed is not None else None,
    }


def _queue_install(
    *,
    job_runtime: Any,
    approval_service: Any,
    module_id: str,
    action: str,
    arguments: dict[str, Any],
    requested_by: str,
    idempotency_key: str,
    emit: Any,
    privileged: bool = False,
    approval_id: str | None = None,
) -> dict[str, Any]:
    """Queue a lifecycle install. Raises HTTPException on worker/queue failure — never silent."""
    if job_runtime is None or not hasattr(job_runtime, "enqueue"):
        _observe_enqueue_failure(
            emit=emit,
            module_id=module_id,
            action=action,
            exc=RuntimeError("job runtime unavailable"),
        )
        raise _http_install_unavailable(
            "INSTALL_WORKER_UNAVAILABLE",
            "JobRuntime unavailable for module install",
            module_id=module_id,
            action=action,
        )
    gateway = getattr(job_runtime, "gateway", None)
    get_capability = getattr(gateway, "get_capability", None) if gateway is not None else None
    if not callable(get_capability):
        _observe_enqueue_failure(
            emit=emit,
            module_id=module_id,
            action=action,
            exc=RuntimeError("job runtime gateway unavailable"),
        )
        raise _http_install_unavailable(
            "INSTALL_WORKER_UNAVAILABLE",
            "job runtime gateway unavailable",
            module_id=module_id,
            action=action,
        )
    definition = get_capability("external.module.install")
    if definition is None:
        _observe_enqueue_failure(
            emit=emit,
            module_id=module_id,
            action=action,
            exc=KeyError("unknown capability external.module.install"),
        )
        raise _http_install_unavailable(
            "INSTALL_WORKER_UNAVAILABLE",
            "unknown capability external.module.install",
            module_id=module_id,
            action=action,
        )

    resolved_approval = approval_id
    if resolved_approval is None and _capability_requires_approval(definition):
        try:
            resolved_approval = _authorize_operator_install(
                approval_service,
                "external.module.install",
                arguments,
                privileged=privileged,
            )
        except Exception as exc:  # noqa: BLE001
            _observe_enqueue_failure(emit=emit, module_id=module_id, action=action, exc=exc)
            raise _http_install_unavailable(
                "INSTALL_QUEUE_FAILED",
                f"approval failed: {exc}",
                module_id=module_id,
                action=action,
            ) from exc
        if not resolved_approval and not privileged:
            _observe_enqueue_failure(
                emit=emit,
                module_id=module_id,
                action=action,
                exc=RuntimeError("approval required for external.module.install"),
            )
            raise _http_install_unavailable(
                "INSTALL_QUEUE_FAILED",
                "approval required for external.module.install",
                module_id=module_id,
                action=action,
            )

    def _enqueue(key: str) -> Any:
        return job_runtime.enqueue(
            capability_id="external.module.install",
            arguments=arguments,
            requested_by=requested_by,
            idempotency_key=key,
            approval_id=resolved_approval,
        )

    try:
        job = _enqueue(idempotency_key)
        if _job_state(job) not in _ACTIVE_JOB_STATES:
            # A previous terminal job must not block a new operator request.
            job = _enqueue(f"{idempotency_key}:retry")
    except Exception as exc:  # noqa: BLE001 — fail closed; no silent sync fallback
        _observe_enqueue_failure(emit=emit, module_id=module_id, action=action, exc=exc)
        raise _http_install_unavailable(
            "INSTALL_QUEUE_FAILED",
            str(exc) or "enqueue failed",
            module_id=module_id,
            action=action,
        ) from exc
    state = _job_state(job) or "QUEUED"
    if state not in _ACTIVE_JOB_STATES:
        _observe_enqueue_failure(
            emit=emit,
            module_id=module_id,
            action=action,
            exc=RuntimeError(f"enqueue returned terminal state {state}"),
        )
        raise _http_install_unavailable(
            "INSTALL_QUEUE_FAILED",
            f"enqueue returned terminal state {state}",
            module_id=module_id,
            action=action,
        )
    job_id = getattr(job, "job_id", None)
    emit(
        "module.install.queued",
        {"module_id": module_id, "action": action, "job_id": job_id, "status": state},
    )
    return {
        "job_id": job_id,
        "run_id": getattr(job, "run_id", None),
        "status": state,
        "operation_id": arguments.get("operation_id"),
        "plan_hash": arguments.get("plan_hash"),
        "approval_id": resolved_approval,
        "truth": {"production_worker_path": True},
    }


def _sync_install(
    *,
    module_manager: Any,
    module_id: str,
    action: str,
    ref: str | None,
    force: bool,
    activate: bool,
    plan_hash: str | None,
    operation_id: str | None,
    auto_resolve_dependencies: bool,
    allow_system_deps: bool,
    prefer_install_version: bool,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "ref": ref,
        "force": force,
        "activate": activate,
        "plan_hash": plan_hash,
        "operation_id": operation_id,
        "auto_resolve_dependencies": auto_resolve_dependencies,
        "allow_system_deps": allow_system_deps,
    }
    if prefer_install_version or (ref is not None and action == "install_version"):
        return module_manager.install_version(
            module_id,
            ref=ref,
            activate=activate,
            **{k: v for k, v in kwargs.items() if k not in {"ref", "activate"}},
        )
    if hasattr(module_manager, "install"):
        return module_manager.install(module_id, **kwargs)
    return module_manager.ensure_installed(module_id, **kwargs)


def _run_install_http(
    *,
    module_manager: Any,
    job_runtime: Any,
    approval_service: Any,
    allow_sync_install_fallback: bool,
    module_id: str,
    action: str,
    ref: str | None,
    force: bool,
    activate: bool,
    approval_id: str | None,
    plan_hash: str | None,
    auto_resolve_dependencies: bool,
    requested_by: str,
    idempotency_key: str,
    emit: Any,
    raise_lifecycle: Any,
    prefer_install_version: bool = False,
) -> Any:
    try:
        plan = module_manager.plan_install(module_id, ref=ref, force=force)
    except ModuleManagerError as exc:
        # Non-external / non-declarative modules have no install plan — continue
        # into the lifecycle install path (keeps defect surfaces like Boom → 500).
        if exc.code == "INVALID_RESULT":
            plan = {
                "module_id": module_id,
                "requested_ref": ref or "main",
                "requires_approval": False,
                "installable": True,
                "blockers": [],
                "privileged_mutations": [],
                "plan_hash": "",
                "package_manager": None,
                "missing_dependencies": [],
            }
        else:
            raise_lifecycle(exc)

    requires_approval = bool(plan.get("requires_approval") or plan.get("privileged_mutations"))
    blockers = list(plan.get("blockers") or [])
    hard_blockers = [
        b
        for b in blockers
        if str(b.get("code") or "") in _HARD_BLOCKER_CODES
        and str(b.get("code") or "") != "APPROVAL_REQUIRED"
    ]
    if (not plan.get("installable", True) and hard_blockers) or (
        not plan.get("installable", True) and not requires_approval
    ):
        try:
            _raise_plan_blocker(module_id, action, plan)
        except ModuleManagerError as exc:
            managed = module_manager.get(module_id)
            if managed is not None:
                managed.status = ModuleStatus.FAILED
                managed.error = scrub_error_text(f"{exc.code}: {exc.detail}")
            raise_lifecycle(exc)

    store = _external_store(module_manager, module_id)
    operation_id = str(uuid.uuid4())
    _persist_operation(
        store,
        module_id=module_id,
        plan=plan,
        operation_id=operation_id,
        ref=ref,
        approval_id=approval_id,
        status="PENDING",
        phase="APPROVAL_REQUIRED" if requires_approval and not approval_id else "PLANNING",
        idempotency_key=idempotency_key,
    )

    if requires_approval and not approval_id:
        if approval_service is None or not hasattr(approval_service, "request"):
            raise_lifecycle(
                ModuleManagerError(
                    "approval service unavailable for privileged install",
                    code="APPROVAL_SERVICE_UNAVAILABLE",
                    module_id=module_id,
                    action=action,
                    detail="approval service unavailable for privileged install",
                )
            )
        binding = _approval_binding_args(module_id=module_id, ref=ref, plan=plan)
        try:
            record = approval_service.request(
                capability_id="external.module.install",
                side_effects=("READ", "WRITE", "NETWORK", "EXECUTE"),
                requested_by=requested_by,
                reason=f"privileged dependency install for {module_id}",
                single_use=True,
                arguments=binding,
                metadata={
                    "module_lifecycle": True,
                    "module_id": module_id,
                    "plan_hash": plan.get("plan_hash"),
                    "operation_id": operation_id,
                },
            )
        except Exception as exc:  # noqa: BLE001
            raise_lifecycle(
                ModuleManagerError(
                    f"approval request failed: {exc}",
                    code="APPROVAL_SERVICE_UNAVAILABLE",
                    module_id=module_id,
                    action=action,
                    detail=f"approval request failed: {exc}",
                )
            )
        aid = getattr(record, "approval_id", None)
        if store is not None and hasattr(store, "update_install_operation") and aid:
            store.update_install_operation(
                operation_id,
                approval_id=str(aid),
                status="PENDING",
                phase="APPROVAL_REQUIRED",
            )
        emit(
            "module.install.approval_required",
            {
                "module_id": module_id,
                "action": action,
                "operation_id": operation_id,
                "approval_id": aid,
                "plan_hash": plan.get("plan_hash"),
            },
        )
        return JSONResponse(
            status_code=202,
            content={
                "status": "APPROVAL_REQUIRED",
                "operation_id": operation_id,
                "plan": plan,
                "approval": _approval_public(record),
                "truth": {
                    "privileged_host_mutations_require_operator_approval": True,
                    "not_auto_approved": True,
                },
            },
        )

    if approval_id:
        if plan_hash and plan_hash != plan.get("plan_hash"):
            raise_lifecycle(
                ModuleManagerError(
                    "provided plan_hash does not match current install plan",
                    code="PLAN_STALE_REAPPROVAL_REQUIRED",
                    module_id=module_id,
                    action=action,
                    detail="provided plan_hash does not match current install plan",
                )
            )
        binding = _approval_binding_args(module_id=module_id, ref=ref, plan=plan)
        if plan_hash:
            binding["plan_hash"] = plan_hash
        # If the client re-sends the approved plan_hash and it matches current, OK.
        # If privileged packages expanded, plan_hash differs → already caught above.
        # Extra safety: compare against stored operation plan when present.
        if store is not None and hasattr(store, "get_install_operation"):
            # Prefer matching by plan_hash among recent ops for this module.
            prior = None
            if hasattr(store, "list_install_operations"):
                for op in store.list_install_operations(module_id):
                    if op.get("plan_hash") == (plan_hash or plan.get("plan_hash")):
                        prior = op
                        break
            if prior and isinstance(prior.get("plan"), dict):
                prior_priv = {
                    str(p)
                    for m in (prior["plan"].get("privileged_mutations") or [])
                    for p in (m.get("packages") or [])
                }
                current_priv = {
                    str(p)
                    for m in (plan.get("privileged_mutations") or [])
                    for p in (m.get("packages") or [])
                }
                if current_priv - prior_priv:
                    raise_lifecycle(
                        ModuleManagerError(
                            "privileged packages expanded since approval",
                            code="PLAN_STALE_REAPPROVAL_REQUIRED",
                            module_id=module_id,
                            action=action,
                            detail="privileged packages expanded since approval",
                        )
                    )
        if approval_service is None or not hasattr(approval_service, "is_approved"):
            raise_lifecycle(
                ModuleManagerError(
                    "approval service unavailable",
                    code="APPROVAL_SERVICE_UNAVAILABLE",
                    module_id=module_id,
                    action=action,
                    detail="approval service unavailable",
                )
            )
        approved = approval_service.is_approved(
            approval_id,
            capability_id="external.module.install",
            side_effects=(
                SideEffect.READ,
                SideEffect.WRITE,
                SideEffect.NETWORK,
                SideEffect.EXECUTE,
            ),
            arguments=binding,
        )
        if not approved:
            # Retry with current plan hash if client sent an older binding shape.
            binding_current = _approval_binding_args(module_id=module_id, ref=ref, plan=plan)
            approved = approval_service.is_approved(
                approval_id,
                capability_id="external.module.install",
                side_effects=(
                    SideEffect.READ,
                    SideEffect.WRITE,
                    SideEffect.NETWORK,
                    SideEffect.EXECUTE,
                ),
                arguments=binding_current,
            )
        if not approved:
            raise_lifecycle(
                ModuleManagerError(
                    "approval is not approved or arguments digest mismatch",
                    code="APPROVAL_INVALID",
                    module_id=module_id,
                    action=action,
                    detail="approval is not approved or arguments digest mismatch",
                )
            )
        if store is not None and hasattr(store, "update_install_operation"):
            store.update_install_operation(
                operation_id,
                approval_id=approval_id,
                status="QUEUED",
                phase="QUEUED",
            )

    worker_args: dict[str, Any] = {
        "module_id": module_id,
        "ref": ref,
        "force": force,
        "activate": activate,
        "plan_hash": plan.get("plan_hash"),
        "operation_id": operation_id,
        "auto_resolve_dependencies": auto_resolve_dependencies,
        "allow_system_deps": True if (requires_approval or approval_id) else False,
        "approval_id": approval_id,
    }
    # Drop None ref for cleaner idempotency / approval digests on non-privileged path.
    if worker_args.get("ref") is None:
        # Keep key for install_version clarity; harmless for install.
        pass

    try:
        queued = _queue_install(
            job_runtime=job_runtime,
            approval_service=approval_service,
            module_id=module_id,
            action=action,
            arguments=worker_args,
            requested_by=requested_by,
            idempotency_key=idempotency_key,
            emit=emit,
            privileged=requires_approval,
            approval_id=approval_id,
        )
        if store is not None and hasattr(store, "update_install_operation"):
            store.update_install_operation(
                operation_id,
                status="QUEUED",
                phase="QUEUED",
                job_id=queued.get("job_id"),
                approval_id=queued.get("approval_id") or approval_id,
            )
        return {**queued, "plan": plan, "operation_id": operation_id}
    except HTTPException as exc:
        # Production: never fall back to inline pip/npm/venv on the API thread.
        # TEST-ONLY: explicit allow gate may use _sync_install for deterministic fixtures.
        from Data.modules.module_manager.external.install_gate import allow_sync_install_for_tests

        if not (allow_sync_install_fallback and allow_sync_install_for_tests()):
            raise
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        code = str(detail.get("code") or "INSTALL_QUEUE_FAILED")
        if code not in {"INSTALL_WORKER_UNAVAILABLE", "INSTALL_QUEUE_FAILED"}:
            raise
        emit(
            "module.install.sync_dev_fallback",
            {"module_id": module_id, "action": action, "error_code": code},
            level="warning",
        )
        emit("module.install.started", {"module_id": module_id, "action": action})
        try:
            result = _sync_install(
                module_manager=module_manager,
                module_id=module_id,
                action=action,
                ref=ref,
                force=force,
                activate=activate,
                plan_hash=plan.get("plan_hash"),
                operation_id=operation_id,
                auto_resolve_dependencies=auto_resolve_dependencies,
                allow_system_deps=bool(requires_approval or approval_id),
                prefer_install_version=prefer_install_version,
            )
        except ModuleManagerError as lifecycle_exc:
            raise_lifecycle(lifecycle_exc)
        managed = module_manager.get(module_id)
        emit("module.install.completed", {"module_id": module_id, "action": action})
        if store is not None and hasattr(store, "update_install_operation"):
            store.update_install_operation(
                operation_id,
                status="SUCCEEDED",
                phase="READY",
                progress=1.0,
            )
        return {
            "result": result,
            "module": managed.public_dict() if managed is not None else None,
            "operation_id": operation_id,
            "plan": plan,
            "executed_via": "sync_dev_fallback",
            "truth": {"production_worker_path": False, "test_only_sync": True},
        }
