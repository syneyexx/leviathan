"""One generic ExternalCapabilityModule — declarative manifests, no per-repo wrappers."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, Mapping

from ..types import (
    ModuleContext,
    ModuleHealth,
    ModuleManifest,
    ModuleResult,
    ModuleStatus,
)
from .adapters.composite import build_adapter
from .store import ExternalCapabilityStore
from .types import AdapterType, ExternalConfig, ExternalRuntimeState, parse_external_config


class ExternalCapabilityModule:
    """ILeviathanModule implementation driven entirely by module.json `external` config."""

    def __init__(self, manifest: ModuleManifest) -> None:
        self._manifest = manifest
        external_raw = (manifest.metadata or {}).get("external")
        config = parse_external_config(external_raw if isinstance(external_raw, Mapping) else None)
        if config is None:
            raise ValueError(f"Module {manifest.module_id} missing external config")
        self._config = config
        self._ctx_services: dict[str, Any] = {}
        self._adapter: Any = None
        self._store: ExternalCapabilityStore | None = None
        self._initialized = False

    @property
    def manifest(self) -> ModuleManifest:
        return self._manifest

    @property
    def external_config(self) -> ExternalConfig:
        return self._config

    def initialize(self, ctx: ModuleContext) -> None:
        self._ctx_services = dict(ctx.metadata or {})
        db_path = ctx.database_path or self._ctx_services.get("database_path")
        if db_path:
            self._store = ExternalCapabilityStore(Path(db_path))
            self._store.initialize()
            self._store.upsert_module(
                module_id=self._manifest.module_id,
                name=self._manifest.name,
                adapter=self._config.adapter.value,
                source=self._config.source.public_dict(),
                desired_state="STOPPED",
                runtime_state=ExternalRuntimeState.LOADED.value,
                capability_count=len(self._manifest.capabilities),
                metadata={
                    "tags": list(self._config.tags),
                    "domain": self._config.domain,
                    "version": self._manifest.version,
                },
            )
        install_root = None
        if self._store is not None:
            version = self._store.get_active_version(self._manifest.module_id)
            if version:
                install_root = version.get("install_root")
        from .adapters.base import AdapterContext

        adapter_ctx = AdapterContext(
            module_id=self._manifest.module_id,
            config=self._config,
            install_root=install_root,
            data_root=ctx.data_root,
            database_path=ctx.database_path,
            mcp_bridge=self._ctx_services.get("mcp_bridge"),
            artifact_store=self._ctx_services.get("artifact_store"),
            store=self._store,
            metadata=dict(self._ctx_services),
        )
        self._adapter = build_adapter(self._config.adapter, adapter_ctx)
        # Reconcile persisted RUNNING — never trust it blindly.
        if hasattr(self._adapter, "_reconcile_persisted"):
            try:
                self._adapter._reconcile_persisted()
            except Exception:  # noqa: BLE001
                pass
        elif self._store is not None:
            rec = self._store.get_module(self._manifest.module_id)
            if rec and rec.get("runtime_state") == ExternalRuntimeState.RUNNING.value:
                # Without an owned process adapter, mark STOPPED until ensure_ready.
                if self._config.adapter != AdapterType.PROCESS_SERVICE:
                    self._store.set_runtime_state(self._manifest.module_id, ExternalRuntimeState.STOPPED.value)
        self._initialized = True
        # Eager start only when explicitly configured.
        if self._config.runtime.eager_start:
            try:
                self._adapter.start()
            except Exception:  # noqa: BLE001 — optional module must not break boot
                if self._store is not None:
                    self._store.set_runtime_state(
                        self._manifest.module_id,
                        ExternalRuntimeState.FAILED.value,
                        last_error="eager_start_failed",
                    )

    def execute(self, operation: str, arguments: Mapping[str, Any]) -> ModuleResult:
        if not self._initialized or self._adapter is None:
            return ModuleResult(
                module_id=self._manifest.module_id,
                operation=operation,
                status="FAILED",
                error="module not initialized",
            )
        # Lifecycle operations routed uniformly.
        if operation == "ensure_installed":
            out = self._adapter.ensure_installed()
            return ModuleResult(module_id=self._manifest.module_id, operation=operation, status="COMPLETED", output=out if isinstance(out, dict) else {"result": out})
        if operation == "ensure_ready":
            out = self._adapter.ensure_ready()
            return ModuleResult(module_id=self._manifest.module_id, operation=operation, status="COMPLETED", output=out if isinstance(out, dict) else {"result": out})
        if operation == "start":
            out = self._adapter.start()
            return ModuleResult(module_id=self._manifest.module_id, operation=operation, status="COMPLETED", output=out if isinstance(out, dict) else {"result": out})
        if operation == "stop":
            out = self._adapter.stop()
            return ModuleResult(module_id=self._manifest.module_id, operation=operation, status="COMPLETED", output=out if isinstance(out, dict) else {"result": out})
        if operation == "restart":
            out = self._adapter.restart()
            return ModuleResult(module_id=self._manifest.module_id, operation=operation, status="COMPLETED", output=out if isinstance(out, dict) else {"result": out})
        if operation == "logs":
            lines = self._adapter.logs(limit=int(arguments.get("limit") or 200))
            return ModuleResult(module_id=self._manifest.module_id, operation=operation, status="COMPLETED", output={"lines": lines})
        if operation == "health":
            return ModuleResult(
                module_id=self._manifest.module_id,
                operation=operation,
                status="COMPLETED",
                output=self.health().public_dict(),
            )
        # Lazy ensure_ready for invoke paths.
        try:
            self._adapter.ensure_ready()
        except Exception as exc:  # noqa: BLE001
            return ModuleResult(
                module_id=self._manifest.module_id,
                operation=operation,
                status="FAILED",
                error=f"ensure_ready failed: {exc}",
            )
        return self._adapter.invoke(operation, arguments)

    def shutdown(self) -> None:
        if self._adapter is not None:
            try:
                # Do not force-stop unless desired state says so — idle shutdown is adapter-specific.
                if self._config.runtime.mode.value in {"RESIDENT", "LAZY"} and self._config.runtime.idle_timeout_seconds is None:
                    # Leave resident processes alone on module shutdown only if desired RUNNING —
                    # default: stop to avoid orphans.
                    pass
                self._adapter.stop()
            except Exception:  # noqa: BLE001
                pass
        self._initialized = False

    def health(self) -> ModuleHealth:
        if self._adapter is None:
            return ModuleHealth(module_id=self._manifest.module_id, status=ModuleStatus.ERROR, detail="not_initialized")
        return self._adapter.health()

    # Convenience lifecycle API used by ModuleManager extensions.
    def ensure_installed(self, **kwargs: Any) -> dict[str, Any]:
        assert self._adapter is not None
        return self._adapter.ensure_installed(**kwargs)

    def start(self) -> dict[str, Any]:
        assert self._adapter is not None
        return self._adapter.start()

    def stop(self) -> dict[str, Any]:
        assert self._adapter is not None
        return self._adapter.stop()

    def restart(self) -> dict[str, Any]:
        assert self._adapter is not None
        return self._adapter.restart()

    def ensure_ready(self) -> dict[str, Any]:
        assert self._adapter is not None
        return self._adapter.ensure_ready()

    def logs(self, *, limit: int = 200) -> list[str]:
        assert self._adapter is not None
        return self._adapter.logs(limit=limit)

    def runtime_state(self) -> str:
        if self._adapter is None:
            return ExternalRuntimeState.DISCOVERED.value
        return self._adapter.runtime_state().value


def create_external_capability_module(manifest: ModuleManifest | None = None) -> ExternalCapabilityModule:
    """Manifest-aware factory. ModuleManager passes manifest= when signature allows."""
    if manifest is None:
        raise TypeError(
            "create_external_capability_module requires manifest= "
            "(ModuleManager must call factory(manifest=...))"
        )
    return ExternalCapabilityModule(manifest)


# Alias used in module.json entrypoints.
factory = create_external_capability_module
