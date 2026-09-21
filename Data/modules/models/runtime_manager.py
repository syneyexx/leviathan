"""Runtime manager — capability-gated lifecycle operations."""

from __future__ import annotations

import threading
from typing import Any, Callable

from Data.modules.models.contracts import (
    LoadOptions,
    ModelHealthState,
    ModelLifecycleState,
    PreflightVerdict,
)
from Data.modules.models.errors import (
    CAPABILITY_NOT_SUPPORTED,
    INSUFFICIENT_MEMORY,
    MODEL_LOAD_FAILED,
    MODEL_UNLOAD_FAILED,
    OPERATION_CONFLICT,
    ModelControlError,
)
from Data.modules.models.registry import ModelRegistry
from Data.modules.models.resource_manager import ResourceManager


class RuntimeManager:
    def __init__(
        self,
        registry: ModelRegistry,
        resource_manager: ResourceManager,
        *,
        get_adapter: Callable[[str], Any],
    ) -> None:
        self.registry = registry
        self.resource_manager = resource_manager
        self._get_adapter = get_adapter
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._busy: set[str] = set()

    def _model_lock(self, model_id: str) -> threading.Lock:
        with self._locks_guard:
            if model_id not in self._locks:
                self._locks[model_id] = threading.Lock()
            return self._locks[model_id]

    def _begin(self, model_id: str, operation: str) -> None:
        lock = self._model_lock(model_id)
        if not lock.acquire(blocking=False):
            raise ModelControlError(
                code=OPERATION_CONFLICT,
                message=f"Model {model_id} is busy with another lifecycle operation",
                model_id=model_id,
                http_status=409,
                details={"operation": operation},
            )
        self._busy.add(model_id)

    def _end(self, model_id: str) -> None:
        self._busy.discard(model_id)
        self._model_lock(model_id).release()

    async def load(
        self,
        model_id: str,
        options: LoadOptions | None = None,
        *,
        confirm_oom: bool = False,
    ) -> dict[str, Any]:
        model = self.registry.get(model_id)
        adapter = self._get_adapter(model.provider_id)
        caps = adapter.capabilities()
        if not caps.load_model:
            raise ModelControlError(
                code=CAPABILITY_NOT_SUPPORTED,
                message=(
                    f"Provider {model.provider_id} does not support programmatic load"
                ),
                provider_id=model.provider_id,
                model_id=model_id,
                http_status=409,
                details={
                    "hint": "Managed externally by the runtime" if model.runtime_id == "lm_studio" else None
                },
            )

        preflight = self.resource_manager.preflight(
            model, requested_context=options.context_length if options else None
        )
        if preflight.verdict == PreflightVerdict.LIKELY_OOM and not confirm_oom:
            raise ModelControlError(
                code=INSUFFICIENT_MEMORY,
                message="Preflight estimates likely OOM; confirm to proceed",
                model_id=model_id,
                http_status=409,
                details=preflight.public_dict(),
                retryable=False,
            )

        self._begin(model_id, "load")
        try:
            self.registry.set_lifecycle(model_id, ModelLifecycleState.LOADING)
            allowed = caps.load_options
            payload_options = options.as_provider_payload(allowed) if options else {}
            # Only pass LoadOptions fields the provider listed.
            load_opts = None
            if options and payload_options:
                load_opts = options
            result = await adapter.load(model_id, load_opts)
            updated = self.registry.set_lifecycle(
                model_id,
                ModelLifecycleState.LOADED,
                health=ModelHealthState.HEALTHY,
                loaded=True,
            )
            return {
                "model": updated.public_dict(),
                "preflight": preflight.public_dict(),
                "providerResult": result,
            }
        except ModelControlError as exc:
            self.registry.set_lifecycle(
                model_id,
                ModelLifecycleState.ERROR,
                health=ModelHealthState.ERROR,
                loaded=False,
                error=str(exc),
            )
            if exc.code == CAPABILITY_NOT_SUPPORTED:
                raise
            raise ModelControlError(
                code=MODEL_LOAD_FAILED,
                message=exc.message,
                provider_id=model.provider_id,
                model_id=model_id,
                retryable=exc.retryable,
                http_status=exc.http_status,
                details=exc.details,
            ) from exc
        except Exception as exc:  # noqa: BLE001 — convert to structured failure
            self.registry.set_lifecycle(
                model_id,
                ModelLifecycleState.ERROR,
                health=ModelHealthState.ERROR,
                loaded=False,
                error=str(exc),
            )
            raise ModelControlError(
                code=MODEL_LOAD_FAILED,
                message=f"Load failed: {exc}",
                provider_id=model.provider_id,
                model_id=model_id,
                http_status=500,
            ) from exc
        finally:
            self._end(model_id)

    async def unload(self, model_id: str) -> dict[str, Any]:
        model = self.registry.get(model_id)
        adapter = self._get_adapter(model.provider_id)
        caps = adapter.capabilities()
        if not caps.unload_model:
            raise ModelControlError(
                code=CAPABILITY_NOT_SUPPORTED,
                message=f"Provider {model.provider_id} does not support programmatic unload",
                provider_id=model.provider_id,
                model_id=model_id,
                http_status=409,
                details={"hint": "Managed externally by the runtime"},
            )

        self._begin(model_id, "unload")
        try:
            self.registry.set_lifecycle(model_id, ModelLifecycleState.UNLOADING)
            result = await adapter.unload(model_id)
            updated = self.registry.set_lifecycle(
                model_id,
                ModelLifecycleState.AVAILABLE,
                health=ModelHealthState.HEALTHY,
                loaded=False,
            )
            return {"model": updated.public_dict(), "providerResult": result}
        except ModelControlError as exc:
            self.registry.set_lifecycle(
                model_id,
                ModelLifecycleState.ERROR,
                health=ModelHealthState.ERROR,
                error=str(exc),
            )
            if exc.code == CAPABILITY_NOT_SUPPORTED:
                raise
            raise ModelControlError(
                code=MODEL_UNLOAD_FAILED,
                message=exc.message,
                provider_id=model.provider_id,
                model_id=model_id,
                http_status=exc.http_status,
                details=exc.details,
            ) from exc
        finally:
            self._end(model_id)
