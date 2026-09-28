"""SCRIPT_PACKAGE adapter — deterministic reusable scripts via CLI runner."""

from __future__ import annotations

from typing import Any, Mapping

from ...types import ModuleHealth, ModuleResult
from ..types import ExternalRuntimeState
from .base import AdapterContext, CancelCheck, ProgressCb
from .cli import CliAdapter


class ScriptPackageAdapter:
    """Thin specialization of CLI for package-local scripts (npm/node/python scripts)."""

    def __init__(self, ctx: AdapterContext) -> None:
        self.ctx = ctx
        self._cli = CliAdapter(ctx)
        self._state = ExternalRuntimeState.DISCOVERED

    def runtime_state(self) -> ExternalRuntimeState:
        return self._cli.runtime_state()

    def ensure_installed(self, **kwargs: Any) -> dict[str, Any]:
        return self._cli.ensure_installed(**kwargs)

    def start(self) -> dict[str, Any]:
        return self._cli.start()

    def stop(self) -> dict[str, Any]:
        return self._cli.stop()

    def restart(self) -> dict[str, Any]:
        return self._cli.restart()

    def ensure_ready(self) -> dict[str, Any]:
        return self._cli.ensure_ready()

    def health(self) -> ModuleHealth:
        return self._cli.health()

    def logs(self, *, limit: int = 200) -> list[str]:
        return self._cli.logs(limit=limit)

    def invoke(
        self,
        operation: str,
        arguments: Mapping[str, Any],
        *,
        progress: ProgressCb | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> ModuleResult:
        # Map script operation names onto configured runtime.operations / command.
        return self._cli.invoke(operation, arguments, progress=progress, cancel_check=cancel_check)
