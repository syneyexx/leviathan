"""llama.cpp / GGUF managed serving adapter (U023).

EXTENDS the prior boundary stub: when managed+inproc (or subprocess command
configured), load/unload/stream are real supervised operations. Missing binary
stays UNAVAILABLE — never fabricated READY.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, TYPE_CHECKING

from Data.modules.models.contracts import LoadOptions, ModelDescriptor, ProviderHealth, RuntimeCapabilities

if TYPE_CHECKING:
    from Data.modules.model_runtime.serving import StreamCancelToken


def _managed_adapter(
    *,
    provider_id: str,
    endpoint: str,
    api_key: str | None,
    timeout_seconds: float,
    mode: str,
    command: list[str] | None,
):
    from Data.modules.model_runtime.managed_adapter import ManagedLocalServingAdapter

    return ManagedLocalServingAdapter(
        provider_id=provider_id,
        backend_kind="llama_cpp",
        endpoint=endpoint or "inproc://llama_cpp",
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        mode=mode if command else "inproc",
        command=command,
    )


class LlamaCppAdapter:
    """Managed llama.cpp serving path under the Model Control Plane."""

    provider_type = "llama_cpp"

    def __init__(
        self,
        *,
        provider_id: str,
        endpoint: str = "",
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        managed: bool = False,
        mode: str | None = None,
        command: list[str] | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.endpoint = endpoint
        self.api_key = api_key or ""
        self.timeout_seconds = timeout_seconds
        self.managed = managed
        resolved_mode = mode or ("inproc" if managed else "subprocess")
        self._inner = None
        if managed:
            self._inner = _managed_adapter(
                provider_id=provider_id,
                endpoint=endpoint,
                api_key=api_key,
                timeout_seconds=timeout_seconds,
                mode=resolved_mode,
                command=command,
            )
            self._capabilities = self._inner.capabilities()
        else:
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
        if self._inner is None:
            return (
                ProviderHealth.UNKNOWN,
                None,
                "llama.cpp managed runtime not enabled (set metadata.managed=true)",
            )
        return await self._inner.health()

    async def discover(self) -> list[ModelDescriptor]:
        if self._inner is None:
            return []
        return await self._inner.discover()

    async def load(self, model_id: str, options: LoadOptions | None = None) -> dict[str, Any]:
        if self._inner is None:
            from Data.modules.models.errors import CAPABILITY_NOT_SUPPORTED, ModelControlError

            raise ModelControlError(
                code=CAPABILITY_NOT_SUPPORTED,
                message=(
                    "llama.cpp load requires managed=true; "
                    "unmanaged external servers use openai_compatible/lm_studio providers"
                ),
                provider_id=self.provider_id,
                model_id=model_id,
                http_status=409,
                details={"runtime": "llama_cpp", "managed": False},
            )
        return await self._inner.load(model_id, options)

    async def unload(self, model_id: str) -> dict[str, Any]:
        if self._inner is None:
            from Data.modules.models.errors import CAPABILITY_NOT_SUPPORTED, ModelControlError

            raise ModelControlError(
                code=CAPABILITY_NOT_SUPPORTED,
                message="llama.cpp unload requires managed=true",
                provider_id=self.provider_id,
                model_id=model_id,
                http_status=409,
            )
        return await self._inner.unload(model_id)

    async def remove(self, model_id: str) -> None:
        if self._inner is None:
            from Data.modules.models.errors import CAPABILITY_NOT_SUPPORTED, ModelControlError

            raise ModelControlError(
                code=CAPABILITY_NOT_SUPPORTED,
                message="llama.cpp remove requires managed=true",
                provider_id=self.provider_id,
                model_id=model_id,
                http_status=409,
            )
        await self._inner.remove(model_id)

    async def test_inference(
        self, model_id: str, *, prompt: str = "ping", max_tokens: int = 8
    ) -> dict[str, Any]:
        if self._inner is None:
            from Data.modules.models.errors import CAPABILITY_NOT_SUPPORTED, ModelControlError

            raise ModelControlError(
                code=CAPABILITY_NOT_SUPPORTED,
                message="llama.cpp inference requires managed=true",
                provider_id=self.provider_id,
                model_id=model_id,
                http_status=409,
            )
        return await self._inner.test_inference(model_id, prompt=prompt, max_tokens=max_tokens)

    async def stream_tokens(
        self,
        model_id: str,
        *,
        prompt: str,
        cancel: StreamCancelToken | None = None,
        max_tokens: int = 32,
    ) -> AsyncIterator[dict[str, Any]]:
        if self._inner is None:
            from Data.modules.models.errors import CAPABILITY_NOT_SUPPORTED, ModelControlError

            raise ModelControlError(
                code=CAPABILITY_NOT_SUPPORTED,
                message="llama.cpp streaming requires managed=true",
                provider_id=self.provider_id,
                model_id=model_id,
                http_status=409,
            )
        async for item in self._inner.stream_tokens(
            model_id, prompt=prompt, cancel=cancel, max_tokens=max_tokens
        ):
            yield item

    def reconcile_workers(self) -> list[dict[str, Any]]:
        if self._inner is None:
            return []
        return self._inner.reconcile_workers()
