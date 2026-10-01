from __future__ import annotations

from typing import Any, Callable, Mapping

from .killable_exec import KillableModuleExecutor


class SubprocessModuleExecutor:
    """Execute a module operation in an isolated killable Python subprocess.

    Used for untrusted ModelData plugins when isolation=SUBPROCESS, and as the
    ModuleManager containment boundary for timed external/untrusted/mutating work.

    Does not grant gateway authority — still advisory/module-local only.
    Delegates to KillableModuleExecutor (hard timeout, process-tree kill, drain,
    cancel, lease fencing). ThreadPoolExecutor timeouts are never used here.
    """

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds
        self._impl = KillableModuleExecutor(timeout_seconds=timeout_seconds)

    def execute(
        self,
        *,
        entrypoint: str,
        operation: str,
        arguments: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        lease_token: str | None = None,
    ) -> dict[str, Any]:
        result = self._impl.execute(
            entrypoint=entrypoint,
            operation=operation,
            arguments=arguments,
            context=context,
            cancel_check=cancel_check,
            lease_token=lease_token,
        )
        return result.public_dict()
