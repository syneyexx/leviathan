"""llama.cpp runtime adapter boundary.

LEVIATHAN does not embed a full llama.cpp inference engine in this control-plane
phase. This adapter establishes the Runtime Manager contract and reports honest
capabilities. When a managed native runtime is wired later, load/unload/import
can be flipped to supported without changing higher layers.
"""

from __future__ import annotations

from typing import Any

from Data.modules.models.contracts import (
    LoadOptions,
    ModelDescriptor,
    ProviderHealth,
    RuntimeCapabilities,
)
from Data.modules.models.errors import CAPABILITY_NOT_SUPPORTED, ModelControlError


class LlamaCppAdapter:
    """Managed local runtime boundary — inference not integrated yet."""

    provider_type = "llama_cpp"

    def __init__(
        self,
        *,
        provider_id: str,
        endpoint: str = "",
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        managed: bool = False,
    ) -> None:
        self.provider_id = provider_id
        self.endpoint = endpoint
        self.api_key = api_key or ""
        self.timeout_seconds = timeout_seconds
        self.managed = managed
        # When a future native bridge is present, callers flip managed=True and
        # expand capabilities. Today we stay honest.
        self._capabilities = RuntimeCapabilities(
            discover_models=False,
            import_model=False,
            download_model=False,
            load_model=False,
            unload_model=False,
            delete_model=False,
            list_loaded_models=False,
            inference=False,
            streaming=False,
            embeddings=False,
            tool_calling=False,
            structured_output=False,
            vision=False,
            runtime_metrics=False,
            load_options=(
                "contextLength",
                "gpuOffloadLayers",
                "gpuMemoryLimitBytes",
                "cpuThreads",
                "batchSize",
                "flashAttention",
            ),
        )

    def capabilities(self) -> RuntimeCapabilities:
        return self._capabilities

    async def health(self) -> tuple[ProviderHealth, float | None, str | None]:
        if not self.managed:
            return (
                ProviderHealth.UNKNOWN,
                None,
                "llama.cpp managed runtime is not integrated yet",
            )
        return ProviderHealth.OFFLINE, None, "Managed runtime not reachable"

    async def discover(self) -> list[ModelDescriptor]:
        return []

    async def load(self, model_id: str, options: LoadOptions | None = None) -> dict[str, Any]:
        raise ModelControlError(
            code=CAPABILITY_NOT_SUPPORTED,
            message=(
                "llama.cpp load is reserved for a future managed native runtime; "
                "not integrated in this build"
            ),
            provider_id=self.provider_id,
            model_id=model_id,
            http_status=409,
            details={"runtime": "llama_cpp", "managed": self.managed},
        )

    async def unload(self, model_id: str) -> dict[str, Any]:
        raise ModelControlError(
            code=CAPABILITY_NOT_SUPPORTED,
            message="llama.cpp unload is not integrated in this build",
            provider_id=self.provider_id,
            model_id=model_id,
            http_status=409,
        )

    async def remove(self, model_id: str) -> None:
        raise ModelControlError(
            code=CAPABILITY_NOT_SUPPORTED,
            message="llama.cpp remove is not integrated in this build",
            provider_id=self.provider_id,
            model_id=model_id,
            http_status=409,
        )

    async def test_inference(
        self, model_id: str, *, prompt: str = "ping", max_tokens: int = 8
    ) -> dict[str, Any]:
        raise ModelControlError(
            code=CAPABILITY_NOT_SUPPORTED,
            message="llama.cpp inference is not integrated in this build",
            provider_id=self.provider_id,
            model_id=model_id,
            http_status=409,
        )
