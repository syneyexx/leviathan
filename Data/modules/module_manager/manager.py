from __future__ import annotations

import importlib
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .discovery import ManifestError, discover_manifest_paths, load_manifest_file
from .types import (
    ILeviathanModule,
    ModuleContext,
    ModuleHealth,
    ModuleManifest,
    ModuleResult,
    ModuleStatus,
)


class ModuleManagerError(RuntimeError):
    pass


@dataclass
class ManagedModule:
    manifest: ModuleManifest
    status: ModuleStatus = ModuleStatus.DISCOVERED
    instance: ILeviathanModule | None = None
    error: str | None = None
    last_result: ModuleResult | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.public_dict(),
            "status": self.status.value,
            "error": self.error,
            "last_result": self.last_result.public_dict() if self.last_result else None,
            "health": (
                self.instance.health().public_dict()
                if self.instance is not None and self.status not in {ModuleStatus.ERROR, ModuleStatus.SHUTDOWN}
                else None
            ),
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
    _modules: dict[str, ManagedModule] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)
    telemetry: dict[str, Any] = field(
        default_factory=lambda: {
            "discovered": 0,
            "loaded": 0,
            "initialized": 0,
            "execute_calls": 0,
            "execute_failures": 0,
            "reload_attempts": 0,
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
                if existing and existing.status in {ModuleStatus.READY, ModuleStatus.INITIALIZED, ModuleStatus.LOADED}:
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
            instance = factory()
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
        try:
            managed.instance.initialize(ctx or ModuleContext())
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
        if managed.instance is None or managed.status not in {ModuleStatus.READY, ModuleStatus.INITIALIZED}:
            raise ModuleManagerError(f"Module not ready: {module_id} ({managed.status.value})")
        self.telemetry["execute_calls"] += 1
        managed.status = ModuleStatus.EXECUTING
        started = time.perf_counter()
        args = dict(arguments or {})

        def _call() -> ModuleResult:
            assert managed.instance is not None
            return managed.instance.execute(operation, args)

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_call)
                result = future.result(timeout=self.execute_timeout_seconds)
            if not isinstance(result, ModuleResult):
                raise ModuleManagerError("Module execute must return ModuleResult")
            managed.last_result = result
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
                },
            }

    def _require(self, module_id: str) -> ManagedModule:
        with self._lock:
            managed = self._modules.get(module_id)
            if managed is None:
                raise ModuleManagerError(f"Unknown module: {module_id}")
            return managed

    @staticmethod
    def _resolve_factory(entrypoint: str) -> Callable[[], Any]:
        module_name, _, attr = entrypoint.partition(":")
        if not module_name or not attr:
            raise ModuleManagerError(f"Invalid entrypoint: {entrypoint}")
        module = importlib.import_module(module_name)
        factory = getattr(module, attr, None)
        if factory is None or not callable(factory):
            raise ModuleManagerError(f"Entrypoint not callable: {entrypoint}")
        return factory

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
