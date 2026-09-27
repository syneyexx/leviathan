from __future__ import annotations

import importlib
import inspect
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .discovery import ManifestError, discover_manifest_paths, load_manifest_file
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

# Statuses that may accept execute / ensure_ready without re-init.
_READY_STATUSES = {
    ModuleStatus.READY,
    ModuleStatus.INITIALIZED,
    ModuleStatus.RUNNING,
    ModuleStatus.BUSY,
    ModuleStatus.INSTALLED,
    ModuleStatus.DEGRADED,
}


class ModuleManagerError(RuntimeError):
    pass


@dataclass
class ManagedModule:
    manifest: ModuleManifest
    status: ModuleStatus = ModuleStatus.DISCOVERED
    instance: ILeviathanModule | None = None
    error: str | None = None
    last_result: ModuleResult | None = None
    desired_state: str | None = None
    active_jobs: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        runtime_state = self.status.value
        adapter = None
        external = (self.manifest.metadata or {}).get("external")
        if isinstance(external, dict):
            adapter = external.get("adapter")
        if self.instance is not None and hasattr(self.instance, "runtime_state"):
            try:
                runtime_state = str(self.instance.runtime_state())
            except Exception:  # noqa: BLE001
                pass
        return {
            "manifest": self.manifest.public_dict(),
            "status": self.status.value,
            "runtime_state": runtime_state,
            "desired_state": self.desired_state,
            "adapter": adapter,
            "error": self.error,
            "active_jobs": list(self.active_jobs),
            "last_result": self.last_result.public_dict() if self.last_result else None,
            "health": (
                self.instance.health().public_dict()
                if self.instance is not None
                and self.status
                not in {
                    ModuleStatus.ERROR,
                    ModuleStatus.FAILED,
                    ModuleStatus.SHUTDOWN,
                }
                else None
            ),
            "truth": {
                "persisted_or_declared_state_is_not_live_health": True,
                "module_manager_is_lifecycle_owner": True,
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
            raise ModuleManagerError(managed.error) from exc
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

    def ensure_installed(self, module_id: str, **kwargs: Any) -> dict[str, Any]:
        managed = self._ensure_instance(module_id)
        assert managed.instance is not None
        if hasattr(managed.instance, "ensure_installed"):
            result = managed.instance.ensure_installed(**kwargs)
            managed.status = ModuleStatus.INSTALLED
            return result if isinstance(result, dict) else {"result": result}
        return {"status": "INSTALLED", "detail": "no_install_required"}

    def start(self, module_id: str) -> dict[str, Any]:
        managed = self._ensure_instance(module_id)
        assert managed.instance is not None
        managed.status = ModuleStatus.STARTING
        managed.desired_state = "RUNNING"
        try:
            if hasattr(managed.instance, "start"):
                result = managed.instance.start()
            else:
                result = {"status": "READY", "detail": "start_noop"}
            managed.status = ModuleStatus.RUNNING if str((result or {}).get("status", "")).upper() == "RUNNING" else ModuleStatus.READY
            managed.error = None
            return result if isinstance(result, dict) else {"result": result}
        except Exception as exc:  # noqa: BLE001
            managed.status = ModuleStatus.FAILED
            managed.error = str(exc)
            raise ModuleManagerError(f"start failed: {exc}") from exc

    def stop(self, module_id: str) -> dict[str, Any]:
        managed = self._ensure_instance(module_id)
        assert managed.instance is not None
        managed.status = ModuleStatus.STOPPING
        managed.desired_state = "STOPPED"
        try:
            if hasattr(managed.instance, "stop"):
                result = managed.instance.stop()
            else:
                result = {"status": "STOPPED", "detail": "stop_noop"}
            managed.status = ModuleStatus.STOPPED
            return result if isinstance(result, dict) else {"result": result}
        except Exception as exc:  # noqa: BLE001
            managed.status = ModuleStatus.FAILED
            managed.error = str(exc)
            raise ModuleManagerError(f"stop failed: {exc}") from exc

    def restart(self, module_id: str) -> dict[str, Any]:
        self.stop(module_id)
        return self.start(module_id)

    def ensure_ready(self, module_id: str) -> dict[str, Any]:
        managed = self._ensure_instance(module_id)
        assert managed.instance is not None
        try:
            if hasattr(managed.instance, "ensure_ready"):
                result = managed.instance.ensure_ready()
            else:
                if managed.status not in _READY_STATUSES:
                    self.initialize(module_id, self._last_context)
                result = {"ready": True, "status": managed.status.value}
            if isinstance(result, dict) and result.get("ready"):
                status = str(result.get("status") or "").upper()
                if status == "RUNNING":
                    managed.status = ModuleStatus.RUNNING
                elif managed.status not in {ModuleStatus.RUNNING, ModuleStatus.BUSY}:
                    managed.status = ModuleStatus.READY
            return result if isinstance(result, dict) else {"ready": True, "result": result}
        except Exception as exc:  # noqa: BLE001
            managed.status = ModuleStatus.FAILED
            managed.error = str(exc)
            raise ModuleManagerError(f"ensure_ready failed: {exc}") from exc

    def health(self, module_id: str) -> ModuleHealth:
        managed = self._ensure_instance(module_id)
        assert managed.instance is not None
        return managed.instance.health()

    def logs(self, module_id: str, *, limit: int = 200) -> list[str]:
        managed = self._ensure_instance(module_id)
        assert managed.instance is not None
        if hasattr(managed.instance, "logs"):
            return list(managed.instance.logs(limit=limit))
        return []

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

    def public_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "modules": [item.public_dict() for item in self.list()],
                "telemetry": dict(self.telemetry),
                "discovery_roots": [str(path) for path in self.discovery_roots],
                "truth": {
                    "module_manager_is_not_execution_gateway": True,
                    "discoverable_is_not_authorized": True,
                    "persisted_running_is_not_live_running": True,
                },
            }

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
                raise ModuleManagerError(f"Unknown module: {module_id}")
            return managed

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
