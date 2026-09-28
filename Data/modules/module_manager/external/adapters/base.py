"""Adapter base protocol for the generic external capability fabric."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from ...types import ModuleHealth, ModuleResult
from ..types import ExternalConfig, ExternalRuntimeState


CancelCheck = Callable[[], bool]
ProgressCb = Callable[[float, str, str], None]

# Kwargs accepted by InstallationService.ensure_installed (and adapter forwards).
INSTALL_SERVICE_KWARGS = (
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
    "progress",
    "cancel_check",
)


@dataclass
class AdapterContext:
    module_id: str
    config: ExternalConfig
    install_root: str | None = None
    data_root: str | None = None
    database_path: str | None = None
    mcp_bridge: Any = None
    artifact_store: Any = None
    store: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


def forward_install_kwargs(ctx: AdapterContext, kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Build InstallationService.ensure_installed kwargs; default store to ctx.store."""
    return {
        "progress": kwargs.get("progress"),
        "cancel_check": kwargs.get("cancel_check"),
        "ref": kwargs.get("ref"),
        "force": bool(kwargs.get("force", False)),
        "activate": bool(kwargs.get("activate", False)),
        "plan_hash": kwargs.get("plan_hash"),
        "operation_id": kwargs.get("operation_id"),
        "auto_resolve_dependencies": bool(kwargs.get("auto_resolve_dependencies", True)),
        "approved_plan": kwargs.get("approved_plan"),
        "allow_system_deps": bool(kwargs.get("allow_system_deps", False)),
        "runner": kwargs.get("runner"),
        "store": kwargs["store"] if "store" in kwargs else ctx.store,
    }


class ExternalAdapter(Protocol):
    def runtime_state(self) -> ExternalRuntimeState: ...

    def ensure_installed(self, **kwargs: Any) -> dict[str, Any]: ...

    def start(self) -> dict[str, Any]: ...

    def stop(self) -> dict[str, Any]: ...

    def restart(self) -> dict[str, Any]: ...

    def ensure_ready(self) -> dict[str, Any]: ...

    def health(self) -> ModuleHealth: ...

    def logs(self, *, limit: int = 200) -> list[str]: ...

    def invoke(
        self,
        operation: str,
        arguments: Mapping[str, Any],
        *,
        progress: ProgressCb | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> ModuleResult: ...
