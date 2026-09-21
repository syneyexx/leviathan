from __future__ import annotations

from typing import Any, Mapping

from Data.modules.module_manager.types import (
    CapabilityAnnouncement,
    ModuleContext,
    ModuleHealth,
    ModuleManifest,
    ModuleResult,
    ModuleStatus,
)


class EchoNeuroModule:
    """First-party example implementing ILeviathanModule — no parallel infrastructure."""

    def __init__(self) -> None:
        self._initialized = False
        self._manifest = ModuleManifest(
            module_id="neuro.echo",
            name="Neuro Echo Module",
            version="0.1.0",
            entrypoint="Data.modules.neuro.echo_module:create_echo_module",
            capabilities=(
                CapabilityAnnouncement(
                    capability_id="neuro.echo.ping",
                    name="Neuro Echo Ping",
                    description="Module-local ping; not a gateway capability by itself.",
                    external_name="ping",
                    side_effects=("READ",),
                ),
            ),
            permissions=("neuro.read",),
            side_effects=("READ",),
            hot_reload=True,
            neuro_hooks=("advisory",),
            metadata={"first_party": True},
        )

    @property
    def manifest(self) -> ModuleManifest:
        return self._manifest

    def initialize(self, ctx: ModuleContext) -> None:
        self._initialized = True
        self._ctx = ctx

    def execute(self, operation: str, arguments: Mapping[str, Any]) -> ModuleResult:
        if not self._initialized:
            return ModuleResult(
                module_id=self._manifest.module_id,
                operation=operation,
                status="FAILED",
                error="Module not initialized",
            )
        if operation != "ping":
            return ModuleResult(
                module_id=self._manifest.module_id,
                operation=operation,
                status="REJECTED",
                error=f"Unknown operation: {operation}",
            )
        message = str(arguments.get("message") or "pong")
        return ModuleResult(
            module_id=self._manifest.module_id,
            operation=operation,
            status="COMPLETED",
            output={"echo": message, "flags": dict(self._ctx.feature_flags)},
        )

    def shutdown(self) -> None:
        self._initialized = False

    def health(self) -> ModuleHealth:
        return ModuleHealth(
            module_id=self._manifest.module_id,
            status=ModuleStatus.READY if self._initialized else ModuleStatus.LOADED,
            detail="ok" if self._initialized else "not initialized",
        )


def create_echo_module() -> EchoNeuroModule:
    return EchoNeuroModule()
