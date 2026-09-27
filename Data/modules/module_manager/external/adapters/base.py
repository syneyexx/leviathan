"""Adapter base protocol for the generic external capability fabric."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from ...types import ModuleHealth, ModuleResult
from ..types import ExternalConfig, ExternalRuntimeState


CancelCheck = Callable[[], bool]
ProgressCb = Callable[[float, str, str], None]


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


class ExternalAdapter(Protocol):
    def runtime_state(self) -> ExternalRuntimeState: ...

    def ensure_installed(self, *, progress: ProgressCb | None = None, cancel_check: CancelCheck | None = None) -> dict[str, Any]: ...

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
