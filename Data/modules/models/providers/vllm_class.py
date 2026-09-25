"""vLLM-class managed serving adapter (U022).

Same ManagedLocalServingAdapter surface as llama.cpp — different backend_kind.
No separate registry / routing / job DB.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, TYPE_CHECKING

from Data.modules.models.contracts import LoadOptions, ModelDescriptor, ProviderHealth, RuntimeCapabilities

if TYPE_CHECKING:
    from Data.modules.model_runtime.serving import StreamCancelToken


class VllmClassAdapter:
    """Managed vLLM-class (OpenAI-compatible local server) adapter."""

    provider_type = "vllm_class"

    def __init__(
        self,
        *,
        provider_id: str,
        endpoint: str = "http://127.0.0.1:8000/v1",
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        mode: str = "inproc",
        command: list[str] | None = None,
    ) -> None:
        from Data.modules.model_runtime.managed_adapter import ManagedLocalServingAdapter

        self.provider_id = provider_id
        self._inner = ManagedLocalServingAdapter(
            provider_id=provider_id,
            backend_kind="vllm_class",
            endpoint=endpoint,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            mode=mode if command else "inproc",
            command=command,
            allow_inproc_fixture=(mode == "inproc" and not command),
        )

    def capabilities(self) -> RuntimeCapabilities:
        return self._inner.capabilities()

    def reasoning_capability_profile(self) -> dict[str, Any]:
        """Honest default: vLLM-class endpoints do not invent reasoning knobs."""
        return {
            "supports_native_reasoning": False,
            "supported_efforts": [],
            "supports_reasoning_token_budget": False,
            "provider_family": "vllm_class",
            "resolution_source": "adapter",
            "notes": (
                "vllm_class_default_ttc — native_requires_explicit_affirmation",
            ),
        }

    async def health(self) -> tuple[ProviderHealth, float | None, str | None]:
        return await self._inner.health()

    async def discover(self) -> list[ModelDescriptor]:
        return await self._inner.discover()

    async def load(self, model_id: str, options: LoadOptions | None = None) -> dict[str, Any]:
        return await self._inner.load(model_id, options)

    async def unload(self, model_id: str) -> dict[str, Any]:
        return await self._inner.unload(model_id)

    async def remove(self, model_id: str) -> None:
        await self._inner.remove(model_id)

    async def test_inference(
        self, model_id: str, *, prompt: str = "ping", max_tokens: int = 8
    ) -> dict[str, Any]:
        return await self._inner.test_inference(model_id, prompt=prompt, max_tokens=max_tokens)

    async def stream_tokens(
        self,
        model_id: str,
        *,
        prompt: str,
        cancel: StreamCancelToken | None = None,
        max_tokens: int = 32,
    ) -> AsyncIterator[dict[str, Any]]:
        async for item in self._inner.stream_tokens(
            model_id, prompt=prompt, cancel=cancel, max_tokens=max_tokens
        ):
            yield item

    def reconcile_workers(self) -> list[dict[str, Any]]:
        return self._inner.reconcile_workers()
