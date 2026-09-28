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
        if ctx.data_root:
            self._ctx_services["data_root"] = ctx.data_root
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

        meta = dict(self._ctx_services)
        if getattr(self._manifest, "source_path", None):
            meta.setdefault("manifest_path", self._manifest.source_path)
        adapter_ctx = AdapterContext(
            module_id=self._manifest.module_id,
            config=self._config,
            install_root=install_root,
            data_root=ctx.data_root,
            database_path=ctx.database_path,
            mcp_bridge=self._ctx_services.get("mcp_bridge"),
            artifact_store=self._ctx_services.get("artifact_store"),
            store=self._store,
            metadata=meta,
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
        # Declared runtime.operations win over lifecycle shortcuts (e.g. Feynman/Selfstarter
        # CLI `status` must invoke the tool, not return ModuleHealth).
        declared_ops = {
            str(op.get("name") or op.get("operation") or "")
            for op in (self._config.runtime.operations or ())
            if isinstance(op, dict)
        }
        # Lifecycle operations routed uniformly (unless shadowed by a declared op).
        if operation == "ensure_installed" and operation not in declared_ops:
            out = self._adapter.ensure_installed()
            return ModuleResult(module_id=self._manifest.module_id, operation=operation, status="COMPLETED", output=out if isinstance(out, dict) else {"result": out})
        if operation == "ensure_ready" and operation not in declared_ops:
            out = self._adapter.ensure_ready()
            return ModuleResult(module_id=self._manifest.module_id, operation=operation, status="COMPLETED", output=out if isinstance(out, dict) else {"result": out})
        if operation == "start" and operation not in declared_ops:
            out = self._adapter.start()
            return ModuleResult(module_id=self._manifest.module_id, operation=operation, status="COMPLETED", output=out if isinstance(out, dict) else {"result": out})
        if operation == "stop" and operation not in declared_ops:
            out = self._adapter.stop()
            return ModuleResult(module_id=self._manifest.module_id, operation=operation, status="COMPLETED", output=out if isinstance(out, dict) else {"result": out})
        if operation == "restart" and operation not in declared_ops:
            out = self._adapter.restart()
            return ModuleResult(module_id=self._manifest.module_id, operation=operation, status="COMPLETED", output=out if isinstance(out, dict) else {"result": out})
        if operation == "logs" and operation not in declared_ops:
            lines = self._adapter.logs(limit=int(arguments.get("limit") or 200))
            return ModuleResult(module_id=self._manifest.module_id, operation=operation, status="COMPLETED", output={"lines": lines})
        if operation in {"health", "status"} and operation not in declared_ops:
            health = self.health().public_dict()
            # Prefer adapter status() when present (MCP/process), else health snapshot.
            status_out = health
            status_fn = getattr(self._adapter, "status", None)
            if callable(status_fn):
                try:
                    maybe = status_fn()
                    if isinstance(maybe, dict):
                        status_out = {**health, **maybe}
                except Exception:  # noqa: BLE001
                    pass
            return ModuleResult(
                module_id=self._manifest.module_id,
                operation=operation,
                status="COMPLETED",
                output=status_out,
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

    def check_update(self) -> dict[str, Any]:
        from .versions import check_update

        return check_update(module_id=self._manifest.module_id, config=self._config, store=self._store)

    def install_version(
        self,
        *,
        ref: str | None = None,
        activate: bool = False,
        active_jobs: list[str] | None = None,
        progress: Any = None,
        cancel_check: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        from .versions import install_version

        data_root = self._ctx_services.get("data_root")
        if not data_root and self._adapter is not None:
            data_root = getattr(getattr(self._adapter, "ctx", None), "data_root", None)
        if not data_root:
            from .types import ExternalFailureCode
            from .versions import VersionError

            raise VersionError(ExternalFailureCode.INSTALL_FAILED, "data_root required for install_version")
        result = install_version(
            module_id=self._manifest.module_id,
            config=self._config,
            data_root=data_root,
            store=kwargs.get("store", self._store),
            ref=ref,
            activate=activate,
            active_jobs=active_jobs,
            progress=progress,
            cancel_check=cancel_check,
            force=bool(kwargs.get("force", False)),
            plan_hash=kwargs.get("plan_hash"),
            operation_id=kwargs.get("operation_id"),
            auto_resolve_dependencies=bool(kwargs.get("auto_resolve_dependencies", True)),
            approved_plan=kwargs.get("approved_plan"),
            allow_system_deps=bool(kwargs.get("allow_system_deps", False)),
            runner=kwargs.get("runner"),
        )
        if activate and self._adapter is not None and result.get("install_root"):
            self._adapter._install_root = result["install_root"]
        return result

    def activate_version(self, version_id: str, *, active_jobs: list[str] | None = None) -> dict[str, Any]:
        from .versions import activate_version

        return activate_version(
            module_id=self._manifest.module_id,
            version_id=version_id,
            store=self._store,
            active_jobs=active_jobs,
            adapter=self._adapter,
        )

    def rollback_version(
        self,
        *,
        version_id: str | None = None,
        active_jobs: list[str] | None = None,
    ) -> dict[str, Any]:
        from .versions import rollback_version

        return rollback_version(
            module_id=self._manifest.module_id,
            store=self._store,
            active_jobs=active_jobs,
            adapter=self._adapter,
            version_id=version_id,
        )

    def maybe_idle_shutdown(self) -> dict[str, Any] | None:
        """Stop LAZY/RESIDENT processes that exceeded idle_timeout with no active jobs."""
        if self._adapter is None:
            return None
        if hasattr(self._adapter, "maybe_idle_shutdown"):
            return self._adapter.maybe_idle_shutdown()
        return None

    def list_versions(self) -> list[dict[str, Any]]:
        if self._store is None:
            return []
        return self._store.list_versions(self._manifest.module_id)


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
