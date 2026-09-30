from __future__ import annotations

import importlib
import inspect
import logging
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, NoReturn

from .discovery import ManifestError, discover_manifest_paths, load_manifest_file
from .errors import (
    ModuleManagerError,
    coerce_lifecycle_error,
    failure_from_lifecycle_result,
    scrub_error_text,
    unknown_module_error,
)
from .subprocess_exec import SubprocessModuleExecutor
from .types import (
    ILeviathanModule,
    ModuleContext,
    ModuleHealth,
    ModuleIsolation,
    ModuleManifest,
    ModuleResult,
    ModuleStatus,
)

logger = logging.getLogger("leviathan.module_manager")

# Cached snapshot health older than this is projected as STALE (not live-healthy).
_HEALTH_STALE_SECONDS = 120.0

# Statuses that may accept execute / ensure_ready without re-init.
_READY_STATUSES = {
    ModuleStatus.READY,
    ModuleStatus.INITIALIZED,
    ModuleStatus.RUNNING,
    ModuleStatus.BUSY,
    ModuleStatus.INSTALLED,
    ModuleStatus.DEGRADED,
}

_INSTALLED_STATUSES = {
    ModuleStatus.INSTALLED,
    ModuleStatus.LOADED,
    ModuleStatus.INITIALIZED,
    ModuleStatus.INITIALIZING,
    ModuleStatus.READY,
    ModuleStatus.STARTING,
    ModuleStatus.RUNNING,
    ModuleStatus.BUSY,
    ModuleStatus.EXECUTING,
    ModuleStatus.STOPPING,
    ModuleStatus.STOPPED,
    ModuleStatus.DISABLED,
    ModuleStatus.DEGRADED,
}

