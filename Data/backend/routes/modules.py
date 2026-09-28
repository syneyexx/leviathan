"""Module manager HTTP routes — lifecycle owner surface for modules/plugins."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from Data.modules.module_manager import ModuleManagerError
from Data.modules.module_manager.errors import (
    http_status_for_lifecycle_error,
    scrub_error_text,
    unknown_module_error,
)

logger = logging.getLogger("leviathan.modules")


class ModuleExecuteRequest(BaseModel):
    operation: str = Field(min_length=1, max_length=120)
    arguments: dict = Field(default_factory=dict)


class ModuleInstallRequest(BaseModel):
    force: bool = False
    ref: str | None = None


class ModuleInstallVersionRequest(BaseModel):
    ref: str | None = None
    activate: bool = False


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

    @router.post("/api/modules/{module_id}/install")
    def install_module(module_id: str, payload: ModuleInstallRequest | None = None) -> dict:
        _require_enabled()
        payload = payload or ModuleInstallRequest()
        _require_known(module_id, "install")
        arguments: dict[str, Any] = {"module_id": module_id, "force": payload.force}
        if payload.ref:
            arguments["ref"] = payload.ref
        queued = _try_queue_install(
            job_runtime=job_runtime,
            approval_service=approval_service,
            module_id=module_id,
            action="install",
            arguments=arguments,
            requested_by="api.modules.install",
            idempotency_key=f"ext-install:{module_id}:{payload.ref or 'active'}",
            emit=_emit,
        )
        if queued is not None:
            return queued
        _emit("module.install.started", {"module_id": module_id, "action": "install"})
        try:
            if payload.ref:
                result = module_manager.install_version(module_id, ref=payload.ref, activate=True)
            else:
                result = module_manager.ensure_installed(module_id)
        except ModuleManagerError as exc:
            _raise_lifecycle(exc)
        managed = module_manager.get(module_id)
        _emit("module.install.completed", {"module_id": module_id, "action": "install"})
        return {"result": result, "module": managed.public_dict() if managed is not None else None}

    @router.post("/api/modules/{module_id}/start")
    def start_module(module_id: str) -> dict:
        _require_enabled()
        try:
            result = module_manager.start(module_id)
        except ModuleManagerError as exc:
            _raise_lifecycle(exc)
        observability.emit("module_manager", "start", payload={"module_id": module_id})
        return {"result": result, "module": module_manager.get(module_id).public_dict()}

    @router.post("/api/modules/{module_id}/stop")
    def stop_module(module_id: str) -> dict:
        _require_enabled()
        try:
            result = module_manager.stop(module_id)
        except ModuleManagerError as exc:
            _raise_lifecycle(exc)
        observability.emit("module_manager", "stop", payload={"module_id": module_id})
        return {"result": result, "module": module_manager.get(module_id).public_dict()}

    @router.post("/api/modules/{module_id}/restart")
    def restart_module(module_id: str) -> dict:
        _require_enabled()
        try:
            result = module_manager.restart(module_id)
        except ModuleManagerError as exc:
            _raise_lifecycle(exc)
        observability.emit("module_manager", "restart", payload={"module_id": module_id})
        return {"result": result, "module": module_manager.get(module_id).public_dict()}

    @router.post("/api/modules/{module_id}/ensure-ready")
    def ensure_ready_module(module_id: str) -> dict:
        _require_enabled()
        try:
            result = module_manager.ensure_ready(module_id)
        except ModuleManagerError as exc:
            _raise_lifecycle(exc)
        observability.emit("module_manager", "ensure_ready", payload={"module_id": module_id})
        managed = module_manager.get(module_id)
        return {
            "result": result,
            "module": managed.public_dict() if managed is not None else None,
        }

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
    def module_jobs(module_id: str) -> dict:
        _require_enabled()
        try:
            jobs = module_manager.active_jobs(module_id)
        except ModuleManagerError as exc:
            _raise_lifecycle(exc)
        return {"module_id": module_id, "jobs": jobs, "count": len(jobs)}

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
    def module_install_version(module_id: str, payload: ModuleInstallVersionRequest | None = None) -> dict:
        _require_enabled()
        payload = payload or ModuleInstallVersionRequest()
        _require_known(module_id, "install_version")
        arguments = {"module_id": module_id, "ref": payload.ref, "activate": payload.activate}
        # Activation changes the live runtime and stays synchronous so an active
        # job conflict is reported on this request. Non-activating installs queue.
        queued = None
        if not payload.activate:
            queued = _try_queue_install(
                job_runtime=job_runtime,
                approval_service=approval_service,
                module_id=module_id,
                action="install_version",
                arguments=arguments,
                requested_by="api.modules.install_version",
                idempotency_key=f"ext-install-ver:{module_id}:{payload.ref or 'active'}",
                emit=_emit,
            )
        if queued is not None:
            return queued
        _emit(
            "module.install.started",
            {"module_id": module_id, "action": "install_version", "activate": payload.activate},
        )
        try:
            result = module_manager.install_version(
                module_id,
                ref=payload.ref,
                activate=payload.activate,
            )
        except ModuleManagerError as exc:
            _raise_lifecycle(exc)
        managed = module_manager.get(module_id)
        _emit(
            "module.install.completed",
            {"module_id": module_id, "action": "install_version", "activate": payload.activate},
        )
        return {"result": result, "module": managed.public_dict() if managed is not None else None}

    @router.post("/api/modules/{module_id}/activate-version")
    def module_activate_version(module_id: str, payload: ModuleActivateVersionRequest) -> dict:
        _require_enabled()
        try:
            result = module_manager.activate_version(module_id, payload.version_id)
        except ModuleManagerError as exc:
            _raise_lifecycle(exc)
        observability.emit(
            "module_manager",
            "activate_version",
            payload={"module_id": module_id, "version_id": payload.version_id},
        )
        return {"result": result, "module": module_manager.get(module_id).public_dict()}

    @router.post("/api/modules/{module_id}/rollback-version")
    def module_rollback_version(module_id: str, payload: ModuleRollbackVersionRequest | None = None) -> dict:
        _require_enabled()
        payload = payload or ModuleRollbackVersionRequest()
        try:
            result = module_manager.rollback_version(module_id, version_id=payload.version_id)
        except ModuleManagerError as exc:
            _raise_lifecycle(exc)
        observability.emit(
            "module_manager",
            "rollback_version",
            payload={"module_id": module_id, "version_id": payload.version_id},
        )
        return {"result": result, "module": module_manager.get(module_id).public_dict()}

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
        try:
            result = module_manager.execute(module_id, payload.operation, payload.arguments)
        except ModuleManagerError as exc:
            _raise_lifecycle(exc)
        observability.emit(
            "module_manager",
            "execute",
            payload={"module_id": module_id, "operation": payload.operation, "status": result.status},
        )
        return {"result": result.public_dict()}

    return router


_ACTIVE_JOB_STATES = {"QUEUED", "RUNNING", "CREATED", "RETRY_WAIT", "CANCEL_REQUESTED"}


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


def _authorize_operator_install(approval_service: Any, capability_id: str, arguments: dict[str, Any]) -> str | None:
    """Record the modules API click as a single-use approval for the job path.

    Chat and other gateway callers still need their own approval. This does not
    auto-install OS packages or bypass ModuleManager.
    """
    if approval_service is None or not hasattr(approval_service, "request"):
        return None
    record = approval_service.request(
        capability_id=capability_id,
        side_effects=("READ", "EXECUTE"),
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


def _try_queue_install(
    *,
    job_runtime: Any,
    approval_service: Any,
    module_id: str,
    action: str,
    arguments: dict[str, Any],
    requested_by: str,
    idempotency_key: str,
    emit: Any,
) -> dict[str, Any] | None:
    """Queue a lifecycle install, or return None so the caller runs it synchronously.

    Enqueue problems are logged. A missing queue is not reported as QUEUED.
    """
    if job_runtime is None or not hasattr(job_runtime, "enqueue"):
        return None
    gateway = getattr(job_runtime, "gateway", None)
    get_capability = getattr(gateway, "get_capability", None) if gateway is not None else None
    if not callable(get_capability):
        _observe_enqueue_failure(
            emit=emit,
            module_id=module_id,
            action=action,
            exc=RuntimeError("job runtime gateway unavailable"),
        )
        return None
    definition = get_capability("external.module.install")
    if definition is None:
        _observe_enqueue_failure(
            emit=emit,
            module_id=module_id,
            action=action,
            exc=KeyError("unknown capability external.module.install"),
        )
        return None
    approval_id = None
    if _capability_requires_approval(definition):
        try:
            approval_id = _authorize_operator_install(approval_service, "external.module.install", arguments)
        except Exception as exc:  # noqa: BLE001 — fall back to the synchronous lifecycle owner
            _observe_enqueue_failure(emit=emit, module_id=module_id, action=action, exc=exc)
            return None
        if not approval_id:
            _observe_enqueue_failure(
                emit=emit,
                module_id=module_id,
                action=action,
                exc=RuntimeError("approval required for external.module.install"),
            )
            return None

    def _enqueue(key: str) -> Any:
        return job_runtime.enqueue(
            capability_id="external.module.install",
            arguments=arguments,
            requested_by=requested_by,
            idempotency_key=key,
            approval_id=approval_id,
        )

    try:
        job = _enqueue(idempotency_key)
        if _job_state(job) not in _ACTIVE_JOB_STATES:
            # A previous terminal job must not block a new operator request.
            job = _enqueue(f"{idempotency_key}:retry")
    except Exception as exc:  # noqa: BLE001 — synchronous ModuleManager fallback
        _observe_enqueue_failure(emit=emit, module_id=module_id, action=action, exc=exc)
        return None
    state = _job_state(job) or "QUEUED"
    if state not in _ACTIVE_JOB_STATES:
        _observe_enqueue_failure(
            emit=emit,
            module_id=module_id,
            action=action,
            exc=RuntimeError(f"enqueue returned terminal state {state}"),
        )
        return None
    job_id = getattr(job, "job_id", None)
    emit(
        "module.install.queued",
        {"module_id": module_id, "action": action, "job_id": job_id, "status": state},
    )
    return {"job_id": job_id, "run_id": getattr(job, "run_id", None), "status": state}