_BUSY_STATUSES = {
    ModuleStatus.BUSY,
    ModuleStatus.EXECUTING,
    ModuleStatus.STARTING,
    ModuleStatus.STOPPING,
    ModuleStatus.INITIALIZING,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_iso(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:  # noqa: BLE001
        return None


@dataclass
class ManagedModule:
    manifest: ModuleManifest
    status: ModuleStatus = ModuleStatus.DISCOVERED
    instance: ILeviathanModule | None = None
    error: str | None = None
    last_result: ModuleResult | None = None
    desired_state: str | None = None
    active_jobs: list[str] = field(default_factory=list)
    # Cached measured health — never refreshed by public_dict / GET /api/modules.
    last_health: dict[str, Any] | None = None
    last_health_at: str | None = None
    last_update_check: dict[str, Any] | None = None
    last_update_check_at: str | None = None

    def _adapter_name(self) -> str | None:
        external = (self.manifest.metadata or {}).get("external")
        if isinstance(external, dict):
            adapter = external.get("adapter")
            return str(adapter) if adapter else None
        return None

    def _has_lifecycle_adapter(self) -> bool:
        return bool(self._adapter_name() or (self.manifest.metadata or {}).get("external"))

    def _health_age_seconds(self) -> float | None:
        ts = _parse_iso(self.last_health_at)
        if ts is None:
            return None
        return max(0.0, time.time() - ts)

    def _health_freshness(self) -> str:
        if self.last_health is None:
            return "UNMEASURED"
        age = self._health_age_seconds()
        if age is None:
            return "UNMEASURED"
        if age > _HEALTH_STALE_SECONDS:
            return "STALE"
        return "FRESH"

    def _cached_health_public(self) -> dict[str, Any] | None:
        """Return bounded cached health for snapshots — never calls instance.health()."""
        if self.last_health is None:
            return None
        out = dict(self.last_health)
        freshness = self._health_freshness()
        out["freshness"] = freshness
        out.setdefault("checked_at", self.last_health_at)
        if freshness == "STALE":
            # Do not present stale measurements as currently healthy.
            status = str(out.get("status") or "").upper()
            if status in {"READY", "RUNNING", "INSTALLED", "HEALTHY", "OK"}:
                out["status"] = "STALE"
                out["detail"] = out.get("detail") or "Cached health is stale — refresh with Health"
        return out

    def allowed_actions(self, *, manager_enabled: bool = True) -> dict[str, Any]:
        """Server-projected lifecycle action availability (canonical over frontend guesses)."""
        blocked: dict[str, str] = {}
        actions = {
            "can_install": False,
            "can_start": False,
            "can_stop": False,
            "can_restart": False,
            "can_ensure_ready": False,
            "can_execute": False,
            "can_check_health": False,
            "can_check_update": False,
            "can_install_version": False,
            "can_activate_version": False,
            "can_rollback": False,
            "can_jobs": False,
            "can_logs": False,
            "can_capabilities": False,
            "can_versions": False,
        }

        def deny(key: str, reason: str) -> None:
            actions[key] = False
            blocked[key] = reason

        def allow(key: str) -> None:
            actions[key] = True

        if not manager_enabled:
            for key in list(actions):
                deny(key, "Module manager feature flag OFF")
            return {"allowed": actions, "blocked_reasons": blocked}

        lifecycle = self._has_lifecycle_adapter()
        busy = self.status in _BUSY_STATUSES or bool(self.active_jobs)
        installed = self.status in _INSTALLED_STATUSES
        not_installed = self.status in {ModuleStatus.DISCOVERED} or (
            not installed and self.status not in {ModuleStatus.READY}
        )
        ready_like = self.status in {
            ModuleStatus.READY,
            ModuleStatus.RUNNING,
            ModuleStatus.BUSY,
            ModuleStatus.EXECUTING,
        }

        if not lifecycle:
            for key in (
                "can_install",
                "can_start",
                "can_stop",
                "can_restart",
                "can_ensure_ready",
                "can_check_health",
                "can_check_update",
                "can_install_version",
                "can_activate_version",
                "can_rollback",
                "can_jobs",
                "can_logs",
                "can_capabilities",
                "can_versions",
            ):
                deny(key, "No lifecycle adapter")
        else:
            if busy:
                for key in (
                    "can_install",
                    "can_start",
                    "can_stop",
                    "can_restart",
                    "can_ensure_ready",
                    "can_install_version",
                    "can_activate_version",
                    "can_rollback",
                ):
                    deny(key, "Module is busy")
            else:
                if not_installed or self.status in {
                    ModuleStatus.DISCOVERED,
                    ModuleStatus.FAILED,
                    ModuleStatus.ERROR,
                }:
                    allow("can_install")
                else:
                    deny("can_install", f"Install not available (status: {self.status.value})")

                if self.status in {
                    ModuleStatus.INSTALLED,
                    ModuleStatus.STOPPED,
                    ModuleStatus.READY,
                    ModuleStatus.DISCOVERED,
                    ModuleStatus.LOADED,
                }:
                    allow("can_start")
                else:
                    deny("can_start", f"Start not available (status: {self.status.value})")

                if self.status in {
                    ModuleStatus.READY,
                    ModuleStatus.RUNNING,
                    ModuleStatus.BUSY,
                    ModuleStatus.INSTALLED,
                }:
                    allow("can_stop")
                else:
                    deny("can_stop", f"Stop not available (status: {self.status.value})")

                if installed:
                    allow("can_restart")
                else:
                    deny("can_restart", "Module not installed")

                allow("can_ensure_ready")
                allow("can_install_version")
                allow("can_activate_version")
                allow("can_rollback")

            allow("can_check_health")
            allow("can_check_update")
            allow("can_jobs")
            allow("can_logs")
            allow("can_capabilities")
            allow("can_versions")

        if ready_like and not busy:
            allow("can_execute")
        elif not ready_like:
            deny("can_execute", f"Requires READY/RUNNING (current: {self.status.value})")
        else:
            deny("can_execute", "Module is busy")

        return {"allowed": actions, "blocked_reasons": blocked}

    def public_dict(self) -> dict[str, Any]:
        runtime_state = self.status.value
        adapter = self._adapter_name()
        if self.instance is not None and hasattr(self.instance, "runtime_state"):
            try:
                runtime_state = str(self.instance.runtime_state())
            except Exception:  # noqa: BLE001
                pass
        action_state = self.allowed_actions(manager_enabled=True)
        external = (self.manifest.metadata or {}).get("external")
        source_type = None
        source_ref = None
        resource_class = None
        isolation = self.manifest.isolation.value if self.manifest.isolation else None
        if isinstance(external, dict):
            source = external.get("source")
            if isinstance(source, dict):
                source_type = source.get("type") or source.get("kind")
                source_ref = source.get("ref")
            source_type = source_type or external.get("source_type")
            resource_class = external.get("resource_class")
        side_effects: list[str] = []
        for effect in self.manifest.side_effects or ():
            side_effects.append(str(effect))
        for cap in self.manifest.capabilities or ():
            for effect in cap.side_effects or ():
                if str(effect) not in side_effects:
                    side_effects.append(str(effect))
        return {
            "manifest": self.manifest.public_dict(),
            "status": self.status.value,
            "runtime_state": runtime_state,
            "desired_state": self.desired_state,
            "adapter": adapter,
            "error": self.error,
            "active_jobs": list(self.active_jobs),
            "last_result": self.last_result.public_dict() if self.last_result else None,
            # Snapshot health is cached only — never fans out to live probes.
            "health": self._cached_health_public(),
            "health_freshness": self._health_freshness(),
            "last_health_at": self.last_health_at,
            "update_evidence": self.last_update_check,
            "last_update_check_at": self.last_update_check_at,
            "allowed_actions": action_state["allowed"],
            "blocked_reasons": action_state["blocked_reasons"],
            "source_type": source_type,
            "source_ref": source_ref,
            "resource_class": resource_class,
            "isolation": isolation,
            "declared_side_effects": side_effects,
            "truth": {
                "persisted_or_declared_state_is_not_live_health": True,
                "module_manager_is_lifecycle_owner": True,
                "snapshot_health_is_cached_not_live": True,
                "discoverable_is_not_authorized": True,
                "declared_side_effects_are_not_authorized": True,
                "allowed_actions_are_server_projected": True,
            },
        }


@dataclass
class ModuleManager:
    """Single discovery/lifecycle owner for LEVIATHAN modules and plugins.

    Does not authorize side effects — ExecutionGateway remains the only execution
    authority for catalogued capabilities. Module.execute is for module-local
    operations and must not bypass the gateway for WRITE/NETWORK/EXECUTE effects.
    """

    discovery_roots: tuple[Path, ...]
    execute_timeout_seconds: float = 30.0
    enabled: bool = True
    allow_subprocess_isolation: bool = False
    _modules: dict[str, ManagedModule] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _last_context: ModuleContext | None = field(default=None, repr=False)
    telemetry: dict[str, Any] = field(
        default_factory=lambda: {
            "discovered": 0,
            "loaded": 0,
            "initialized": 0,
            "execute_calls": 0,
            "execute_failures": 0,
            "reload_attempts": 0,
            "subprocess_executes": 0,
            "errors": 0,
            "install_started": 0,
            "install_completed": 0,
            "install_failed": 0,
        }
    )

    def list(self) -> list[ManagedModule]:
        with self._lock:
            return sorted(self._modules.values(), key=lambda item: item.manifest.module_id)

    def get(self, module_id: str) -> ManagedModule | None:
        with self._lock:
            return self._modules.get(module_id)

    def discover(self) -> list[ModuleManifest]:
        if not self.enabled:
            return []
        manifests: list[ModuleManifest] = []
        for path in discover_manifest_paths(self.discovery_roots):
            try:
                manifest = load_manifest_file(path)
            except ManifestError as exc:
                self.telemetry["errors"] += 1
                # Keep going — one bad plugin must not poison discovery.
                managed = ManagedModule(
                    manifest=ModuleManifest(
                        module_id=f"invalid:{path.parent.name}",
                        name=path.parent.name,
                        version="0.0.0",
                        entrypoint="invalid:invalid",
                        source_path=str(path),
                        metadata={"discovery_error": str(exc)},
                    ),
                    status=ModuleStatus.ERROR,
                    error=str(exc),
                )
                with self._lock:
                    self._modules[managed.manifest.module_id] = managed
                continue
            with self._lock:
                existing = self._modules.get(manifest.module_id)
                if existing and existing.status in {
                    ModuleStatus.READY,
                    ModuleStatus.INITIALIZED,
                    ModuleStatus.LOADED,
                    ModuleStatus.RUNNING,
                    ModuleStatus.BUSY,
                    ModuleStatus.EXECUTING,
                    ModuleStatus.STARTING,
                }:
                    # Do not clobber a live instance on rediscover.
                    manifests.append(existing.manifest)
                    continue
                self._modules[manifest.module_id] = ManagedModule(
                    manifest=manifest,
                    status=ModuleStatus.DISCOVERED,
                )
            manifests.append(manifest)
            self.telemetry["discovered"] += 1
        return manifests

    def load(self, module_id: str) -> ManagedModule:
        managed = self._require(module_id)
        if managed.status == ModuleStatus.ERROR and managed.instance is None and managed.manifest.entrypoint == "invalid:invalid":
            raise ModuleManagerError(managed.error or "invalid manifest")
        try:
            factory = self._resolve_factory(managed.manifest.entrypoint)
            instance = self._call_factory(factory, managed.manifest)
            if not isinstance(instance, ILeviathanModule):
                # Protocol check — also verify required attributes exist.
                for attr in ("manifest", "initialize", "execute", "shutdown", "health"):
                    if not hasattr(instance, attr):
                        raise ModuleManagerError(f"Module missing ILeviathanModule attribute: {attr}")
            managed.instance = instance
            managed.status = ModuleStatus.LOADED
            managed.error = None
            self.telemetry["loaded"] += 1
            return managed
        except Exception as exc:  # noqa: BLE001 — containment boundary
            managed.status = ModuleStatus.ERROR
            managed.error = f"load failed: {exc}"
            managed.instance = None
            self.telemetry["errors"] += 1
            raise ModuleManagerError(managed.error) from exc

    def initialize(self, module_id: str, ctx: ModuleContext | None = None) -> ManagedModule:
        managed = self._require(module_id)
        if managed.instance is None:
            self.load(module_id)
            managed = self._require(module_id)
        assert managed.instance is not None
        context = ctx or ModuleContext()
        self._last_context = context
        managed.status = ModuleStatus.INITIALIZING
        try:
            managed.instance.initialize(context)
            # External modules may report INSTALLED/READY/STOPPED after init.
            if hasattr(managed.instance, "runtime_state"):
                try:
                    rt = str(managed.instance.runtime_state()).upper()
                    managed.status = ModuleStatus[rt] if rt in ModuleStatus.__members__ else ModuleStatus.READY
                except Exception:  # noqa: BLE001
                    managed.status = ModuleStatus.READY
            else:
                managed.status = ModuleStatus.READY
            managed.error = None
            self.telemetry["initialized"] += 1
            return managed
        except Exception as exc:  # noqa: BLE001 — containment boundary
            managed.status = ModuleStatus.ERROR
            managed.error = f"initialize failed: {exc}"
            self.telemetry["errors"] += 1
            raise ModuleManagerError(managed.error) from exc

    def execute(
        self,
        module_id: str,
        operation: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> ModuleResult:
        managed = self._require(module_id)
        if managed.instance is None or managed.status not in _READY_STATUSES | {
            ModuleStatus.STOPPED,
            ModuleStatus.DISABLED,
        }:
            # Auto-initialize when discovered/loaded.
            if managed.status in {ModuleStatus.DISCOVERED, ModuleStatus.LOADED, ModuleStatus.INSTALLED}:
                self.initialize(module_id, self._last_context)
                managed = self._require(module_id)
            elif managed.instance is None:
                raise ModuleManagerError(f"Module not ready: {module_id} ({managed.status.value})")
        if managed.instance is None:
            raise ModuleManagerError(f"Module not ready: {module_id} ({managed.status.value})")
        self.telemetry["execute_calls"] += 1
        previous = managed.status
        managed.status = ModuleStatus.EXECUTING
        started = time.perf_counter()
        args = dict(arguments or {})

        # Phase 50: optional subprocess isolation for untrusted plugins.
        if (
            managed.manifest.isolation == ModuleIsolation.SUBPROCESS
            and self.allow_subprocess_isolation
        ):
            self.telemetry["subprocess_executes"] += 1
            executor = SubprocessModuleExecutor(timeout_seconds=self.execute_timeout_seconds)
            ctx = self._last_context or ModuleContext()
            raw = executor.execute(
                entrypoint=managed.manifest.entrypoint,
                operation=operation,
                arguments=args,
                context={
                    "database_path": ctx.database_path,
                    "data_root": ctx.data_root,
                    "feature_flags": dict(ctx.feature_flags),
                    "metadata": dict(ctx.metadata),
                },
            )
            status = str(raw.get("status") or "FAILED")
            result = ModuleResult(
                module_id=module_id,
                operation=operation,
                status=status,
                output=raw.get("output") if isinstance(raw.get("output"), dict) else raw,
                error=raw.get("error"),
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            managed.last_result = result
            managed.status = ModuleStatus.READY if status in {"COMPLETED", "OK", "SUCCESS"} else ModuleStatus.ERROR
            if managed.status == ModuleStatus.ERROR:
                self.telemetry["execute_failures"] += 1
            return result

        def _call() -> ModuleResult:
            assert managed.instance is not None
            return managed.instance.execute(operation, args)

        # External modules may declare longer timeouts in manifest.
        timeout = self.execute_timeout_seconds
        external = (managed.manifest.metadata or {}).get("external")
        if isinstance(external, dict):
            runtime = external.get("runtime") or {}
            if isinstance(runtime, dict) and runtime.get("timeout_seconds"):
                try:
                    timeout = max(timeout, float(runtime["timeout_seconds"]))
                except (TypeError, ValueError):
                    pass

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_call)
                result = future.result(timeout=timeout)
            if not isinstance(result, ModuleResult):
                raise ModuleManagerError("Module execute must return ModuleResult")
            managed.last_result = result
            # Restore prior semantic state for long-lived modules (RUNNING etc.).
            if previous in {ModuleStatus.RUNNING, ModuleStatus.READY, ModuleStatus.INSTALLED}:
                managed.status = previous if previous != ModuleStatus.EXECUTING else ModuleStatus.READY
            else:
                managed.status = ModuleStatus.READY
            if result.status.upper() not in {"COMPLETED", "OK", "SUCCESS"}:
                self.telemetry["execute_failures"] += 1
            return result
        except FuturesTimeout as exc:
            managed.status = ModuleStatus.ERROR
            managed.error = f"execute timeout after {self.execute_timeout_seconds}s"
            self.telemetry["execute_failures"] += 1
            self.telemetry["errors"] += 1
            result = ModuleResult(
                module_id=module_id,
                operation=operation,
                status="TIMEOUT",
                error=managed.error,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            managed.last_result = result
            raise ModuleManagerError(
                managed.error,
                code="TIMEOUT",
                module_id=module_id,
                action="execute",
                detail=managed.error,
            ) from exc
        except Exception as exc:  # noqa: BLE001 — containment boundary
            managed.status = ModuleStatus.ERROR
            managed.error = f"execute crashed: {exc}"
            self.telemetry["execute_failures"] += 1
            self.telemetry["errors"] += 1
            result = ModuleResult(
                module_id=module_id,
                operation=operation,
                status="FAILED",
                error=f"{exc}\n{traceback.format_exc(limit=3)}",
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            managed.last_result = result
            return result

    def shutdown(self, module_id: str) -> ManagedModule:
        managed = self._require(module_id)
        if managed.instance is not None:
            try:
                managed.instance.shutdown()
            except Exception as exc:  # noqa: BLE001 — best-effort shutdown
                managed.error = f"shutdown error: {exc}"
                self.telemetry["errors"] += 1
        managed.status = ModuleStatus.SHUTDOWN
        managed.instance = None
        return managed

    def reload(self, module_id: str, ctx: ModuleContext | None = None) -> ManagedModule:
        self.telemetry["reload_attempts"] += 1
        managed = self._require(module_id)
        if not managed.manifest.hot_reload:
            raise ModuleManagerError(f"Module does not allow hot_reload: {module_id}")
        previous = managed
        try:
            if managed.instance is not None:
                self.shutdown(module_id)
            # Re-read manifest from disk when possible.
            if managed.manifest.source_path:
                refreshed = load_manifest_file(Path(managed.manifest.source_path))
                with self._lock:
                    self._modules[module_id] = ManagedModule(manifest=refreshed, status=ModuleStatus.DISCOVERED)
            self.load(module_id)
            return self.initialize(module_id, ctx)
        except Exception as exc:
            # Restore previous ready state if we still have a usable snapshot — honest failure.
            with self._lock:
                self._modules[module_id] = previous
                previous.status = ModuleStatus.ERROR
                previous.error = f"reload failed: {exc}"
            self.telemetry["errors"] += 1
            raise ModuleManagerError(previous.error) from exc

    def discover_load_initialize_all(self, ctx: ModuleContext | None = None) -> list[ManagedModule]:
        """Discover and initialize modules.

        External modules without eager_start are discovered/loaded metadata-only
        (initialized lightly so manifests hydrate) but must not launch third-party
        processes. The ExternalCapabilityModule.initialize already respects eager_start.
        """
        self.discover()
        ready: list[ManagedModule] = []
        for managed in list(self.list()):
            if managed.status == ModuleStatus.ERROR:
                continue
            try:
                ready.append(self.initialize(managed.manifest.module_id, ctx))
            except ModuleManagerError:
                continue
        return ready

    def plan_install(
        self,
        module_id: str,
        *,
        ref: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Read-only install preflight; returns InstallPlan.public_dict()."""
        managed = self._ensure_instance(module_id)
        assert managed.instance is not None
        config = getattr(managed.instance, "external_config", None)
        if config is None:
            raise ModuleManagerError(
                f"module {module_id} does not support plan_install",
                code="INVALID_RESULT",
                module_id=module_id,
                action="plan_install",
                detail=f"module {module_id} does not support plan_install",
            )
        data_root = None
        if self._last_context is not None:
            data_root = self._last_context.data_root
        if not data_root:
            ctx_services = getattr(managed.instance, "_ctx_services", None) or {}
            data_root = ctx_services.get("data_root") if isinstance(ctx_services, dict) else None
        if not data_root:
            raise ModuleManagerError(
                "data_root required for plan_install",
                code="INSTALL_FAILED",
                module_id=module_id,
                action="plan_install",
                detail="data_root required for plan_install",
            )
        from .external.install import InstallationService

        plan = InstallationService(Path(data_root)).plan_install(
            module_id,
            config,
            ref=ref,
            force=force,
        )
        return plan.public_dict()

    def install(
        self,
        module_id: str,
        *,
        ref: str | None = None,
        force: bool = False,
        activate: bool = True,
        operation_id: str | None = None,
        plan_hash: str | None = None,
        approval_id: str | None = None,
        auto_resolve_dependencies: bool = True,
        allow_system_deps: bool = False,
        approved_plan: Any = None,
        progress: Any = None,
        cancel_check: Any = None,
        runner: Any = None,
        store: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Canonical module install path — forwards all install kwargs to adapters."""
        managed = self._ensure_instance(module_id)
        assert managed.instance is not None
        forwarded: dict[str, Any] = {
            "ref": ref,
            "force": force,
            "activate": activate,
            "operation_id": operation_id,
            "plan_hash": plan_hash,
            "auto_resolve_dependencies": auto_resolve_dependencies,
            "allow_system_deps": allow_system_deps,
            "approved_plan": approved_plan,
            "progress": progress,
            "cancel_check": cancel_check,
            "runner": runner,
        }
        if store is not None:
            forwarded["store"] = store
        if approval_id is not None:
            # Metadata pass-through for observability; InstallationService ignores unknown keys
            # so keep it out of _call_install forwarding — stash on kwargs only for callers.
            forwarded["_approval_id"] = approval_id
        for key, value in kwargs.items():
            if key not in forwarded and value is not None:
                forwarded[key] = value
        return self._run_install(
            managed,
            action="install",
            call=lambda: self._call_install(managed, **forwarded),
            activate=activate,
        )

    def ensure_installed(self, module_id: str, **kwargs: Any) -> dict[str, Any]:
        """Install a module. Operational adapter failures become ModuleManagerError."""
        kwargs.setdefault("activate", True)
        return self.install(module_id, **kwargs)

    def start(self, module_id: str) -> dict[str, Any]:
        managed = self._ensure_instance(module_id)
        assert managed.instance is not None
        previous = managed.status
        managed.status = ModuleStatus.STARTING
        managed.desired_state = "RUNNING"
        try:
            if hasattr(managed.instance, "start"):
                result = managed.instance.start()
            else:
                result = {"status": "READY", "detail": "start_noop"}
            if not isinstance(result, dict):
                result = {"status": "READY", "result": result}
            self._raise_if_result_failed(result, module_id=module_id, action="start")
            managed.status = (
                ModuleStatus.RUNNING
                if str(result.get("status") or "").upper() == "RUNNING"
                else ModuleStatus.READY
            )
            managed.error = None
            return result
        except Exception as exc:
            self._fail_lifecycle(managed, exc, module_id=module_id, action="start", previous=previous)

    def stop(self, module_id: str, *, expected_generation: int | None = None) -> dict[str, Any]:
        managed = self._ensure_instance(module_id)
        assert managed.instance is not None
        previous = managed.status
        managed.status = ModuleStatus.STOPPING
        managed.desired_state = "STOPPED"
        try:
            if hasattr(managed.instance, "stop"):
                try:
                    result = managed.instance.stop(expected_generation=expected_generation)
                except TypeError:
                    result = managed.instance.stop()
            else:
                result = {"status": "STOPPED", "detail": "stop_noop"}
            if not isinstance(result, dict):
                result = {"status": "STOPPED", "result": result}
            if result.get("refused") == "STALE_GENERATION":
                # Do not mark STOPPED when a stale stop was refused — newer generation lives.
                managed.status = previous
                managed.desired_state = "RUNNING"
                managed.error = None
                return result
            self._raise_if_result_failed(result, module_id=module_id, action="stop")
            managed.status = ModuleStatus.STOPPED
            managed.error = None
            return result
        except Exception as exc:
            self._fail_lifecycle(managed, exc, module_id=module_id, action="stop", previous=previous)

    def restart(self, module_id: str) -> dict[str, Any]:
        self.stop(module_id)
        return self.start(module_id)

    def ensure_ready(self, module_id: str) -> dict[str, Any]:
        managed = self._ensure_instance(module_id)
        assert managed.instance is not None
        previous = managed.status
        try:
            if hasattr(managed.instance, "ensure_ready"):
                result = managed.instance.ensure_ready()
            else:
                if managed.status not in _READY_STATUSES:
                    self.initialize(module_id, self._last_context)
                    managed = self._require(module_id)
                result = {"ready": True, "status": managed.status.value}
            if not isinstance(result, dict):
                result = {"ready": True, "result": result}
            if result.get("ready"):
                status = str(result.get("status") or "").upper()
                if status == "RUNNING":
                    managed.status = ModuleStatus.RUNNING
                elif managed.status not in {ModuleStatus.RUNNING, ModuleStatus.BUSY}:
                    managed.status = ModuleStatus.READY
                managed.error = None
            return result
        except Exception as exc:
            self._fail_lifecycle(
                managed, exc, module_id=module_id, action="ensure_ready", previous=previous
            )

    def health(self, module_id: str) -> ModuleHealth:
        """Explicit live health measurement — caches result for cheap snapshots."""
        managed = self._ensure_instance(module_id)
        assert managed.instance is not None
        try:
            measured = managed.instance.health()
            checked_at = _utc_now()
            if isinstance(measured, ModuleHealth):
                payload = measured.public_dict()
                # Preserve adapter telemetry; stamp measurement time.
                if not payload.get("checked_at"):
                    payload = {**payload, "checked_at": checked_at}
                    measured = ModuleHealth(
                        module_id=measured.module_id,
                        status=measured.status,
                        detail=measured.detail,
                        telemetry=dict(measured.telemetry or {}),
                        checked_at=checked_at,
                    )
                managed.last_health = payload
                managed.last_health_at = checked_at
                return measured
            # Defensive: adapters should return ModuleHealth.
            payload = {
                "module_id": module_id,
                "status": str(getattr(measured, "status", managed.status.value)),
                "detail": str(getattr(measured, "detail", "ok")),
                "telemetry": dict(getattr(measured, "telemetry", {}) or {}),
                "checked_at": checked_at,
            }
            managed.last_health = payload
            managed.last_health_at = checked_at
            return ModuleHealth(
                module_id=module_id,
                status=managed.status,
                detail=payload["detail"],
                telemetry=payload["telemetry"],
                checked_at=checked_at,
            )
        except Exception as exc:
            self._fail_lifecycle(
                managed, exc, module_id=module_id, action="health", previous=managed.status
            )

    def logs(self, module_id: str, *, limit: int = 200) -> list[str]:
        managed = self._ensure_instance(module_id)
        assert managed.instance is not None
        try:
            if hasattr(managed.instance, "logs"):
                return list(managed.instance.logs(limit=limit))
            return []
        except Exception as exc:
            self._fail_lifecycle(
                managed, exc, module_id=module_id, action="logs", previous=managed.status
            )

    def active_jobs(self, module_id: str) -> list[str]:
        managed = self._require(module_id)
        return list(managed.active_jobs)

    def register_job(self, module_id: str, job_id: str) -> None:
        managed = self._require(module_id)
        if job_id not in managed.active_jobs:
            managed.active_jobs.append(job_id)

    def unregister_job(self, module_id: str, job_id: str) -> None:
        managed = self._require(module_id)
        managed.active_jobs = [j for j in managed.active_jobs if j != job_id]

    def check_update(self, module_id: str) -> dict[str, Any]:
        """Local update evidence (store/ref compare). Persists receipt on ManagedModule."""
        managed = self._ensure_instance(module_id)
        assert managed.instance is not None
        previous = managed.status
        try:
            if hasattr(managed.instance, "check_update"):
                result = managed.instance.check_update()
            else:
                result = {"module_id": module_id, "update_available": False, "reason": "not_external"}
            if not isinstance(result, dict):
                result = {"module_id": module_id, "update_available": False, "result": result}
            checked_at = _utc_now()
            result = {
                **result,
                "checked_at": result.get("checked_at") or checked_at,
                "truth": {
                    **(result.get("truth") if isinstance(result.get("truth"), dict) else {}),
                    "update_evidence_persisted_on_manager": True,
                },
            }
            managed.last_update_check = result
            managed.last_update_check_at = checked_at
            self._persist_update_evidence(managed, result)
            return result
        except Exception as exc:
            self._fail_lifecycle(
                managed, exc, module_id=module_id, action="check_update", previous=previous
            )

    def install_version(
        self,
        module_id: str,
        *,
        ref: str | None = None,
        activate: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        managed = self._ensure_instance(module_id)
        assert managed.instance is not None
        if activate and managed.active_jobs:
            raise ModuleManagerError(
                f"cannot activate while jobs active: {', '.join(managed.active_jobs[:5])}",
                code="UPDATE_BLOCKED_ACTIVE",
                module_id=module_id,
                action="install_version",
                detail=f"cannot activate while jobs active: {', '.join(managed.active_jobs[:5])}",
            )
        if not hasattr(managed.instance, "install_version"):
            # Fall back to canonical install path when module only exposes ensure_installed.
            return self.install(module_id, ref=ref, activate=activate, **kwargs)

        forwarded = {
            key: kwargs[key]
            for key in (
                "progress",
                "cancel_check",
                "force",
                "plan_hash",
                "operation_id",
                "auto_resolve_dependencies",
                "approved_plan",
                "allow_system_deps",
                "runner",
                "store",
            )
            if key in kwargs
        }

        def _call() -> Any:
            assert managed.instance is not None
            return managed.instance.install_version(
                ref=ref,
                activate=activate,
                active_jobs=list(managed.active_jobs),
                **forwarded,
            )

        return self._run_install(managed, action="install_version", call=_call, activate=activate)

    def activate_version(self, module_id: str, version_id: str) -> dict[str, Any]:
        managed = self._ensure_instance(module_id)
        assert managed.instance is not None
        if not hasattr(managed.instance, "activate_version"):
            raise ModuleManagerError(
                f"module {module_id} does not support activate_version",
                code="INVALID_RESULT",
                module_id=module_id,
                action="activate_version",
                detail=f"module {module_id} does not support activate_version",
            )
        previous = managed.status
        try:
            result = managed.instance.activate_version(version_id, active_jobs=list(managed.active_jobs))
            if not isinstance(result, dict):
                result = {"status": "ACTIVE", "result": result}
            self._raise_if_result_failed(result, module_id=module_id, action="activate_version")
            managed.error = None
            if str(result.get("status") or "").upper() == "ACTIVE":
                managed.status = ModuleStatus.INSTALLED
            return result
        except Exception as exc:
            self._fail_lifecycle(
                managed, exc, module_id=module_id, action="activate_version", previous=previous
            )

    def rollback_version(self, module_id: str, *, version_id: str | None = None) -> dict[str, Any]:
        managed = self._ensure_instance(module_id)
        assert managed.instance is not None
        if not hasattr(managed.instance, "rollback_version"):
            raise ModuleManagerError(
                f"module {module_id} does not support rollback_version",
                code="INVALID_RESULT",
                module_id=module_id,
                action="rollback_version",
                detail=f"module {module_id} does not support rollback_version",
            )
        previous = managed.status
        try:
            result = managed.instance.rollback_version(
                version_id=version_id,
                active_jobs=list(managed.active_jobs),
            )
            if not isinstance(result, dict):
                result = {"status": "ACTIVE", "result": result}
            self._raise_if_result_failed(result, module_id=module_id, action="rollback_version")
            managed.error = None
            return result
        except Exception as exc:
            self._fail_lifecycle(
                managed, exc, module_id=module_id, action="rollback_version", previous=previous
            )

    def list_versions(self, module_id: str) -> list[dict[str, Any]]:
        managed = self._ensure_instance(module_id)
        assert managed.instance is not None
        previous = managed.status
        try:
            if hasattr(managed.instance, "list_versions"):
                return list(managed.instance.list_versions())
            return []
        except Exception as exc:
            self._fail_lifecycle(
                managed, exc, module_id=module_id, action="versions", previous=previous
            )

    def sweep_idle_modules(self) -> list[dict[str, Any]]:
        """Stop idle LAZY/RESIDENT external processes with no active jobs."""
        stopped: list[dict[str, Any]] = []
        for managed in self.list():
            if managed.active_jobs:
                continue
            inst = managed.instance
            if inst is None or not hasattr(inst, "maybe_idle_shutdown"):
                continue
            try:
                result = inst.maybe_idle_shutdown()
            except Exception:  # noqa: BLE001
                continue
            if result and result.get("stopped"):
                managed.status = ModuleStatus.STOPPED
                managed.desired_state = "STOPPED"
                stopped.append({"module_id": managed.manifest.module_id, **result})
        return stopped

    def public_snapshot(self) -> dict[str, Any]:
        with self._lock:
            modules_out: list[dict[str, Any]] = []
            for item in self.list():
                payload = item.public_dict()
                # Re-project allowed actions with the live feature flag.
                action_state = item.allowed_actions(manager_enabled=self.enabled)
                payload["allowed_actions"] = action_state["allowed"]
                payload["blocked_reasons"] = action_state["blocked_reasons"]
                modules_out.append(payload)
            return {
                "enabled": self.enabled,
                "modules": modules_out,
                "telemetry": dict(self.telemetry),
                "discovery_roots": [str(path) for path in self.discovery_roots],
                "truth": {
                    "module_manager_is_not_execution_gateway": True,
                    "discoverable_is_not_authorized": True,
                    "persisted_running_is_not_live_running": True,
                    "snapshot_health_is_cached_not_live": True,
                    "allowed_actions_are_server_projected": True,
                },
            }

    def _persist_update_evidence(self, managed: ManagedModule, evidence: dict[str, Any]) -> None:
        """Best-effort persist update-check receipt into external CONTROL store metadata."""
        try:
            store = None
            if managed.instance is not None:
                store = getattr(managed.instance, "_store", None)
            if store is None or not hasattr(store, "get_module") or not hasattr(store, "upsert_module"):
                return
            module_id = managed.manifest.module_id
            existing = store.get_module(module_id) or {}
            metadata = dict(existing.get("metadata") or {})
            metadata["last_update_check"] = evidence
            metadata["last_update_check_at"] = evidence.get("checked_at") or _utc_now()
            store.upsert_module(
                module_id=module_id,
                name=str(existing.get("name") or managed.manifest.name),
                adapter=str(existing.get("adapter") or managed._adapter_name() or "EXTERNAL"),
                source=existing.get("source") if isinstance(existing.get("source"), dict) else {},
                desired_state=str(existing.get("desired_state") or managed.desired_state or "STOPPED"),
                runtime_state=str(existing.get("runtime_state") or managed.status.value),
                active_version_id=existing.get("active_version_id"),
                last_error=existing.get("last_error"),
                capability_count=int(existing.get("capability_count") or len(managed.manifest.capabilities)),
                metadata=metadata,
            )
        except Exception:  # noqa: BLE001 — persistence must not break check_update
            logger.debug("failed to persist update evidence for %s", managed.manifest.module_id, exc_info=True)

    def hydrate_update_evidence(self, module_id: str) -> dict[str, Any] | None:
        """Load persisted update evidence from external store into ManagedModule cache."""
        managed = self.get(module_id)
        if managed is None:
            return None
        if managed.last_update_check is not None:
            return managed.last_update_check
        try:
            store = None
            if managed.instance is not None:
                store = getattr(managed.instance, "_store", None)
            if store is None and hasattr(managed, "manifest"):
                return None
            if store is None or not hasattr(store, "get_module"):
                return None
            row = store.get_module(module_id) or {}
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            evidence = metadata.get("last_update_check")
            if isinstance(evidence, dict):
                managed.last_update_check = evidence
                managed.last_update_check_at = (
                    str(metadata.get("last_update_check_at") or evidence.get("checked_at") or "") or None
                )
                return evidence
        except Exception:  # noqa: BLE001
            return None
        return None

    def _ensure_instance(self, module_id: str) -> ManagedModule:
        managed = self._require(module_id)
        if managed.instance is None:
            self.initialize(module_id, self._last_context)
            managed = self._require(module_id)
        return managed

    def _require(self, module_id: str) -> ManagedModule:
        with self._lock:
            managed = self._modules.get(module_id)
            if managed is None:
                raise unknown_module_error(module_id, action="resolve")
            return managed

    def _call_install(self, managed: ManagedModule, **kwargs: Any) -> Any:
        assert managed.instance is not None
        if not hasattr(managed.instance, "ensure_installed"):
            return {"status": "INSTALLED", "detail": "no_install_required"}
        forwarded: dict[str, Any] = {}
        for key in (
            "progress",
            "cancel_check",
            "ref",
            "force",
            "activate",
            "plan_hash",
            "operation_id",
            "auto_resolve_dependencies",
            "approved_plan",
            "allow_system_deps",
            "runner",
            "store",
        ):
            if key not in kwargs:
                continue
            value = kwargs[key]
            # Forward explicit False/None for optional callbacks only when present;
            # always forward bool flags even when False.
            if key in {"progress", "cancel_check", "ref", "plan_hash", "operation_id", "approved_plan", "runner", "store"}:
                if value is not None:
                    forwarded[key] = value
            else:
                forwarded[key] = value
        return managed.instance.ensure_installed(**forwarded)

    def _run_install(
        self,
        managed: ManagedModule,
        *,
        action: str,
        call: Callable[[], Any],
        activate: bool,
    ) -> dict[str, Any]:
        module_id = managed.manifest.module_id
        previous = managed.status
        self.telemetry["install_started"] = int(self.telemetry.get("install_started", 0)) + 1
        managed.status = ModuleStatus.BUSY
        managed.desired_state = "INSTALLED"
        managed.error = None
        try:
            result = call()
            if not isinstance(result, dict):
                result = {"status": "INSTALLED", "result": result}
            self._raise_if_result_failed(result, module_id=module_id, action=action)
            if activate or previous in {
                ModuleStatus.DISCOVERED,
                ModuleStatus.LOADED,
                ModuleStatus.FAILED,
                ModuleStatus.ERROR,
                ModuleStatus.BUSY,
                ModuleStatus.INITIALIZING,
            }:
                managed.status = ModuleStatus.INSTALLED
            else:
                managed.status = previous
            managed.error = None
            self.telemetry["install_completed"] = int(self.telemetry.get("install_completed", 0)) + 1
            return result
        except Exception as exc:
            self.telemetry["install_failed"] = int(self.telemetry.get("install_failed", 0)) + 1
            self._fail_lifecycle(managed, exc, module_id=module_id, action=action, previous=previous)

    def _raise_if_result_failed(self, result: dict[str, Any], *, module_id: str, action: str) -> None:
        failed = failure_from_lifecycle_result(result)
        if failed is None:
            return
        code, detail = failed
        raise ModuleManagerError(
            f"{code}: {detail}",
            code=code,
            module_id=module_id,
            action=action,
            detail=detail,
        )

    def _fail_lifecycle(
        self,
        managed: ManagedModule,
        exc: BaseException,
        *,
        module_id: str,
        action: str,
        previous: ModuleStatus,
    ) -> NoReturn:
        """Record a lifecycle failure and raise the normalized contract.

        Unexpected defects are logged and re-raised so they stay HTTP 500.
        """
        normalized = coerce_lifecycle_error(exc, module_id=module_id, action=action)
        if normalized is None:
            managed.status = ModuleStatus.FAILED
            managed.error = scrub_error_text(f"{type(exc).__name__}: {exc}")
            self.telemetry["errors"] = int(self.telemetry.get("errors", 0)) + 1
            logger.exception(
                "module.lifecycle.unexpected module_id=%s action=%s error_class=%s",
                module_id,
                action,
                type(exc).__name__,
            )
            raise exc
        # A blocked version switch is not a failed installation of a live module.
        if normalized.code == "UPDATE_BLOCKED_ACTIVE" and previous != ModuleStatus.BUSY:
            managed.status = previous
        elif normalized.code == "UPDATE_BLOCKED_ACTIVE":
            managed.status = previous if previous != ModuleStatus.BUSY else ModuleStatus.INSTALLED
        else:
            managed.status = ModuleStatus.FAILED
        managed.error = scrub_error_text(f"{normalized.code}: {normalized.detail}")
        self.telemetry["errors"] = int(self.telemetry.get("errors", 0)) + 1
        if normalized is exc:
            raise normalized
        raise normalized from exc

    @staticmethod
    def _resolve_factory(entrypoint: str) -> Callable[..., Any]:
        module_name, _, attr = entrypoint.partition(":")
        if not module_name or not attr:
            raise ModuleManagerError(f"Invalid entrypoint: {entrypoint}")
        module = importlib.import_module(module_name)
        factory = getattr(module, attr, None)
        if factory is None or not callable(factory):
            raise ModuleManagerError(f"Entrypoint not callable: {entrypoint}")
        return factory

    @staticmethod
    def _call_factory(factory: Callable[..., Any], manifest: ModuleManifest) -> Any:
        """Backward-compatible factory invocation.

        ``factory()`` continues to work for first-party modules.
        Manifest-aware factories may accept ``factory(manifest=...)``.
        """
        try:
            signature = inspect.signature(factory)
        except (TypeError, ValueError):
            return factory()
        params = signature.parameters
        if "manifest" in params:
            return factory(manifest=manifest)
        # Positional single-arg factories that look like manifest-aware.
        positional = [
            p
            for p in params.values()
            if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            and p.default is inspect.Parameter.empty
        ]
        if len(positional) == 1 and positional[0].name in {"manifest", "module_manifest"}:
            return factory(manifest)
        return factory()

    def register_instance(self, instance: ILeviathanModule, *, ready: bool = False) -> ManagedModule:
        """Register an already-constructed first-party module (tests / builtins)."""
        manifest = instance.manifest
        managed = ManagedModule(
            manifest=manifest,
            status=ModuleStatus.LOADED,
            instance=instance,
        )
        with self._lock:
            self._modules[manifest.module_id] = managed
        if ready:
            instance.initialize(ModuleContext())
            managed.status = ModuleStatus.READY
        return managed
